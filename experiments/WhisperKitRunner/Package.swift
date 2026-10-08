// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "BleepWhisperKitExperiment",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "BleepWhisperKit", targets: ["BleepWhisperKit"])],
    dependencies: [.package(url: "https://github.com/argmaxinc/argmax-oss-swift.git", exact: "1.1.0")],
    targets: [.executableTarget(name: "BleepWhisperKit", dependencies: [
        .product(name: "WhisperKit", package: "argmax-oss-swift")
    ])]
)
