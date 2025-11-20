/**
 * macOS Core Audio Process Tap Native Extension
 * プロセスの音声をキャプチャするObjective-C拡張モジュール
 *
 * 最適化ポイント:
 * 1. サブプロセスオーバーヘッド削減 (37ms → 0ms)
 * 2. Pre-allocated buffers
 * 3. Aggregate device作成の最適化
 * 4. 非同期初期化
 *
 * 目標レイテンシー: 500ms以下
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#import <Foundation/Foundation.h>
#import <CoreAudio/CoreAudio.h>
#import <AudioToolbox/AudioToolbox.h>
#import <objc/runtime.h>
#import <CoreGraphics/CoreGraphics.h>
#import <IOSurface/IOSurface.h>
#import <CoreVideo/CoreVideo.h>
#include <pthread.h>
#include <stdatomic.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>

// Forward declarations for macOS 14.4+ APIs (not in public headers)
// These are available at runtime on macOS 14.4+

#ifdef __cplusplus
extern "C" {
#endif

// CATapDescription class (Objective-C class, declared in CoreAudio framework)
// We'll access this via objc_getClass at runtime
// Note: We only declare the methods we actually use
@interface CATapDescription : NSObject
- (instancetype)initStereoMixdownOfProcesses:(NSArray<NSNumber*>*)processes;
- (instancetype)initMonoMixdownOfProcesses:(NSArray<NSNumber*>*)processes;
- (instancetype)initStereoGlobalTapButExcludeProcesses:(NSArray<NSNumber*>*)processes;
- (instancetype)initMonoGlobalTapButExcludeProcesses:(NSArray<NSNumber*>*)processes;
- (void)setMono:(BOOL)mono;
- (void)setMixdown:(BOOL)mixdown;
- (void)setExclusive:(BOOL)exclusive;
- (void)setPrivate:(BOOL)isPrivate;
// Don't declare UUID property to avoid semantics conflicts - we'll set it via KVC or raw ivar access
@end

// Core Audio Process Tap functions (macOS 14.4+)
OSStatus AudioHardwareCreateProcessTap(CATapDescription* tap_description, AudioObjectID* out_tap_id);
OSStatus AudioHardwareDestroyProcessTap(AudioObjectID tap_id);

#ifdef __cplusplus
}
#endif

// Ring buffer for audio data
#define RING_BUFFER_SIZE (1024 * 1024 * 4)  // 4MB ring buffer

typedef struct {
    uint8_t* data;
    size_t size;
    atomic_size_t write_pos;
    atomic_size_t read_pos;
    pthread_mutex_t lock;
} RingBuffer;

// Process Tap state
typedef struct {
    // Core Audio objects
    AudioObjectID tap_id;
    AudioObjectID device_id;
    AudioDeviceIOProcID io_proc_id;

    // Configuration
    UInt32 sample_rate;
    UInt32 channels;
    UInt32 bits_per_sample;
    AudioStreamBasicDescription format;  // Tap stream format

    // PIDs
    pid_t* include_pids;
    size_t include_count;
    pid_t* exclude_pids;
    size_t exclude_count;

    // Buffer
    RingBuffer* ring_buffer;

    // State
    atomic_bool is_running;
    atomic_bool is_initialized;

    // Error handling
    OSStatus last_error;
    char error_message[256];
} ProcessTapState;

// ============================================================================
// Ring Buffer Implementation
// ============================================================================

static RingBuffer* ring_buffer_create(size_t size) {
    RingBuffer* rb = (RingBuffer*)malloc(sizeof(RingBuffer));
    if (!rb) return NULL;

    rb->data = (uint8_t*)malloc(size);
    if (!rb->data) {
        free(rb);
        return NULL;
    }

    rb->size = size;
    atomic_init(&rb->write_pos, 0);
    atomic_init(&rb->read_pos, 0);
    pthread_mutex_init(&rb->lock, NULL);

    return rb;
}

static void ring_buffer_destroy(RingBuffer* rb) {
    if (!rb) return;

    pthread_mutex_destroy(&rb->lock);
    free(rb->data);
    free(rb);
}

static size_t ring_buffer_available(RingBuffer* rb) {
    size_t write_pos = atomic_load(&rb->write_pos);
    size_t read_pos = atomic_load(&rb->read_pos);

    if (write_pos >= read_pos) {
        return write_pos - read_pos;
    } else {
        return rb->size - read_pos + write_pos;
    }
}

static size_t ring_buffer_write(RingBuffer* rb, const uint8_t* data, size_t len) {
    pthread_mutex_lock(&rb->lock);

    size_t write_pos = atomic_load(&rb->write_pos);
    size_t read_pos = atomic_load(&rb->read_pos);

    // Calculate available space
    size_t available_space;
    if (write_pos >= read_pos) {
        available_space = rb->size - (write_pos - read_pos) - 1;
    } else {
        available_space = read_pos - write_pos - 1;
    }

    if (len > available_space) {
        len = available_space;
    }

    // Write data (handle wrap-around)
    size_t first_chunk = rb->size - write_pos;
    if (len <= first_chunk) {
        memcpy(rb->data + write_pos, data, len);
        write_pos = (write_pos + len) % rb->size;
    } else {
        memcpy(rb->data + write_pos, data, first_chunk);
        memcpy(rb->data, data + first_chunk, len - first_chunk);
        write_pos = len - first_chunk;
    }

    atomic_store(&rb->write_pos, write_pos);
    pthread_mutex_unlock(&rb->lock);

    return len;
}

static size_t ring_buffer_read(RingBuffer* rb, uint8_t* data, size_t len) {
    pthread_mutex_lock(&rb->lock);

    size_t write_pos = atomic_load(&rb->write_pos);
    size_t read_pos = atomic_load(&rb->read_pos);

    // Calculate available data
    size_t available_data;
    if (write_pos >= read_pos) {
        available_data = write_pos - read_pos;
    } else {
        available_data = rb->size - read_pos + write_pos;
    }

    if (len > available_data) {
        len = available_data;
    }

    // Read data (handle wrap-around)
    size_t first_chunk = rb->size - read_pos;
    if (len <= first_chunk) {
        memcpy(data, rb->data + read_pos, len);
        read_pos = (read_pos + len) % rb->size;
    } else {
        memcpy(data, rb->data + read_pos, first_chunk);
        memcpy(data + first_chunk, rb->data, len - first_chunk);
        read_pos = len - first_chunk;
    }

    atomic_store(&rb->read_pos, read_pos);
    pthread_mutex_unlock(&rb->lock);

    return len;
}

// ============================================================================
// Screen Recording Permission Helper
// ============================================================================

static PyObject* request_screen_recording_permission(PyObject* self, PyObject* args) {
    (void)self;
    (void)args;
    @autoreleasepool {
        CFDictionaryRef empty_dict = CFDictionaryCreate(
            kCFAllocatorDefault,
            NULL,
            NULL,
            0,
            &kCFTypeDictionaryKeyCallBacks,
            &kCFTypeDictionaryValueCallBacks
        );

        CGDisplayStreamRef stream = CGDisplayStreamCreate(
            kCGDirectMainDisplay,
            1,
            1,
            kCVPixelFormatType_32BGRA,
            empty_dict,
            ^(CGDisplayStreamFrameStatus status,
              uint64_t time,
              IOSurfaceRef frame,
              CGDisplayStreamUpdateRef update) {
                (void)status;
                (void)time;
                (void)frame;
                (void)update;
            }
        );

        if (empty_dict) {
            CFRelease(empty_dict);
        }

        if (stream == NULL) {
            NSLog(@"[TCC] CGDisplayStreamCreate failed; Screen Recording permission likely denied.");
            Py_RETURN_FALSE;
        }

        CFRelease(stream);
        Py_RETURN_TRUE;
    }
}

// ============================================================================
// Stream Format / Aggregate Device Helpers
// ============================================================================

static void ensure_default_stream_format(ProcessTapState* state) {
    if (!state) {
        return;
    }

    AudioStreamBasicDescription* fmt = &state->format;
    UInt32 fallback_channels = state->channels > 0 ? state->channels : 2;
    UInt32 fallback_bits = state->bits_per_sample > 0 ? state->bits_per_sample : 16;
    Float64 fallback_rate = (state->sample_rate > 0) ? (Float64)state->sample_rate : 48000.0;
    UInt32 bytes_per_sample = fallback_bits / 8;
    if (bytes_per_sample == 0) {
        bytes_per_sample = 2;
    }

    if (fmt->mSampleRate == 0.0) {
        fmt->mSampleRate = fallback_rate;
    }
    if (fmt->mFormatID == 0) {
        fmt->mFormatID = kAudioFormatLinearPCM;
    }
    if (fmt->mFormatFlags == 0) {
        fmt->mFormatFlags = kAudioFormatFlagIsPacked | kAudioFormatFlagIsSignedInteger;
    }
    if (fmt->mChannelsPerFrame == 0) {
        fmt->mChannelsPerFrame = fallback_channels;
    }
    if (fmt->mBitsPerChannel == 0) {
        fmt->mBitsPerChannel = fallback_bits;
    }
    if (fmt->mFramesPerPacket == 0) {
        fmt->mFramesPerPacket = 1;
    }
    if (fmt->mBytesPerFrame == 0) {
        fmt->mBytesPerFrame = fmt->mChannelsPerFrame * bytes_per_sample;
    }
    if (fmt->mBytesPerPacket == 0) {
        fmt->mBytesPerPacket = fmt->mBytesPerFrame * fmt->mFramesPerPacket;
    }
}

static void log_stream_format(const char* prefix, const AudioStreamBasicDescription* fmt) {
    if (!fmt) {
        return;
    }

    NSString* prefix_str = prefix ? [NSString stringWithUTF8String:prefix] : @"[DEBUG] Format";
    NSLog(@"%@ %.0f Hz, %u ch, formatID=0x%08X, flags=0x%08X, bits=%u, bytes/frame=%u",
          prefix_str,
          fmt->mSampleRate,
          (unsigned int)fmt->mChannelsPerFrame,
          (unsigned int)fmt->mFormatID,
          (unsigned int)fmt->mFormatFlags,
          (unsigned int)fmt->mBitsPerChannel,
          (unsigned int)fmt->mBytesPerFrame);
}

static OSStatus configure_aggregate_device(ProcessTapState* state) {
    if (!state || state->device_id == 0) {
        return kAudioHardwareUnspecifiedError;
    }

    ensure_default_stream_format(state);
    log_stream_format("[DEBUG] configure_aggregate_device: Desired stream format",
                      &state->format);

    AudioObjectPropertyAddress fmt_addr = {
        .mSelector = kAudioDevicePropertyStreamFormat,
        .mScope = kAudioDevicePropertyScopeInput,
        .mElement = kAudioObjectPropertyElementMain
    };

    UInt32 fmt_size = sizeof(state->format);
    OSStatus status = AudioObjectSetPropertyData(
        state->device_id,
        &fmt_addr,
        0,
        NULL,
        fmt_size,
        &state->format
    );

    if (status != noErr) {
        NSLog(@"[ERROR] Failed to set aggregate device stream format (status=%d)", status);
        return status;
    }

    AudioStreamBasicDescription confirmed_format = {0};
    UInt32 confirmed_size = sizeof(confirmed_format);
    status = AudioObjectGetPropertyData(
        state->device_id,
        &fmt_addr,
        0,
        NULL,
        &confirmed_size,
        &confirmed_format
    );

    if (status == noErr) {
        log_stream_format("[DEBUG] configure_aggregate_device: Confirmed stream format",
                          &confirmed_format);
    } else {
        NSLog(@"[WARN] Could not read back stream format (status=%d)", status);
    }

    UInt32 channels = state->format.mChannelsPerFrame > 0
        ? state->format.mChannelsPerFrame
        : state->channels;
    if (channels == 0) {
        channels = 2;
    }

    AudioObjectPropertyAddress stream_config_addr = {
        .mSelector = kAudioDevicePropertyStreamConfiguration,
        .mScope = kAudioDevicePropertyScopeInput,
        .mElement = kAudioObjectPropertyElementMain
    };

    UInt32 buffer_list_size = (UInt32)(offsetof(AudioBufferList, mBuffers) + sizeof(AudioBuffer));
    AudioBufferList* buffer_list = (AudioBufferList*)malloc(buffer_list_size);
    if (!buffer_list) {
        return kAudioHardwareUnspecifiedError;
    }

    memset(buffer_list, 0, buffer_list_size);
    buffer_list->mNumberBuffers = 1;
    buffer_list->mBuffers[0].mNumberChannels = channels;
    buffer_list->mBuffers[0].mDataByteSize = 0;
    buffer_list->mBuffers[0].mData = NULL;

    status = AudioObjectSetPropertyData(
        state->device_id,
        &stream_config_addr,
        0,
        NULL,
        buffer_list_size,
        buffer_list
    );

    free(buffer_list);

    if (status != noErr) {
        NSLog(@"[ERROR] Failed to set stream configuration (status=%d)", status);
        return status;
    }

    // Read back stream config for diagnostics
    UInt32 readback_size = 0;
    status = AudioObjectGetPropertyDataSize(
        state->device_id,
        &stream_config_addr,
        0,
        NULL,
        &readback_size
    );

    if (status == noErr && readback_size >= sizeof(AudioBufferList)) {
        AudioBufferList* readback = (AudioBufferList*)malloc(readback_size);
        if (readback) {
            memset(readback, 0, readback_size);
            status = AudioObjectGetPropertyData(
                state->device_id,
                &stream_config_addr,
                0,
                NULL,
                &readback_size,
                readback
            );

            if (status == noErr) {
                UInt32 configured_channels = 0;
                if (readback->mNumberBuffers > 0) {
                    configured_channels = readback->mBuffers[0].mNumberChannels;
                }
                NSLog(@"[DEBUG] configure_aggregate_device: Stream configuration set (buffers=%u, channels=%u)",
                      (unsigned int)readback->mNumberBuffers,
                      (unsigned int)configured_channels);
            } else {
                NSLog(@"[WARN] Failed to read back stream configuration (status=%d)", status);
            }

            free(readback);
        }
    } else {
        NSLog(@"[WARN] Could not query stream configuration size (status=%d)", status);
    }

    return noErr;
}

// ============================================================================
// Core Audio Helpers
// ============================================================================

static OSStatus translate_pid_to_process_object(pid_t pid, AudioObjectID* out_object_id) {
    AudioObjectPropertyAddress address = {
        .mSelector = kAudioHardwarePropertyTranslatePIDToProcessObject,
        .mScope = kAudioObjectPropertyScopeGlobal,
        .mElement = kAudioObjectPropertyElementMain
    };

    UInt32 translation_value = (UInt32)pid;
    AudioObjectID process_object_id = 0;
    UInt32 data_size = sizeof(AudioObjectID);

    OSStatus status = AudioObjectGetPropertyData(
        kAudioObjectSystemObject,
        &address,
        sizeof(translation_value),
        &translation_value,
        &data_size,
        &process_object_id
    );

    if (status == noErr && out_object_id) {
        *out_object_id = process_object_id;
    }

    return status;
}

static CFStringRef get_default_output_device_uid() {
    AudioObjectPropertyAddress address = {
        .mSelector = kAudioHardwarePropertyDefaultOutputDevice,
        .mScope = kAudioObjectPropertyScopeGlobal,
        .mElement = kAudioObjectPropertyElementMain
    };

    AudioObjectID device_id = 0;
    UInt32 data_size = sizeof(AudioObjectID);

    OSStatus status = AudioObjectGetPropertyData(
        kAudioObjectSystemObject,
        &address,
        0,
        NULL,
        &data_size,
        &device_id
    );

    if (status != noErr || device_id == 0) {
        return NULL;
    }

    // Get device UID
    address.mSelector = kAudioDevicePropertyDeviceUID;
    CFStringRef uid = NULL;
    data_size = sizeof(CFStringRef);

    status = AudioObjectGetPropertyData(
        device_id,
        &address,
        0,
        NULL,
        &data_size,
        &uid
    );

    return (status == noErr) ? uid : NULL;
}

// ============================================================================
// IOProc Callback
// ============================================================================

static OSStatus io_proc_callback(
    AudioObjectID inDevice,
    const AudioTimeStamp* inNow,
    const AudioBufferList* inInputData,
    const AudioTimeStamp* inInputTime,
    AudioBufferList* outOutputData,
    const AudioTimeStamp* inOutputTime,
    void* inClientData
) {
    ProcessTapState* state = (ProcessTapState*)inClientData;

    static uint64_t call_count = 0;
    if ((call_count++ % 100) == 0) {
        UInt32 inBuffers = inInputData ? inInputData->mNumberBuffers : 0;
        UInt32 outBuffers = outOutputData ? outOutputData->mNumberBuffers : 0;
        UInt32 inBytes = 0;
        if (inInputData && inBuffers > 0) {
            inBytes = inInputData->mBuffers[0].mDataByteSize;
        }
        NSLog(@"[IOPROC] called #%llu: inBuffers=%u inBytes=%u outBuffers=%u",
              call_count, (unsigned int)inBuffers, (unsigned int)inBytes, (unsigned int)outBuffers);
    }

    if (!state || !atomic_load(&state->is_running)) {
        return noErr;
    }

    if (inInputData && inInputData->mNumberBuffers > 0) {
        const AudioBuffer* buffer = &inInputData->mBuffers[0];
        if (buffer->mData && buffer->mDataByteSize > 0) {
            ring_buffer_write(
                state->ring_buffer,
                (const uint8_t*)buffer->mData,
                buffer->mDataByteSize
            );
        }
    }

    return noErr;
}

// ============================================================================
// Process Tap Creation (Optimized)
// ============================================================================

static OSStatus create_process_tap(ProcessTapState* state) {
    NSLog(@"[DEBUG] create_process_tap: Starting...");
    @autoreleasepool {
        // Convert PIDs to AudioObjectIDs
        AudioObjectID* include_objects = NULL;
        AudioObjectID* exclude_objects = NULL;
        NSLog(@"[DEBUG] create_process_tap: Converting PIDs to AudioObjectIDs...");

        if (state->include_count > 0) {
            include_objects = (AudioObjectID*)malloc(sizeof(AudioObjectID) * state->include_count);
            for (size_t i = 0; i < state->include_count; i++) {
                OSStatus status = translate_pid_to_process_object(state->include_pids[i], &include_objects[i]);
                if (status != noErr) {
                    snprintf(state->error_message, sizeof(state->error_message),
                            "Failed to translate PID %d to AudioObjectID", state->include_pids[i]);
                    free(include_objects);
                    return status;
                }
            }
        }

        if (state->exclude_count > 0) {
            exclude_objects = (AudioObjectID*)malloc(sizeof(AudioObjectID) * state->exclude_count);
            for (size_t i = 0; i < state->exclude_count; i++) {
                OSStatus status = translate_pid_to_process_object(state->exclude_pids[i], &exclude_objects[i]);
                if (status != noErr) {
                    snprintf(state->error_message, sizeof(state->error_message),
                            "Failed to translate PID %d to AudioObjectID", state->exclude_pids[i]);
                    free(include_objects);
                    free(exclude_objects);
                    return status;
                }
            }
        }

        // Create CATapDescription
        NSLog(@"[DEBUG] create_process_tap: Creating CATapDescription...");
        CATapDescription* tap_desc = nil;

        if (state->include_count > 0) {
            // Include specific processes (stereo mixdown)
            // Note: initStereoMixdownOfProcesses expects NSNumber array
            NSMutableArray<NSNumber*>* include_array = [NSMutableArray arrayWithCapacity:state->include_count];
            for (size_t i = 0; i < state->include_count; i++) {
                [include_array addObject:@(include_objects[i])];
            }
            tap_desc = [[CATapDescription alloc] initStereoMixdownOfProcesses:include_array];
        } else if (state->exclude_count > 0) {
            // Exclude specific processes (global tap)
            // Note: initStereoGlobalTapButExcludeProcesses expects NSNumber array
            NSMutableArray<NSNumber*>* exclude_array = [NSMutableArray arrayWithCapacity:state->exclude_count];
            for (size_t i = 0; i < state->exclude_count; i++) {
                [exclude_array addObject:@(exclude_objects[i])];
            }
            tap_desc = [[CATapDescription alloc] initStereoGlobalTapButExcludeProcesses:exclude_array];
        } else {
            // Global tap (all processes) - use init and set properties manually
            // initStereoGlobalTap is a Swift-only convenience method
            tap_desc = [[CATapDescription alloc] init];
            [tap_desc setMono:NO];  // Stereo
            [tap_desc setMixdown:NO];  // Global (not mixdown)
            [tap_desc setExclusive:NO];
            [tap_desc setPrivate:YES];
        }

        // Note: UUID setting is skipped due to property copy semantics issues with CFUUIDRef
        // The system will auto-generate a UUID if not specified
        free(include_objects);
        free(exclude_objects);

        NSLog(@"[DEBUG] create_process_tap: CATapDescription created successfully");
        NSLog(@"[DEBUG] create_process_tap: Calling AudioHardwareCreateProcessTap...");

        // Create process tap
        AudioObjectID tap_id = 0;
        OSStatus status = AudioHardwareCreateProcessTap(tap_desc, &tap_id);

        NSLog(@"[DEBUG] create_process_tap: AudioHardwareCreateProcessTap returned: %d", status);

        if (status != noErr) {
            snprintf(state->error_message, sizeof(state->error_message),
                    "AudioHardwareCreateProcessTap failed: %d. Screen Recording permission "
                    "is required. Enable it via  > System Settings > Privacy & Security > "
                    "Screen Recording, then restart the app. 過去に拒否した場合は手動で許可し、アプリを再起動してください。",
                    status);
            return status;
        }

        state->tap_id = tap_id;
        NSLog(@"[DEBUG] create_process_tap: Process tap created with ID: %u", tap_id);

        // CRITICAL: Read tap stream format (must be done before creating aggregate device)
        // This matches AudioCap line 133: tapID.readAudioTapStreamBasicDescription()
        NSLog(@"[DEBUG] create_process_tap: Reading tap stream format...");
        AudioStreamBasicDescription tap_format;
        UInt32 tap_format_size = sizeof(tap_format);
        AudioObjectPropertyAddress tap_format_address = {
            .mSelector = kAudioTapPropertyFormat,
            .mScope = kAudioObjectPropertyScopeGlobal,
            .mElement = kAudioObjectPropertyElementMain
        };

        status = AudioObjectGetPropertyData(tap_id, &tap_format_address, 0, NULL, &tap_format_size, &tap_format);
        if (status != noErr) {
            NSLog(@"[DEBUG] create_process_tap: Failed to read tap format: %d", status);
            // Continue anyway - this might not be fatal
        } else {
            NSLog(@"[DEBUG] create_process_tap: Tap format: %.0f Hz, %u channels, %u bits/sample",
                  tap_format.mSampleRate, tap_format.mChannelsPerFrame, tap_format.mBitsPerChannel);
            // Store format in state for later use
            state->format = tap_format;
            ensure_default_stream_format(state);
        }

        // === AGGREGATE DEVICE CREATION (FIXED - String Literal Keys) ===
        NSLog(@"[DEBUG] Step 1: Generating UUIDs");

        CFUUIDRef agg_uuid = CFUUIDCreate(NULL);
        CFStringRef agg_uuid_str = CFUUIDCreateString(NULL, agg_uuid);
        CFRelease(agg_uuid);

        NSLog(@"[DEBUG] Step 2: Getting default output device UID");
        CFStringRef device_uid = get_default_output_device_uid();
        if (!device_uid) {
            snprintf(state->error_message, sizeof(state->error_message),
                    "Failed to get default output device");
            CFRelease(agg_uuid_str);
            return kAudioHardwareUnspecifiedError;
        }
        NSLog(@"[DEBUG] Device UID: %@", device_uid);

        // Create string literal keys (DO NOT use kAudio* constants!)
        NSLog(@"[DEBUG] Step 3: Creating CFString keys from literals");
        CFStringRef key_name = CFSTR("name");
        CFStringRef key_uid = CFSTR("uid");
        CFStringRef key_subdevices = CFSTR("subdevices");
        CFStringRef key_master = CFSTR("master");
        CFStringRef key_private = CFSTR("private");
        CFStringRef key_stacked = CFSTR("stacked");
        CFStringRef key_taplist = CFSTR("taplist");
        CFStringRef key_tapautostart = CFSTR("tapautostart");

        // Create subdevice list with tap ID
        NSLog(@"[DEBUG] Step 4: Creating subdevice list (tap_id=%u)", state->tap_id);
        tap_id = state->tap_id;  // Use existing tap_id variable from line 410
        CFNumberRef tap_id_num = CFNumberCreate(NULL, kCFNumberSInt32Type, &tap_id);
        const void* sub_vals[] = { tap_id_num };
        CFArrayRef subdevice_list = CFArrayCreate(NULL, sub_vals, 1, &kCFTypeArrayCallBacks);

        CFArrayRef tap_list = CFArrayCreate(NULL, (const void**)&tap_id_num, 1, &kCFTypeArrayCallBacks);

        // Create aggregate device dictionary
        NSLog(@"[DEBUG] Step 5: Creating aggregate device dictionary");
        const void* agg_keys[] = {
            key_name,
            key_uid,
            key_subdevices,
            key_master,
            key_private,
            key_stacked,
            key_taplist,
            key_tapautostart
        };

        CFStringRef agg_name = CFSTR("ProcTap Aggregate");
        const void* agg_vals[] = {
            agg_name,           // name
            agg_uuid_str,       // uid
            subdevice_list,     // subdevices
            tap_id_num,         // master
            kCFBooleanTrue,     // private
            kCFBooleanFalse,    // stacked
            tap_list,           // tap list
            kCFBooleanTrue      // tap auto start
        };

        NSLog(@"[DEBUG] Step 5a: Calling CFDictionaryCreate");
        CFDictionaryRef device_dict = CFDictionaryCreate(
            NULL,
            agg_keys,
            agg_vals,
            8,
            &kCFTypeDictionaryKeyCallBacks,
            &kCFTypeDictionaryValueCallBacks
        );

        if (!device_dict) {
            NSLog(@"[ERROR] CFDictionaryCreate returned NULL!");
            CFRelease(tap_id_num);
            CFRelease(subdevice_list);
            CFRelease(tap_list);
            CFRelease(agg_uuid_str);
            CFRelease(device_uid);
            snprintf(state->error_message, sizeof(state->error_message),
                    "Failed to create aggregate device dictionary");
            return kAudioHardwareUnspecifiedError;
        }
        NSLog(@"[DEBUG] Step 5b: Dictionary created: %p", device_dict);

        // Call AudioHardwareCreateAggregateDevice
        NSLog(@"[DEBUG] Step 6: Calling AudioHardwareCreateAggregateDevice");
        status = AudioHardwareCreateAggregateDevice(device_dict, &state->device_id);
        NSLog(@"[DEBUG] Step 6: Returned status=%d, device_id=%u", status, state->device_id);

        // Cleanup
        NSLog(@"[DEBUG] Step 7: Cleanup");
        CFRelease(device_dict);
        CFRelease(subdevice_list);
        CFRelease(tap_list);
        CFRelease(tap_id_num);
        CFRelease(agg_uuid_str);
        CFRelease(device_uid);

        if (status != noErr) {
            snprintf(state->error_message, sizeof(state->error_message),
                    "AudioHardwareCreateAggregateDevice failed: %d", status);
            return status;
        }

        NSLog(@"[DEBUG] Step 8: Configuring aggregate device stream format...");
        status = configure_aggregate_device(state);
        if (status != noErr) {
            snprintf(state->error_message, sizeof(state->error_message),
                    "Failed to configure aggregate device: %d", status);
            AudioObjectPropertyAddress destroy_addr = {
                .mSelector = kAudioPlugInDestroyAggregateDevice,
                .mScope = kAudioObjectPropertyScopeGlobal,
                .mElement = kAudioObjectPropertyElementMain
            };
            AudioObjectSetPropertyData(
                kAudioObjectSystemObject,
                &destroy_addr,
                0,
                NULL,
                sizeof(AudioObjectID),
                &state->device_id
            );
            state->device_id = 0;
            return status;
        }

        NSLog(@"[DEBUG] Step 9: SUCCESS!");
        atomic_store(&state->is_initialized, true);
        // === END AGGREGATE DEVICE CREATION ===
        return noErr;
    }
}

// ============================================================================
// Python Extension Methods
// ============================================================================

static PyObject* create_tap(PyObject* self, PyObject* args, PyObject* kwargs) {
    static char* kwlist[] = {
        "include_pids", "exclude_pids", "sample_rate", "channels", "bits_per_sample", NULL
    };

    PyObject* include_pids_list = NULL;
    PyObject* exclude_pids_list = NULL;
    unsigned int sample_rate = 48000;
    unsigned int channels = 2;
    unsigned int bits_per_sample = 16;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|OOIII", kwlist,
                                     &include_pids_list, &exclude_pids_list,
                                     &sample_rate, &channels, &bits_per_sample)) {
        return NULL;
    }

    // Allocate state
    ProcessTapState* state = (ProcessTapState*)calloc(1, sizeof(ProcessTapState));
    if (!state) {
        PyErr_NoMemory();
        return NULL;
    }

    state->sample_rate = sample_rate;
    state->channels = channels;
    state->bits_per_sample = bits_per_sample;
    state->io_proc_id = NULL;  // Initialize to NULL
    atomic_init(&state->is_running, false);
    atomic_init(&state->is_initialized, false);
    ensure_default_stream_format(state);

    // Parse include PIDs
    if (include_pids_list && PyList_Check(include_pids_list)) {
        Py_ssize_t count = PyList_Size(include_pids_list);
        state->include_count = (size_t)count;
        state->include_pids = (pid_t*)malloc(sizeof(pid_t) * count);

        for (Py_ssize_t i = 0; i < count; i++) {
            PyObject* item = PyList_GetItem(include_pids_list, i);
            state->include_pids[i] = (pid_t)PyLong_AsLong(item);
        }
    }

    // Parse exclude PIDs
    if (exclude_pids_list && PyList_Check(exclude_pids_list)) {
        Py_ssize_t count = PyList_Size(exclude_pids_list);
        state->exclude_count = (size_t)count;
        state->exclude_pids = (pid_t*)malloc(sizeof(pid_t) * count);

        for (Py_ssize_t i = 0; i < count; i++) {
            PyObject* item = PyList_GetItem(exclude_pids_list, i);
            state->exclude_pids[i] = (pid_t)PyLong_AsLong(item);
        }
    }

    // Create ring buffer
    state->ring_buffer = ring_buffer_create(RING_BUFFER_SIZE);
    if (!state->ring_buffer) {
        free(state->include_pids);
        free(state->exclude_pids);
        free(state);
        PyErr_NoMemory();
        return NULL;
    }

    // Create process tap
    OSStatus status = create_process_tap(state);
    if (status != noErr) {
        PyErr_Format(PyExc_RuntimeError, "Failed to create process tap: %s (OSStatus %d)",
                     state->error_message, status);
        ring_buffer_destroy(state->ring_buffer);
        free(state->include_pids);
        free(state->exclude_pids);
        free(state);
        return NULL;
    }

    // Return state as PyCapsule
    return PyCapsule_New(state, "proctap.ProcessTapState", NULL);
}

static PyObject* start_tap(PyObject* self, PyObject* args) {
    PyObject* capsule = NULL;

    if (!PyArg_ParseTuple(args, "O", &capsule)) {
        return NULL;
    }

    ProcessTapState* state = (ProcessTapState*)PyCapsule_GetPointer(capsule, "proctap.ProcessTapState");
    if (!state) {
        PyErr_SetString(PyExc_ValueError, "Invalid tap handle");
        return NULL;
    }

    // If already running, return immediately
    if (atomic_load(&state->is_running)) {
        Py_RETURN_NONE;
    }

    if (state->tap_id == 0) {
        PyErr_SetString(PyExc_RuntimeError, "Process tap not initialized");
        return NULL;
    }

    // Create IOProcID only if not already created
    if (state->io_proc_id == NULL) {
        NSLog(@"[DEBUG] start_tap: Creating IOProcID for tap %u", state->tap_id);
        OSStatus status = AudioDeviceCreateIOProcID(
            state->tap_id,
            io_proc_callback,
            state,
            &state->io_proc_id
        );

        if (status != noErr) {
            PyErr_Format(PyExc_RuntimeError, "Failed to create IOProcID: %d", status);
            return NULL;
        }
    }

    log_stream_format("[DEBUG] start_tap: Tap format", &state->format);
    NSLog(@"[DEBUG] About to start tap %u with IOProcID=%p", state->tap_id, state->io_proc_id);

    // Start device with IOProcID (NOT function pointer!)
    OSStatus status = AudioDeviceStart(state->tap_id, state->io_proc_id);
    NSLog(@"[DEBUG] AudioDeviceStart returned status=%d (0x%08X)", status, (unsigned int)status);
    if (status != noErr) {
        // Cleanup on failure
        AudioDeviceDestroyIOProcID(state->tap_id, state->io_proc_id);
        state->io_proc_id = NULL;
        PyErr_Format(PyExc_RuntimeError, "Failed to start device: %d (0x%08X)", status, (unsigned int)status);
        return NULL;
    }

    atomic_store(&state->is_running, true);

    Py_RETURN_NONE;
}

static PyObject* stop_tap(PyObject* self, PyObject* args) {
    PyObject* capsule = NULL;

    if (!PyArg_ParseTuple(args, "O", &capsule)) {
        return NULL;
    }

    ProcessTapState* state = (ProcessTapState*)PyCapsule_GetPointer(capsule, "proctap.ProcessTapState");
    if (!state) {
        PyErr_SetString(PyExc_ValueError, "Invalid tap handle");
        return NULL;
    }

    // If not running, return immediately
    if (!atomic_load(&state->is_running)) {
        Py_RETURN_NONE;
    }

    // Mark as stopped
    atomic_store(&state->is_running, false);

    // Stop and destroy IOProc if it exists
    if (state->io_proc_id != NULL) {
        OSStatus stop_status = AudioDeviceStop(state->tap_id, state->io_proc_id);
        NSLog(@"[DEBUG] stop_tap: AudioDeviceStop returned %d", stop_status);
        OSStatus destroy_status = AudioDeviceDestroyIOProcID(state->tap_id, state->io_proc_id);
        NSLog(@"[DEBUG] stop_tap: AudioDeviceDestroyIOProcID returned %d", destroy_status);
        state->io_proc_id = NULL;
    }

    Py_RETURN_NONE;
}

static PyObject* read_tap(PyObject* self, PyObject* args) {
    PyObject* capsule = NULL;
    unsigned int max_bytes = 8192;

    if (!PyArg_ParseTuple(args, "O|I", &capsule, &max_bytes)) {
        return NULL;
    }

    ProcessTapState* state = (ProcessTapState*)PyCapsule_GetPointer(capsule, "proctap.ProcessTapState");
    if (!state) {
        PyErr_SetString(PyExc_ValueError, "Invalid tap handle");
        return NULL;
    }

    size_t available = ring_buffer_available(state->ring_buffer);
    if (available == 0) {
        return PyBytes_FromStringAndSize("", 0);
    }

    size_t to_read = (available < max_bytes) ? available : max_bytes;

    PyObject* result = PyBytes_FromStringAndSize(NULL, to_read);
    if (!result) {
        return NULL;
    }

    uint8_t* buffer = (uint8_t*)PyBytes_AsString(result);
    size_t bytes_read = ring_buffer_read(state->ring_buffer, buffer, to_read);

    if (bytes_read < to_read) {
        _PyBytes_Resize(&result, bytes_read);
    }

    return result;
}

static PyObject* get_format(PyObject* self, PyObject* args) {
    PyObject* capsule = NULL;

    if (!PyArg_ParseTuple(args, "O", &capsule)) {
        return NULL;
    }

    ProcessTapState* state = (ProcessTapState*)PyCapsule_GetPointer(capsule, "proctap.ProcessTapState");
    if (!state) {
        PyErr_SetString(PyExc_ValueError, "Invalid tap handle");
        return NULL;
    }

    return Py_BuildValue("{s:I,s:I,s:I}",
                         "sample_rate", state->sample_rate,
                         "channels", state->channels,
                         "bits_per_sample", state->bits_per_sample);
}

static PyObject* destroy_tap(PyObject* self, PyObject* args) {
    PyObject* capsule = NULL;

    if (!PyArg_ParseTuple(args, "O", &capsule)) {
        return NULL;
    }

    ProcessTapState* state = (ProcessTapState*)PyCapsule_GetPointer(capsule, "proctap.ProcessTapState");
    if (!state) {
        PyErr_SetString(PyExc_ValueError, "Invalid tap handle");
        return NULL;
    }

    // Stop if running
    if (atomic_load(&state->is_running)) {
        atomic_store(&state->is_running, false);

        // Stop and destroy IOProc if it exists
        if (state->io_proc_id != NULL) {
            OSStatus stop_status = AudioDeviceStop(state->tap_id, state->io_proc_id);
            NSLog(@"[DEBUG] destroy_tap: AudioDeviceStop returned %d", stop_status);
            OSStatus destroy_status = AudioDeviceDestroyIOProcID(state->tap_id, state->io_proc_id);
            NSLog(@"[DEBUG] destroy_tap: AudioDeviceDestroyIOProcID returned %d", destroy_status);
            state->io_proc_id = NULL;
        }
    }

    // Destroy process tap
    if (state->tap_id != 0) {
        AudioObjectID tap_id = state->tap_id;
        OSStatus tap_status = AudioHardwareDestroyProcessTap(tap_id);
        NSLog(@"[DEBUG] destroy_tap: AudioHardwareDestroyProcessTap(%u) -> %d",
              tap_id, tap_status);
        state->tap_id = 0;
    }

    // Destroy aggregate device
    if (state->device_id != 0) {
        AudioObjectPropertyAddress address = {
            .mSelector = kAudioPlugInDestroyAggregateDevice,
            .mScope = kAudioObjectPropertyScopeGlobal,
            .mElement = kAudioObjectPropertyElementMain
        };

        AudioObjectID device_id = state->device_id;
        OSStatus destroy_status = AudioObjectSetPropertyData(
            kAudioObjectSystemObject,
            &address,
            0,
            NULL,
            sizeof(AudioObjectID),
            &state->device_id
        );
        NSLog(@"[DEBUG] destroy_tap: Destroy aggregate device %u status=%d",
              device_id, destroy_status);
        state->device_id = 0;
    }

    // Clean up resources
    ring_buffer_destroy(state->ring_buffer);
    free(state->include_pids);
    free(state->exclude_pids);
    free(state);

    Py_RETURN_NONE;
}

// ============================================================================
// Module Definition
// ============================================================================

static PyMethodDef module_methods[] = {
    {"request_permission_prompt", request_screen_recording_permission, METH_NOARGS,
     "Trigger macOS Screen Recording permission dialog."},
    {"create_tap", (PyCFunction)create_tap, METH_VARARGS | METH_KEYWORDS,
     "Create a process audio tap"},
    {"start_tap", start_tap, METH_VARARGS,
     "Start audio capture"},
    {"stop_tap", stop_tap, METH_VARARGS,
     "Stop audio capture"},
    {"read_tap", read_tap, METH_VARARGS,
     "Read captured audio data"},
    {"get_format", get_format, METH_VARARGS,
     "Get audio format information"},
    {"destroy_tap", destroy_tap, METH_VARARGS,
     "Destroy the tap and free resources"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module_def = {
    PyModuleDef_HEAD_INIT,
    "_native_macos",
    "macOS Core Audio Process Tap native extension",
    -1,
    module_methods
};

PyMODINIT_FUNC PyInit__native_macos(void) {
    return PyModule_Create(&module_def);
}
