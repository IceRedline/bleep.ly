import XCTest
import SwiftUI
import AVKit
@testable import Bleep

final class VideoPreviewTests: XCTestCase {
    func testStandaloneExecutableLinksVideoPlayerSuperclassFramework() throws {
        // The test runner itself loads AVKit, which can hide the app-only crash.
        // Inspect the actual product beside this test bundle instead.
        let executable = Bundle(for: Self.self).bundleURL.deletingLastPathComponent()
            .appendingPathComponent("Bleep")
        XCTAssertTrue(FileManager.default.isExecutableFile(atPath: executable.path))
        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/otool")
        process.arguments = ["-L", executable.path]
        process.standardOutput = output
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        XCTAssertEqual(process.terminationStatus, 0)
        XCTAssertTrue(String(decoding: data, as: UTF8.self)
            .contains("/AVKit.framework/Versions/A/AVKit"),
            "Standalone app must load AVKit before SwiftUI creates VideoPlayerView")
    }

    @MainActor
    func testVideoReviewCreatesPlayerAndSurvivesScreenTransitions() async throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let python = root.appendingPathComponent(".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            throw XCTSkip("Local Python environment is required")
        }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-video-test-\(UUID())")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let source = folder.appendingPathComponent("video with spaces.mov")
        let generator = Process()
        generator.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        generator.environment = ["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"]
        generator.arguments = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=25:d=2",
                               "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-c:a", "aac", source.path]
        try generator.run(); generator.waitUntilExit()
        XCTAssertEqual(generator.terminationStatus, 0)
        let transcript = folder.appendingPathComponent("review.json")
        try Data("""
        {"words":[{"word":"test","start":0.5,"end":1,"profane":true}]}
        """.utf8).write(to: transcript)

        let model = AppModel()
        model.selectMode(.advanced)
        let host = NSHostingView(rootView: ContentView(model: model).frame(width: 1120, height: 780))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1120, height: 780),
                              styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = host
        window.orderFront(nil)
        defer { model.pause(); model.player.replaceCurrentItem(with: nil); window.orderOut(nil) }
        model.phase = .analyzing
        let data = try await PythonBridge().run(root: root, python: python, request: [
            "operation": "analyze", "source": source.path, "transcript": transcript.path
        ]) { _, _ in }
        model.document = try JSONDecoder.bridge.decode(ReviewDocument.self, from: data)
        XCTAssertTrue(try XCTUnwrap(model.document).hasVideo)
        let item = AVPlayerItem(url: source)
        model.player.replaceCurrentItem(with: item)
        model.phase = .review
        host.layoutSubtreeIfNeeded()
        try await Task.sleep(nanoseconds: 500_000_000)
        for _ in 0..<30 where item.status == .unknown {
            try await Task.sleep(nanoseconds: 100_000_000)
        }
        XCTAssertEqual(item.status, .readyToPlay, item.error?.localizedDescription ?? "Video did not load")

        func players(in view: NSView) -> [AVPlayerView] {
            (view as? AVPlayerView).map { [$0] } ?? view.subviews.flatMap { players(in: $0) }
        }
        let initialPlayer = try XCTUnwrap(players(in: host).first)
        XCTAssertTrue(initialPlayer.player === model.player)
        XCTAssertGreaterThan(initialPlayer.bounds.width, 0)
        model.seek(0.75)
        try await Task.sleep(nanoseconds: 300_000_000)
        XCTAssertEqual(model.player.currentTime().seconds, 0.75, accuracy: 0.1)
        // Rendering/export hides the preview; returning must reattach the player.
        model.phase = .exporting
        try await Task.sleep(nanoseconds: 300_000_000)
        model.phase = .review
        try await Task.sleep(nanoseconds: 300_000_000)
        XCTAssertTrue(try XCTUnwrap(players(in: host).first).player === model.player)
    }
}
