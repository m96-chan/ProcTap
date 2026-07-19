// swift-tools-version: 6.1
// The swift-tools-version declares the minimum version of Swift required to build this package.

import PackageDescription

let package = Package(
    name: "proctap-helper",
    platforms: [
        .macOS(.v14)  // macOS 14.2+ required for Process Tap API
    ],
    targets: [
        // Targets are the basic building blocks of a package, defining a module or a test suite.
        // Targets can depend on other targets in this package and products from dependencies.
        .executableTarget(
            name: "proctap-helper",
            linkerSettings: [
                .linkedFramework("AVFoundation")
            ]
        ),
    ],
    // Swift 5 language mode: the Core Audio IOProc block is invoked by CoreAudio
    // on its own dispatch queue. Under the Swift 6 language mode the closure
    // inherits @main's MainActor isolation and traps with a dispatch-queue
    // executor assertion (_dispatch_assert_queue_fail) on the first callback.
    swiftLanguageModes: [.v5]
)
