import XCTest
import AVFoundation
@testable import Bleep

@MainActor
final class WorkflowTests: XCTestCase {
    private func fixture(video: Bool = false) throws -> (AppModel, URL, URL, UserDefaults) {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let python = root.appendingPathComponent(".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { throw XCTSkip("Local Python required") }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-workflow-\(UUID())")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: folder) }
        let suite = "bleep-tests-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        addTeardownBlock { UserDefaults(suiteName: suite)?.removePersistentDomain(forName: suite) }
        defaults.set(root.path, forKey: "projectRoot")
        let model = AppModel(defaults: defaults, supportDirectory: folder.appendingPathComponent("support"))
        let source = folder.appendingPathComponent(video ? "видео.mov" : "audio.wav")
        let generator = Process()
        generator.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        generator.environment = ["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"]
        generator.arguments = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2"] +
            (video ? ["-f", "lavfi", "-i", "color=c=blue:s=160x90:r=25:d=2", "-c:v", "libx264", "-c:a", "aac"] : []) + [source.path]
        try generator.run(); generator.waitUntilExit()
        XCTAssertEqual(generator.terminationStatus, 0)
        let transcript = folder.appendingPathComponent("review.json")
        try Data("""
        {"words":[{"word":"test","start":0.5,"end":1.5,"profane":true}]}
        """.utf8).write(to: transcript)
        return (model, source, transcript, defaults)
    }

    func testFastVideoExportsAutomaticallyAndAvoidsExistingFiles() async throws {
        let (model, source, transcript, defaults) = try fixture(video: true)
        defaults.set("full", forKey: "censorStyle")
        XCTAssertEqual(model.workflowMode, .fast)
        let existing = source.deletingLastPathComponent().appendingPathComponent("видео_censored.mov")
        try Data("keep".utf8).write(to: existing)
        let sourceBytes = try Data(contentsOf: source)
        let task = try XCTUnwrap(model.open(source, transcript: transcript, workflow: .fast))
        XCTAssertTrue(model.busy)
        // Mode changes are locked until the whole analysis/export operation finishes.
        model.selectMode(.advanced)
        XCTAssertEqual(model.workflowMode, .fast)
        await task.value
        XCTAssertNil(model.error)
        XCTAssertEqual(model.phase, .done)
        let result = try XCTUnwrap(model.exportURL)
        XCTAssertEqual(result.lastPathComponent, "видео_censored_2.mov")
        XCTAssertTrue(FileManager.default.fileExists(atPath: result.path))
        XCTAssertEqual(try Data(contentsOf: existing), Data("keep".utf8))
        XCTAssertEqual(try Data(contentsOf: source), sourceBytes)
        let tracks = try await AVURLAsset(url: result).loadTracks(withMediaType: .video)
        XCTAssertEqual(tracks.count, 1)
        XCTAssertEqual(model.document?.censorStyle, "full")
        XCTAssertEqual(model.document?.words.first?.muteStart, 0.5)
        XCTAssertEqual(model.document?.words.first?.muteEnd, 1.5)
        XCTAssertEqual(defaults.string(forKey: "workflowMode"), "fast")
    }

    func testFastAudioDefaultsToWAVAndAdvancedKeepsReview() async throws {
        let (model, source, transcript, defaults) = try fixture()
        model.sound = "silence"
        await model.open(source, transcript: transcript, workflow: .fast)?.value
        XCTAssertNil(model.error)
        XCTAssertEqual(model.exportURL?.pathExtension, "wav")
        XCTAssertEqual(model.phase, .done)
        let review = try XCTUnwrap(model.document)
        XCTAssertEqual(review.censorStyle, "middle")
        XCTAssertGreaterThan(review.words[0].muteStart, review.words[0].start)
        model.selectMode(.advanced)
        XCTAssertEqual(model.document, review)
        XCTAssertEqual(defaults.string(forKey: "workflowMode"), "advanced")
        model.updateInterval(id: review.words[0].id, start: 0.7, end: 1.1)
        defaults.set("full", forKey: "censorStyle")
        model.startNewFile()
        XCTAssertFalse(model.canUndo)
        model.restoreDraft()
        XCTAssertNil(model.error)
        XCTAssertEqual(model.workflowMode, .advanced)
        XCTAssertEqual(model.document?.words.first?.muteStart, 0.7)
        XCTAssertEqual(model.document?.words.first?.muteEnd, 1.1)
        // A new Advanced import stops for review and does not export a second file.
        await model.open(source, transcript: transcript)?.value
        XCTAssertEqual(model.phase, .review)
        XCTAssertNil(model.exportURL)
        XCTAssertFalse(FileManager.default.fileExists(atPath: source.deletingLastPathComponent()
            .appendingPathComponent("audio_censored_2.wav").path))
    }

    func testFastExportFailureKeepsReviewAndCanRetryWithoutRecognition() async throws {
        let (model, source, transcript, _) = try fixture()
        model.sound = "custom"
        XCTAssertNil(model.open(source, transcript: transcript, workflow: .fast))
        XCTAssertFalse(model.busy)
        let invalidSound = source.deletingLastPathComponent().appendingPathComponent("invalid.wav")
        try Data("not audio".utf8).write(to: invalidSound)
        model.setSound(invalidSound)
        await model.open(source, transcript: transcript, workflow: .fast)?.value
        XCTAssertNotNil(model.error)
        XCTAssertNotNil(model.document)
        XCTAssertEqual(model.phase, .review)
        XCTAssertNil(model.exportURL)
        // The retry only renders the saved review (transcript can be removed).
        try FileManager.default.removeItem(at: transcript)
        model.sound = "beep"
        await model.beginExport()?.value
        XCTAssertNil(model.error)
        XCTAssertEqual(model.phase, .done)
        XCTAssertNotNil(model.exportURL)
    }

    func testImmediateCancellationDoesNotLaunchAutomaticExport() async throws {
        let (model, source, transcript, _) = try fixture()
        let task = try XCTUnwrap(model.open(source, transcript: transcript, workflow: .fast))
        model.cancel()
        await task.value
        XCTAssertFalse(model.busy)
        XCTAssertNil(model.error)
        XCTAssertNil(model.document)
        XCTAssertNil(model.exportURL)
        XCTAssertFalse(FileManager.default.fileExists(atPath: source.deletingLastPathComponent()
            .appendingPathComponent("audio_censored.wav").path))
    }
    func testHomeCancelsAndReturnsToEmptyWelcome() async throws {
        let (model, source, transcript, _) = try fixture()
        let task = try XCTUnwrap(model.open(source, transcript: transcript, workflow: .fast))
        model.goHome()
        await task.value
        XCTAssertEqual(model.phase, .ready)
        XCTAssertNil(model.document)
        XCTAssertNil(model.exportURL)
        XCTAssertFalse(model.cancelling)
        await model.open(source, transcript: transcript, workflow: .advanced)?.value
        XCTAssertEqual(model.phase, .review)
        model.goHome()
        XCTAssertEqual(model.phase, .ready)
        XCTAssertNil(model.document)
        XCTAssertNil(model.player.currentItem)
        model.restoreDraft()
        XCTAssertEqual(model.phase, .review)
        XCTAssertNotNil(model.document)
        let export = try XCTUnwrap(model.beginExport())
        model.goHome()
        await export.value
        XCTAssertEqual(model.phase, .ready)
        XCTAssertNil(model.exportURL)
    }

}
