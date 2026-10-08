// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Bleep",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "Bleep", targets: ["Bleep"])],
    targets: [
        .executableTarget(name: "Bleep"),
        .testTarget(name: "BleepTests", dependencies: ["Bleep"])
    ]
)
