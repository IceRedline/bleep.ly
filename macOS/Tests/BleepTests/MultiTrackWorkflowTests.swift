import XCTest
import SwiftUI
import AVFoundation
@testable import Bleep

@MainActor
final class MultiTrackWorkflowTests: XCTestCase {
    func testFastKeepsTwoStreamsAndAdvancedEditsAndPreviewsSelectedTrack() async throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let python = root.appendingPathComponent(".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { throw XCTSkip("Python required") }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-multi-\(UUID())")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let source = folder.appendingPathComponent("two.mov")
        let support = folder.appendingPathComponent("support")
        // Populate independent real backend caches with deterministic words, without model inference.
        let generator = Process()
        generator.executableURL = python
        generator.currentDirectoryURL = root
        generator.environment = ["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"]
        generator.arguments = ["-c", """
        import sys
        from unittest.mock import patch
        from censor.ffmpeg import run
        from censor.desktop import analyze
        from censor.models import WordTimestamp
        run(['ffmpeg','-v','error','-f','lavfi','-i','color=blue:s=160x90:r=25:d=4',
             '-f','lavfi','-i','sine=frequency=440:duration=4',
             '-f','lavfi','-i','sine=frequency=880:duration=4',
             '-map','0:v','-map','1:a','-map','2:a','-c:v','libx264','-c:a','aac',sys.argv[1]])
        with patch('censor.desktop.FasterWhisperBackend.transcribe',side_effect=[
            [WordTimestamp('бля',1,1.3)], [WordTimestamp('бля',2,2.3)]]):
            analyze(dict(source=sys.argv[1],cache_dir=sys.argv[2],model='large-v3'))
        """, source.path, support.appendingPathComponent("cache").path]
        generator.standardOutput = FileHandle.nullDevice
        try generator.run(); generator.waitUntilExit()
        XCTAssertEqual(generator.terminationStatus, 0)
        let suite = "multitrack-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set(root.path, forKey: "projectRoot")
        let model = AppModel(defaults: defaults, supportDirectory: support)
        await model.open(source, workflow: .fast)?.value
        XCTAssertNil(model.error)
        XCTAssertEqual(model.phase, .done)
        XCTAssertEqual(model.document?.audioTracks.count, 2)
        XCTAssertEqual(model.document?.cacheHit, true)
        let exported = try XCTUnwrap(model.exportURL)
        let tracks = try await AVURLAsset(url: exported).loadTracks(withMediaType: .audio)
        XCTAssertEqual(tracks.count, 2)
        model.selectMode(.advanced)
        await model.selectAudioTrack(1)?.value
        XCTAssertEqual(model.visibleWords.count, 1)
        let word = try XCTUnwrap(model.visibleWords.first)
        XCTAssertEqual(word.audioTrack, 1)
        let item = try XCTUnwrap(model.player.currentItem)
        let previewTracks = try await item.asset.loadTracks(withMediaType: .audio)
        XCTAssertEqual(previewTracks.count, 1)
        XCTAssertEqual(model.player.currentItem?.asset is AVComposition, true)
        model.updateInterval(id: word.id, start: 2.05, end: 2.2)
        XCTAssertEqual(try XCTUnwrap(model.document?.words.first?.muteStart), 1.06, accuracy: 0.0001)
        XCTAssertEqual(model.visibleWords.first?.muteStart, 2.05)
        for _ in 0..<100 where model.preparingPreview { try await Task.sleep(nanoseconds: 50_000_000) }
        model.audition(word)
        try await Task.sleep(nanoseconds: 1_200_000_000)
        XCTAssertFalse(model.isPlaying)
        XCTAssertLessThan(model.playhead, 2.6)
        XCTAssertGreaterThanOrEqual(model.playhead, 2.4)
        await model.setPreviewCensorship(true)?.value
        XCTAssertNil(model.error)
        XCTAssertTrue(model.previewCensorship)
        let host = NSHostingView(rootView: ContentView(model: model).frame(width: 880, height: 690))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 880, height: 690),
                              styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.contentView = host; window.orderFront(nil)
        defer { window.orderOut(nil); model.goHome() }
        try await Task.sleep(nanoseconds: 300_000_000)
        let frame = try XCTUnwrap(host.superview)
        let bitmap = try XCTUnwrap(frame.bitmapImageRepForCachingDisplay(in: frame.bounds))
        frame.cacheDisplay(in: frame.bounds, to: bitmap)
        let previews = root.appendingPathComponent(".cache/macos-previews")
        try FileManager.default.createDirectory(at: previews, withIntermediateDirectories: true)
        try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
            .write(to: previews.appendingPathComponent("two-tracks.png"))
        // Manual JSON import replaces only the selected track.
        let transcript = folder.appendingPathComponent("track.json")
        try Data("{\"words\":[{\"word\":\"edited\",\"start\":2.5,\"end\":2.8,\"profane\":true}]}".utf8).write(to: transcript)
        await model.open(source, transcript: transcript, replacingTrack: 1)?.value
        XCTAssertNil(model.error)
        XCTAssertEqual(model.document?.words.first?.start, 1)
        XCTAssertEqual(model.visibleWords.first?.word, "edited")
        XCTAssertEqual(model.document?.audioTracks.count, 2)
    }
}
