import Foundation
import CoreAudio
import AudioToolbox
import AVFoundation

// Private Core Audio APIs
@_silgen_name("AudioHardwareCreateProcessTap")
func AudioHardwareCreateProcessTap(_ tapDescription: AnyObject, _ outTapID: UnsafeMutablePointer<AudioObjectID>) -> OSStatus

@_silgen_name("AudioHardwareDestroyProcessTap")
func AudioHardwareDestroyProcessTap(_ tapID: AudioObjectID) -> OSStatus

// Verbose diagnostics go to stderr only when PROCTAP_VERBOSE is set. Errors and
// the "Ready" readiness marker are always printed.
let g_verbose = ProcessInfo.processInfo.environment["PROCTAP_VERBOSE"] != nil
func dlog(_ msg: String) {
    if g_verbose { fputs(msg, stderr) }
}

@available(macOS 14.2, *)
func requestMicrophonePermission() -> Bool {
    dlog("Requesting microphone permission...\n")

    let semaphore = DispatchSemaphore(value: 0)
    var granted = false

    AVCaptureDevice.requestAccess(for: .audio) { result in
        granted = result
        if result {
            dlog("Microphone permission granted\n")
        } else {
            dlog("Microphone permission denied\n")
        }
        semaphore.signal()
    }

    // Wait for permission response (with timeout)
    let timeout = DispatchTime.now() + .seconds(60)
    let result = semaphore.wait(timeout: timeout)

    if result == .timedOut {
        fputs("WARNING: Permission request timed out\n", stderr)
        return false
    }

    return granted
}

@available(macOS 14.2, *)
func checkScreenRecordingPermission() -> Bool {
    // Screen Recording permission gates Process Tap *audio content* (a tap without
    // it is created fine but delivers silence). Use the real preflight API, not
    // CGWindowListCopyWindowInfo (which returns window metadata even WITHOUT the
    // permission and so gives a false positive).
    let has = CGPreflightScreenCaptureAccess()
    dlog("Screen Recording preflight: \(has)\n")
    if has { return true }

    // Not granted: ask the system to register/prompt this binary.
    let granted = CGRequestScreenCaptureAccess()
    dlog("Screen Recording request result: \(granted)\n")
    if !granted {
        fputs("ERROR: Screen Recording permission required. Enable it for this binary in\n", stderr)
        dlog("System Settings > Privacy & Security > Screen Recording, then relaunch.\n")
    }
    return granted
}

@available(macOS 14.2, *)
func checkMicrophonePermission() -> Bool {
    let status = AVCaptureDevice.authorizationStatus(for: .audio)

    switch status {
    case .authorized:
        dlog("Microphone permission: Already authorized\n")
        return true
    case .notDetermined:
        dlog("Microphone permission: Not determined, requesting...\n")
        return requestMicrophonePermission()
    case .denied:
        fputs("ERROR: Microphone permission denied\n", stderr)
        dlog("Please grant microphone access in System Settings > Privacy & Security > Microphone\n")
        return false
    case .restricted:
        fputs("ERROR: Microphone access is restricted\n", stderr)
        return false
    @unknown default:
        fputs("WARNING: Unknown microphone permission status\n", stderr)
        return false
    }
}

@available(macOS 14.2, *)
func checkAllPermissions() -> Bool {
    var allGranted = true

    // Check microphone permission
    if !checkMicrophonePermission() {
        allGranted = false
    }

    // Check screen recording permission (needed for process audio access)
    if !checkScreenRecordingPermission() {
        allGranted = false
    }

    return allGranted
}

@available(macOS 14.2, *)
func findProcessAudioObject(pid: pid_t) -> AudioObjectID? {
    // Use kAudioHardwarePropertyTranslatePIDToProcessObject (public since macOS 14.4).
    // NOTE: the archived code used the wrong FourCC 'pid2' (0x70696432); the correct
    // selector is 'id2p'. Using the named constant avoids that class of bug.
    var propertyAddress = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyTranslatePIDToProcessObject,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )

    var processObjectID: AudioObjectID = 0
    var dataSize = UInt32(MemoryLayout<AudioObjectID>.size)
    var qualifierData = pid
    let qualifierSize = UInt32(MemoryLayout<pid_t>.size)

    let status = AudioObjectGetPropertyData(
        AudioObjectID(kAudioObjectSystemObject),
        &propertyAddress,
        qualifierSize,
        &qualifierData,
        &dataSize,
        &processObjectID
    )

    if status == noErr && processObjectID != 0 {
        dlog("Found process object ID \(processObjectID) for PID \(pid)\n")
        return processObjectID
    } else {
        fputs("ERROR: Failed to translate PID \(pid) to process object (status=\(status), objectID=\(processObjectID))\n", stderr)
        return nil
    }
}

@available(macOS 14.2, *)
@main
struct ProcTapHelper {
    static func main() {
        let args = CommandLine.arguments

        guard args.count >= 2 else {
            fputs("Usage: proctap-helper <PID>\n", stderr)
            exit(1)
        }

        guard let pid = pid_t(args[1]) else {
            fputs("Error: Invalid PID\n", stderr)
            exit(1)
        }

        // Optional 2nd arg: output file path. Lets the helper be launched via
        // LaunchServices (`open`) — which can't pipe stdout — so it runs as its
        // own TCC responsible process. PCM is written here instead of stdout.
        if args.count >= 3 {
            let outPath = args[2]
            // When launched via `open`, stderr is detached; mirror it to a log file.
            _ = freopen(outPath + ".log", "w", stderr)
            setvbuf(stderr, nil, _IONBF, 0)  // unbuffered so the log is live
            if freopen(outPath, "wb", stdout) == nil {
                fputs("Error: cannot open output file \(outPath)\n", stderr)
                exit(1)
            }
            dlog("Writing PCM to file: \(outPath)\n")
        }

        dlog("ProcTap Helper starting for PID \(pid)\n")

        // Check and request all required permissions
        if !checkAllPermissions() {
            fputs("Error: Required permissions not granted\n", stderr)
            exit(1)
        }

        guard let processObjectID = findProcessAudioObject(pid: pid) else {
            fputs("Error: Process \(pid) has no audio\n", stderr)
            exit(1)
        }

        dlog("Found process audio object: \(processObjectID)\n")

        // DIAGNOSTIC: is the tapped process actually rendering output audio right now?
        var runAddr = AudioObjectPropertyAddress(
            mSelector: kAudioProcessPropertyIsRunningOutput,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var isRunningOut: UInt32 = 0
        var runSize = UInt32(MemoryLayout<UInt32>.size)
        let runStatus = AudioObjectGetPropertyData(
            processObjectID, &runAddr, 0, nil, &runSize, &isRunningOut)
        dlog("Process isRunningOutput=\(isRunningOut) (status=\(runStatus))\n")

        // CATapDescription is a public class since macOS 14.4. Construct it
        // directly instead of via fragile Objective-C runtime calls (the old
        // unsafeBitCast path crashed with a bus error on macOS 15).
        let tapUUID = UUID()
        let tapDescription = CATapDescription(stereoMixdownOfProcesses: [processObjectID])
        tapDescription.uuid = tapUUID

        dlog("Created tap description\n")

        // Create Process Tap
        var tapDeviceID: AudioObjectID = 0
        var status = AudioHardwareCreateProcessTap(tapDescription, &tapDeviceID)

        guard status == noErr, tapDeviceID != 0 else {
            fputs("Error: Failed to create Process Tap (status=\(status))\n", stderr)
            exit(1)
        }

        dlog("Process Tap created: device ID \(tapDeviceID)\n")

        // Read the tap's ACTUAL UID; the aggregate's tap list must reference this
        // (not merely the description's UUID) or the aggregate input is the phantom
        // silent input of the output subdevice instead of the tap.
        var tapUIDAddr = AudioObjectPropertyAddress(
            mSelector: kAudioTapPropertyUID,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var tapUIDRef: Unmanaged<CFString>?
        var tapUIDSize = UInt32(MemoryLayout<CFString>.size)
        let tapUIDStatus = AudioObjectGetPropertyData(
            tapDeviceID, &tapUIDAddr, 0, nil, &tapUIDSize, &tapUIDRef)
        let tapUIDString: String = (tapUIDStatus == noErr)
            ? (tapUIDRef?.takeRetainedValue() as String? ?? tapUUID.uuidString)
            : tapUUID.uuidString
        dlog("Tap UID: \(tapUIDString) (desc uuid: \(tapUUID.uuidString), status=\(tapUIDStatus))\n")

        // Read the tap's actual stream format (0 ch / 0 Hz => tap not really configured).
        var tapFmtAddr = AudioObjectPropertyAddress(
            mSelector: kAudioTapPropertyFormat,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var tapASBD = AudioStreamBasicDescription()
        var tapFmtSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        let tapFmtStatus = AudioObjectGetPropertyData(
            tapDeviceID, &tapFmtAddr, 0, nil, &tapFmtSize, &tapASBD)
        dlog("Tap format: status=\(tapFmtStatus) rate=\(tapASBD.mSampleRate) ch=\(tapASBD.mChannelsPerFrame) bits=\(tapASBD.mBitsPerChannel) flags=\(tapASBD.mFormatFlags) bytesPerFrame=\(tapASBD.mBytesPerFrame)\n")

        // Get default output device
        var defaultOutputPropertyAddress = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultOutputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )

        var defaultOutputID: AudioObjectID = 0
        var outputSize = UInt32(MemoryLayout<AudioObjectID>.size)

        status = AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject),
            &defaultOutputPropertyAddress,
            0, nil,
            &outputSize,
            &defaultOutputID
        )

        guard status == noErr else {
            fputs("Error: Failed to get default output device\n", stderr)
            AudioHardwareDestroyProcessTap(tapDeviceID)
            exit(1)
        }

        // Get output device UID
        var uidPropertyAddress = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyDeviceUID,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )

        var outputUID: Unmanaged<CFString>?
        var uidSize = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)

        status = AudioObjectGetPropertyData(
            defaultOutputID,
            &uidPropertyAddress,
            0, nil,
            &uidSize,
            &outputUID
        )

        let outputUIDString: String
        if status == noErr, let uid = outputUID?.takeRetainedValue() {
            outputUIDString = uid as String
        } else {
            fputs("WARNING: could not read default output UID (status=\(status)); using fallback\n", stderr)
            outputUIDString = "BuiltInSpeakerDevice"
        }

        // Create Aggregate Device
        let aggregateUID = UUID().uuidString

        // NOTE: the tap auto-start key is "tapautostart" (kAudioAggregateDeviceTapAutoStartKey);
        // the archived code used "autostart", which is ignored, so the tap was never
        // started and delivered silence.
        // Aggregate device wrapping the process tap (AudioCap-style). The tap auto-start
        // key is "tapautostart" (kAudioAggregateDeviceTapAutoStartKey) — the archived
        // code used "autostart", which is ignored.
        let description: [String: Any] = [
            "name": "ProcTap-\(pid)",
            "uid": aggregateUID,
            "private": true,
            "stacked": false,
            "tapautostart": true,
            "master": outputUIDString,
            "subdevices": [
                ["uid": outputUIDString]
            ],
            "taps": [
                [
                    "drift": true,
                    "uid": tapUIDString
                ]
            ]
        ]
        dlog("Aggregate output master UID: \(outputUIDString)\n")

        var aggregateDeviceID: AudioObjectID = 0
        status = AudioHardwareCreateAggregateDevice(description as CFDictionary, &aggregateDeviceID)

        guard status == noErr, aggregateDeviceID != 0 else {
            fputs("Error: Failed to create Aggregate Device (status=\(status))\n", stderr)
            AudioHardwareDestroyProcessTap(tapDeviceID)
            exit(1)
        }

        dlog("Aggregate Device created\n")

        // Create IOProc with block
        let queue = DispatchQueue(label: "com.proctap.ioproc", qos: .userInitiated)

        var ioProcID: AudioDeviceIOProcID?

        status = AudioDeviceCreateIOProcIDWithBlock(
            &ioProcID,
            aggregateDeviceID,
            queue
        ) { (now, inputData, inputTime, outputData, outputTime) in
            // The tapped audio arrives as a single interleaved stereo stream.
            let abl = UnsafeMutableAudioBufferListPointer(
                UnsafeMutablePointer(mutating: inputData))
            guard let buffer = abl.first, let data = buffer.mData else { return }
            let size = Int(buffer.mDataByteSize)
            let bytePtr = data.bindMemory(to: UInt8.self, capacity: size)
            FileHandle.standardOutput.write(Data(UnsafeBufferPointer(start: bytePtr, count: size)))
        }

        guard status == noErr, let procID = ioProcID else {
            fputs("Error: Failed to create IOProc (status=\(status))\n", stderr)
            AudioHardwareDestroyAggregateDevice(aggregateDeviceID)
            AudioHardwareDestroyProcessTap(tapDeviceID)
            exit(1)
        }

        // Start device
        status = AudioDeviceStart(aggregateDeviceID, procID)

        guard status == noErr else {
            fputs("Error: Failed to start device (status=\(status))\n", stderr)
            AudioDeviceDestroyIOProcID(aggregateDeviceID, procID)
            AudioHardwareDestroyAggregateDevice(aggregateDeviceID)
            AudioHardwareDestroyProcessTap(tapDeviceID)
            exit(1)
        }

        fputs("Ready\n", stderr)

        // Run forever
        // Note: Signal handling is managed by parent process
        RunLoop.main.run()
    }
}
