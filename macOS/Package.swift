// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Bleep",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "Bleep", targets: ["Bleep"])],
    targets: [
        // VideoPlayer's SwiftUI overlay resolves its AVPlayerView superclass at
        // runtime. Link AVKit explicitly: importing the overlay alone can leave
        // it out of the standalone executable, even though XCTest loads it.
        .executableTarget(name: "Bleep", linkerSettings: [.linkedFramework("AVKit")]),
        .testTarget(name: "BleepTests", dependencies: ["Bleep"])
    ]
)
