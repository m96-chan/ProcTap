import Foundation
import ScreenCaptureKit
import AVFoundation
import CoreMedia
import CoreAudio

// MARK: - Audio Capture Stream Handler

@available(macOS 13.0, *)
class AudioCaptureHandler: NSObject, SCStreamDelegate, SCStreamOutput {
    private var stream: SCStream?
    private let bundleID: String
    private let sampleRate: Int
    private let channels: Int
    private var isRunning = false

    init(bundleID: String, sampleRate: Int = 48000, channels: Int = 2) {
        self.bundleID = bundleID
        self.sampleRate = sampleRate
        self.channels = channels
        super.init()
    }

    // MARK: - Permission Check

    func checkScreenRecordingPermission() -> Bool {
        if #available(macOS 14.0, *) {
            // macOS 14.0+ has canRecordScreen property
            return CGPreflightScreenCaptureAccess()
        } else {
            // For macOS 13.x, request permission
            return CGRequestScreenCaptureAccess()
        }
    }

    // MARK: - Stream Setup

    func start() async throws {
        fputs("Checking Screen Recording permission...\n", stderr)

        guard checkScreenRecordingPermission() else {
            fputs("ERROR: Screen Recording permission not granted\n", stderr)
            fputs("Please enable: System Settings → Privacy & Security → Screen Recording\n", stderr)
            throw NSError(domain: "AudioCapture", code: 1,
                         userInfo: [NSLocalizedDescriptionKey: "Screen Recording permission required"])
        }

        fputs("Screen Recording permission: OK\n", stderr)
        fputs("Fetching available applications...\n", stderr)

        // Get all shareable content
        let availableContent = try await SCShareableContent.excludingDesktopWindows(
            false,
            onScreenWindowsOnly: false
        )

        // Find application by bundle ID
        guard let targetApp = availableContent.applications.first(where: {
            $0.bundleIdentifier == bundleID
        }) else {
            fputs("ERROR: Application with bundleID '\(bundleID)' not found\n", stderr)
            fputs("\nAvailable applications:\n", stderr)
            for app in availableContent.applications.prefix(10) {
                fputs("  - \(app.applicationName) (\(app.bundleIdentifier))\n", stderr)
            }
            throw NSError(domain: "AudioCapture", code: 2,
                         userInfo: [NSLocalizedDescriptionKey: "Application not found"])
        }

        fputs("Found application: \(targetApp.applicationName)\n", stderr)

        // Configure stream for audio capture only
        let configuration = SCStreamConfiguration()

        // Audio AND video capture (ScreenCaptureKit requires both for audio to work)
        configuration.capturesAudio = true

        // Video settings (minimum resolution)
        configuration.width = 100
        configuration.height = 100
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 2)  // 2 FPS
        configuration.pixelFormat = kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange

        // Audio configuration
        configuration.sampleRate = self.sampleRate
        configuration.channelCount = self.channels

        // Exclude our own process audio (we don't want to capture our own sounds)
        configuration.excludesCurrentProcessAudio = true

        fputs("Stream configuration:\n", stderr)
        fputs("  - Sample Rate: \(configuration.sampleRate) Hz\n", stderr)
        fputs("  - Channels: \(configuration.channelCount)\n", stderr)
        fputs("  - Audio Only: true\n", stderr)

        // Create filter for app-specific audio
        guard let display = availableContent.displays.first else {
            fputs("ERROR: No display found\n", stderr)
            throw NSError(domain: "AudioCapture", code: 3,
                         userInfo: [NSLocalizedDescriptionKey: "No display available"])
        }

        // Get windows for the app
        let appWindows = availableContent.windows.filter { window in
            window.owningApplication?.bundleIdentifier == bundleID
        }

        fputs("Found \(appWindows.count) windows for app\n", stderr)

        // Create content filter for app-specific audio
        // Note: ScreenCaptureKit audio capture on macOS 15+ supports app-specific filtering
        // when using display-wide filter with specific apps included
        fputs("Creating app-specific audio filter\n", stderr)
        let audioFilter = SCContentFilter(
            display: display,
            including: [targetApp],
            exceptingWindows: []
        )

        fputs("Created audio filter for: \(targetApp.applicationName)\n", stderr)

        let newStream = SCStream(filter: audioFilter, configuration: configuration, delegate: self)
        stream = newStream

        fputs("Created SCStream instance\n", stderr)

        // Add audio output handler
        try newStream.addStreamOutput(self, type: .audio, sampleHandlerQueue: .global(qos: .userInteractive))

        fputs("Added audio output handler\n", stderr)
        fputs("Starting audio capture stream...\n", stderr)

        do {
            try await newStream.startCapture()
            isRunning = true
            fputs("Audio capture started successfully!\n", stderr)
            fputs("Streaming PCM audio data to stdout...\n\n", stderr)
        } catch {
            fputs("ERROR: Failed to start stream: \(error)\n", stderr)
            fputs("ERROR: \(error.localizedDescription)\n", stderr)
            throw error
        }
    }

    func stop() async throws {
        guard isRunning else { return }
        fputs("\nStopping audio capture...\n", stderr)
        try await stream?.stopCapture()
        isRunning = false
        fputs("Audio capture stopped\n", stderr)
    }

    // MARK: - SCStreamOutput

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of outputType: SCStreamOutputType) {
        // Only process audio samples
        guard outputType == .audio else {
            return
        }

        // Extract PCM audio data from CMSampleBuffer
        guard let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else {
            fputs("WARNING: No data buffer in sample\n", stderr)
            return
        }

        var length: Int = 0
        var dataPointer: UnsafeMutablePointer<Int8>?

        let status = CMBlockBufferGetDataPointer(
            blockBuffer,
            atOffset: 0,
            lengthAtOffsetOut: nil,
            totalLengthOut: &length,
            dataPointerOut: &dataPointer
        )

        guard status == kCMBlockBufferNoErr, let data = dataPointer else {
            fputs("WARNING: Failed to get data pointer (status=\(status))\n", stderr)
            return
        }

        // Write raw PCM data to stdout
        let bufferPointer = UnsafeRawBufferPointer(start: data, count: length)
        let dataArray = Data(bufferPointer)

        FileHandle.standardOutput.write(dataArray)
    }

    // MARK: - SCStreamDelegate

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fputs("ERROR: Stream stopped with error: \(error.localizedDescription)\n", stderr)
        isRunning = false
    }
}

// MARK: - Main Entry Point

@available(macOS 13.0, *)
@main
struct ScreenCaptureAudio {
    static func main() async {
        // Parse command line arguments
        let arguments = CommandLine.arguments

        guard arguments.count >= 2 else {
            fputs("""
            Usage: screencapture-audio <bundleID> [sample_rate] [channels]

            Arguments:
              bundleID     - Application bundle identifier (e.g., com.apple.Safari)
              sample_rate  - Audio sample rate in Hz (default: 48000)
              channels     - Number of audio channels (default: 2)

            Example:
              screencapture-audio com.google.Chrome 48000 2 > output.pcm

            Output:
              Raw PCM audio data is written to stdout
              Progress/errors are written to stderr

            Required Permissions:
              - Screen Recording (System Settings → Privacy & Security → Screen Recording)

            """, stderr)
            exit(1)
        }

        let bundleID = arguments[1]
        let sampleRate = arguments.count > 2 ? Int(arguments[2]) ?? 48000 : 48000
        let channels = arguments.count > 3 ? Int(arguments[3]) ?? 2 : 2

        fputs("=== ScreenCaptureKit Audio Capture ===\n", stderr)
        fputs("Target Bundle ID: \(bundleID)\n", stderr)
        fputs("Sample Rate: \(sampleRate) Hz\n", stderr)
        fputs("Channels: \(channels)\n\n", stderr)

        // Create capture handler
        let handler = AudioCaptureHandler(
            bundleID: bundleID,
            sampleRate: sampleRate,
            channels: channels
        )

        do {
            // Start capture
            try await handler.start()

            // Keep running indefinitely
            // Signal handling is delegated to parent process
            // Note: Task.sleep with very large values can be optimized away,
            // so we use a loop with reasonable intervals
            while true {
                try await Task.sleep(nanoseconds: 1_000_000_000)  // 1 second
            }

        } catch is CancellationError {
            fputs("\nReceived cancellation, stopping...\n", stderr)
            try? await handler.stop()
        } catch {
            fputs("FATAL ERROR: \(error.localizedDescription)\n", stderr)
            try? await handler.stop()
            exit(1)
        }

        fputs("Exiting cleanly\n", stderr)
        exit(0)
    }
}
