// swift-tools-version: 5.9
// ScreenCaptureKit requires macOS 13.0+

import PackageDescription

let package = Package(
    name: "screencapture-audio",
    platforms: [
        .macOS(.v13)  // ScreenCaptureKit introduced in macOS 13 (Ventura)
    ],
    targets: [
        .executableTarget(
            name: "screencapture-audio",
            linkerSettings: [
                .linkedFramework("ScreenCaptureKit"),
                .linkedFramework("AVFoundation"),
                .linkedFramework("CoreMedia"),
                .linkedFramework("CoreAudio")
            ]
        ),
    ]
)
