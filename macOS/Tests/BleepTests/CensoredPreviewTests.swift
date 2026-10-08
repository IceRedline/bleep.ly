import XCTest
import AVFoundation
import SwiftUI
@testable import Bleep

@MainActor
final class CensoredPreviewTests: XCTestCase {
    private var root: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
    }

    private func fixture(tracks: Int = 1) async throws -> (AppModel, URL, URL) {
        let python = root.appendingPathComponent(".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { throw XCTSkip("Python required") }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-preview-test-\(UUID())")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: folder) }
        let source = folder.appendingPathComponent("source.mov")
        let result = folder.appendingPathComponent("review.json")
        let generator = Process()
        generator.executableURL = python; generator.currentDirectoryURL = root
        generator.environment = ["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"]
        generator.standardOutput = FileHandle.nullDevice
        generator.arguments = ["-c", """
        import sys, json
        from unittest.mock import patch
        from censor.ffmpeg import run
        from censor.desktop import analyze
        from censor.models import WordTimestamp
        tracks = int(sys.argv[3])
        args = ['ffmpeg','-v','error','-f','lavfi','-i','color=blue:s=160x90:r=25:d=4',
                '-f','lavfi','-i','sine=frequency=440:duration=4']
        if tracks == 2:
            args += ['-f','lavfi','-i','sine=frequency=880:duration=4']
        args += ['-map','0:v','-map','1:a']
        if tracks == 2: args += ['-map','2:a']
        run(args + ['-c:v','libx264','-c:a','aac',sys.argv[1]])
        with patch('censor.desktop.FasterWhisperBackend.transcribe', side_effect=[
                [WordTimestamp('бля',1,1.3)], [WordTimestamp('бля',2,2.3)]]):
            doc = analyze(dict(source=sys.argv[1],cache_dir=sys.argv[4],censor_style='full'))
        open(sys.argv[2], 'w').write(json.dumps(doc))
        """, source.path, result.path, String(tracks), folder.appendingPathComponent("cache").path]
        try generator.run(); generator.waitUntilExit()
        XCTAssertEqual(generator.terminationStatus, 0)
        let suite = "preview-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        addTeardownBlock { UserDefaults(suiteName: suite)?.removePersistentDomain(forName: suite) }
        defaults.set(root.path, forKey: "projectRoot")
        let model = AppModel(defaults: defaults, supportDirectory: folder.appendingPathComponent("support"))
        model.document = try JSONDecoder.bridge.decode(ReviewDocument.self, from: Data(contentsOf: result))
        model.phase = .review; model.sourceName = source.lastPathComponent
        model.selectMode(.advanced)
        await model.selectAudioTrack(0)?.value
        return (model, source, folder)
    }

    private func audioURL(_ model: AppModel) async throws -> URL {
        let item = try XCTUnwrap(model.player.currentItem)
        if let asset = item.asset as? AVURLAsset { return asset.url }
        let tracks = try await item.asset.loadTracks(withMediaType: .audio)
        let track = try XCTUnwrap(tracks.first as? AVCompositionTrack)
        return try XCTUnwrap(track.segments.first(where: { !$0.isEmpty })?.sourceURL)
    }

    private func amplitude(_ url: URL, at seconds: Double, frequency: Double) throws -> Double {
        let process = Process(); let output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.environment = ["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"]
        process.arguments = ["ffmpeg", "-v", "error", "-i", url.path, "-ss", String(seconds), "-t", "0.05",
                             "-ac", "1", "-ar", "48000", "-f", "f32le", "-"]
        process.standardOutput = output
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit(); XCTAssertEqual(process.terminationStatus, 0)
        let samples = data.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
        XCTAssertFalse(samples.isEmpty)
        var real = 0.0, imaginary = 0.0
        for (index, sample) in samples.enumerated() {
            let angle = 2 * Double.pi * frequency * Double(index) / 48000
            real += Double(sample) * cos(angle); imaginary += Double(sample) * sin(angle)
        }
        return 2 * hypot(real, imaginary) / Double(samples.count)
    }

    private func waitForPreview(_ model: AppModel) async throws {
        for _ in 0..<200 where model.preparingPreview || model.loadingPlayer { try await Task.sleep(nanoseconds: 50_000_000) }
        XCTAssertFalse(model.preparingPreview)
        XCTAssertFalse(model.loadingPlayer)
        XCTAssertNil(model.error)
    }

    func testPreviewUsesExportMixerAndRefreshesSoundEditsAndUndo() async throws {
        let (model, source, folder) = try await fixture()
        defer { model.goHome() }
        let sourceBytes = try Data(contentsOf: source)
        XCTAssertTrue(model.previewCensorship)
        await model.setPreviewCensorship(false)?.value
        let original = try await audioURL(model)
        XCTAssertEqual(original.resolvingSymlinksInPath(), source.resolvingSymlinksInPath())
        XCTAssertGreaterThan(try amplitude(original, at: 1.1, frequency: 440), 0.08)
        model.seek(0.7)
        try await Task.sleep(nanoseconds: 150_000_000)
        await model.setPreviewCensorship(true)?.value
        XCTAssertNil(model.error)
        XCTAssertEqual(model.player.currentTime().seconds, 0.7, accuracy: 0.05)
        let beep = try await audioURL(model)
        XCTAssertNotEqual(beep, source)
        XCTAssertLessThan(try amplitude(beep, at: 1.1, frequency: 440), 0.005)
        XCTAssertGreaterThan(try amplitude(beep, at: 1.1, frequency: 1000), 0.08)
        let video = try await XCTUnwrap(model.player.currentItem).asset.loadTracks(withMediaType: .video)
        XCTAssertEqual(video.count, 1)
        let word = try XCTUnwrap(model.document?.words.first)
        model.audition(word)
        try await Task.sleep(nanoseconds: 1_000_000_000)
        XCTAssertFalse(model.isPlaying)
        XCTAssertEqual(model.playhead, 1.5, accuracy: 0.1)
        // Toggle off/on reuses the rendered track and keeps the current timeline position.
        await model.setPreviewCensorship(false)?.value
        let restored = try await audioURL(model)
        XCTAssertEqual(restored.resolvingSymlinksInPath(), source.resolvingSymlinksInPath())
        XCTAssertEqual(model.player.currentTime().seconds, 1.5, accuracy: 0.1)
        await model.setPreviewCensorship(true)?.value
        let reused = try await audioURL(model)
        XCTAssertEqual(reused, beep)

        let cue = folder.appendingPathComponent("cue.wav")
        let generator = Process()
        generator.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        generator.environment = ["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"]
        generator.arguments = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=1200:duration=0.9", cue.path]
        try generator.run(); generator.waitUntilExit()
        model.setSound(cue)
        try await waitForPreview(model)
        let custom = try await audioURL(model)
        XCTAssertGreaterThan(try amplitude(custom, at: 1.5, frequency: 1200), 0.08)
        XCTAssertGreaterThan(try amplitude(custom, at: 1.5, frequency: 440), 0.08)
        XCTAssertLessThan(try amplitude(custom, at: 2.1, frequency: 1200), 0.005)
        model.sound = "silence"
        try await waitForPreview(model)
        let silence = try await audioURL(model)
        XCTAssertLessThan(try amplitude(silence, at: 1.1, frequency: 440), 0.005)
        XCTAssertLessThan(try amplitude(silence, at: 1.1, frequency: 1000), 0.005)
        // All three completed variants remain reusable without a new render.
        for (mode, expected) in [("beep", beep), ("custom", custom), ("silence", silence)] {
            model.sound = mode
            XCTAssertFalse(model.preparingPreview, "Cached \(mode) must not start rendering")
            try await waitForPreview(model)
            let reusedMode = try await audioURL(model)
            XCTAssertEqual(reusedMode, expected)
        }
        model.toggle(word)
        try await waitForPreview(model)
        let unchecked = try await audioURL(model)
        XCTAssertGreaterThan(try amplitude(unchecked, at: 1.1, frequency: 440), 0.08)
        model.undo()
        try await waitForPreview(model)
        let undone = try await audioURL(model)
        XCTAssertLessThan(try amplitude(undone, at: 1.1, frequency: 440), 0.005)
        model.updateInterval(id: word.id, start: 1.5, end: 1.7)
        try await waitForPreview(model)
        let edited = try await audioURL(model)
        XCTAssertGreaterThan(try amplitude(edited, at: 1.1, frequency: 440), 0.08)
        XCTAssertLessThan(try amplitude(edited, at: 1.6, frequency: 440), 0.005)
        XCTAssertNil(model.exportURL)
        XCTAssertEqual(try Data(contentsOf: source), sourceBytes)
        model.goHome()
        for url in [beep, custom, silence, unchecked, edited] {
            XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))
        }
    }

    func testTrackSelectionCancellationAndFailureKeepOriginalPlayable() async throws {
        let (model, source, _) = try await fixture(tracks: 2)
        defer { model.goHome() }
        model.sound = "silence"
        await model.setPreviewCensorship(true)?.value
        let first = try await audioURL(model)
        XCTAssertLessThan(try amplitude(first, at: 1.1, frequency: 440), 0.005)
        await model.selectAudioTrack(1)?.value
        let second = try await audioURL(model)
        XCTAssertGreaterThan(try amplitude(second, at: 1.1, frequency: 880), 0.08)
        XCTAssertLessThan(try amplitude(second, at: 2.1, frequency: 880), 0.005)
        let pending = model.setPreviewCensorship(true)
        await model.setPreviewCensorship(false)?.value
        await pending?.value
        XCTAssertFalse(model.previewCensorship)
        let restored = try await audioURL(model)
        XCTAssertEqual(restored.resolvingSymlinksInPath(), source.resolvingSymlinksInPath())
        XCTAssertNil(model.error)
        await model.setPreviewCensorship(true)?.value
        model.setSound(source)
        try FileManager.default.removeItem(at: XCTUnwrap(model.customSound))
        for _ in 0..<100 where model.preparingPreview || model.loadingPlayer { try await Task.sleep(nanoseconds: 50_000_000) }
        XCTAssertNotNil(model.error)
        XCTAssertNotNil(model.player.currentItem)
        XCTAssertFalse(model.playingCensoredPreview)
        XCTAssertTrue(model.previewCensorship)
        model.goHome()
        XCTAssertNil(model.player.currentItem)
        XCTAssertFalse(model.preparingPreview)
    }
    func testHomeCancelsAnActivePreviewWorker() async throws {
        let (model, _, folder) = try await fixture()
        defer { model.goHome() }
        let fakeRoot = folder.appendingPathComponent("worker")
        let package = fakeRoot.appendingPathComponent("censor")
        try FileManager.default.createDirectory(at: package, withIntermediateDirectories: true)
        try Data().write(to: package.appendingPathComponent("__init__.py"))
        try Data("""
        import os, signal, sys, time
        from pathlib import Path
        if os.getpgrp() != os.getpid(): os.setsid()
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(130))
        Path('started').touch()
        print('{"version":1,"event":"progress","stage":"Exporting audio","fraction":0}', flush=True)
        time.sleep(20)
        """.utf8).write(to: package.appendingPathComponent("desktop.py"))
        let suite = "cancel-preview-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set(fakeRoot.path, forKey: "projectRoot")
        defaults.set("/usr/bin/python3", forKey: "pythonPath")
        let cancellable = AppModel(defaults: defaults, supportDirectory: folder.appendingPathComponent("cancel-support"))
        cancellable.document = model.document; cancellable.phase = .review
        let task = try XCTUnwrap(cancellable.setPreviewCensorship(true))
        let marker = fakeRoot.appendingPathComponent("started")
        for _ in 0..<100 where !FileManager.default.fileExists(atPath: marker.path) {
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTAssertTrue(FileManager.default.fileExists(atPath: marker.path), cancellable.error ?? "Worker did not start")
        XCTAssertTrue(cancellable.preparingPreview)
        XCTAssertFalse(cancellable.loadingPlayer)
        XCTAssertFalse(cancellable.playingCensoredPreview)
        XCTAssertNotNil(cancellable.player.currentItem)
        cancellable.togglePlayback()
        try await Task.sleep(nanoseconds: 300_000_000)
        XCTAssertGreaterThan(cancellable.playhead, 0.05, "Original playback must work during rendering")
        let start = Date()
        cancellable.goHome()
        await task.value
        XCTAssertLessThan(Date().timeIntervalSince(start), 5)
        XCTAssertEqual(cancellable.phase, .ready)
        XCTAssertNil(cancellable.document)
        XCTAssertNil(cancellable.player.currentItem)
        XCTAssertNil(cancellable.error)
        XCTAssertFalse(cancellable.preparingPreview)
    }

}
