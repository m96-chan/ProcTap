#!/usr/bin/env python3
"""
Debug script to query aggregate device stream configuration.
"""

import proctap._native_macos as native
import subprocess
import time
import ctypes
import ctypes.util

# Load Core Audio
ca_lib = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))

# Constants
kAudioObjectPropertyScopeGlobal = 0x676c6f62  # 'glob'
kAudioObjectPropertyScopeInput = 0x696e7074   # 'inpt'
kAudioObjectPropertyScopeOutput = 0x6f757470  # 'outp'
kAudioObjectPropertyElementMain = 0

kAudioDevicePropertyStreams = 0x73746d23  # 'stm#'
kAudioDevicePropertyStreamConfiguration = 0x73636667  # 'scfg'

class AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32)
    ]

# Start say process
say_proc = subprocess.Popen(['say', 'Testing stream configuration'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(0.3)

try:
    # Create tap
    handle = native.create_tap(
        include_pids=[say_proc.pid],
        exclude_pids=[],
        sample_rate=16000,
        channels=1,
        bits_per_sample=16
    )
    print(f"✅ Tap created, handle: {handle}")

    # Extract device ID from handle (it's a PyCapsule, so we need to use native API)
    # For now, let's use AudioObjectGetPropertyData to query system for aggregate devices

    print("\n" + "="*60)
    print("FINDING AGGREGATE DEVICE...")
    print("="*60)

    # Query kAudioHardwarePropertyDevices
    kAudioHardwarePropertyDevices = 0x64657623  # 'dev#'
    kAudioObjectSystemObject = 1

    addr = AudioObjectPropertyAddress(
        kAudioHardwarePropertyDevices,
        kAudioObjectPropertyScopeGlobal,
        kAudioObjectPropertyElementMain
    )

    # Get size
    size = ctypes.c_uint32(0)
    ca_lib.AudioObjectGetPropertyDataSize(
        kAudioObjectSystemObject,
        ctypes.byref(addr),
        0,
        None,
        ctypes.byref(size)
    )

    # Get device list
    num_devices = size.value // 4
    devices = (ctypes.c_uint32 * num_devices)()
    ca_lib.AudioObjectGetPropertyData(
        kAudioObjectSystemObject,
        ctypes.byref(addr),
        0,
        None,
        ctypes.byref(size),
        devices
    )

    print(f"Found {num_devices} total audio devices")

    # Find our aggregate device (look for "ProcTap Aggregate" name)
    kAudioObjectPropertyName = 0x6c6e616d  # 'lnam'

    agg_device_id = None
    for device_id in devices:
        addr.mSelector = kAudioObjectPropertyName
        name_size = ctypes.c_uint32(256)
        name_buf = ctypes.create_string_buffer(256)

        status = ca_lib.AudioObjectGetPropertyData(
            device_id,
            ctypes.byref(addr),
            0,
            None,
            ctypes.byref(name_size),
            name_buf
        )

        if status == 0:
            # CFStringRef to string (simplified - just check if it contains ProcTap)
            # In reality we'd need to use CF APIs properly
            print(f"  Device {device_id}: checking...")

            # Query streams on input scope
            addr.mSelector = kAudioDevicePropertyStreams
            addr.mScope = kAudioObjectPropertyScopeInput

            stream_size = ctypes.c_uint32(0)
            status = ca_lib.AudioObjectGetPropertyDataSize(
                device_id,
                ctypes.byref(addr),
                0,
                None,
                ctypes.byref(stream_size)
            )

            if status == 0:
                num_input_streams = stream_size.value // 4
                if num_input_streams > 0:
                    print(f"    → Has {num_input_streams} INPUT streams")

                    # This might be our aggregate device
                    if device_id >= 119:  # Recent device IDs
                        agg_device_id = device_id
                        print(f"    ✅ Likely our aggregate device!")
                        break

    if agg_device_id:
        print(f"\n" + "="*60)
        print(f"QUERYING DEVICE {agg_device_id}")
        print("="*60)

        # Query input streams in detail
        addr.mSelector = kAudioDevicePropertyStreams
        addr.mScope = kAudioObjectPropertyScopeInput

        stream_size = ctypes.c_uint32(0)
        ca_lib.AudioObjectGetPropertyDataSize(
            agg_device_id,
            ctypes.byref(addr),
            0,
            None,
            ctypes.byref(stream_size)
        )

        num_streams = stream_size.value // 4
        print(f"\nINPUT Scope: {num_streams} streams")

        if num_streams > 0:
            stream_ids = (ctypes.c_uint32 * num_streams)()
            ca_lib.AudioObjectGetPropertyData(
                agg_device_id,
                ctypes.byref(addr),
                0,
                None,
                ctypes.byref(stream_size),
                stream_ids
            )

            for i, stream_id in enumerate(stream_ids):
                print(f"  Stream {i}: ID = {stream_id}")

        # Query output streams
        addr.mScope = kAudioObjectPropertyScopeOutput

        stream_size = ctypes.c_uint32(0)
        ca_lib.AudioObjectGetPropertyDataSize(
            agg_device_id,
            ctypes.byref(addr),
            0,
            None,
            ctypes.byref(stream_size)
        )

        num_streams = stream_size.value // 4
        print(f"\nOUTPUT Scope: {num_streams} streams")
    else:
        print("\n❌ Could not find aggregate device")

    # Cleanup
    native.destroy_tap(handle)

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

finally:
    say_proc.kill()
    say_proc.wait()
