import XCTest
import SwiftUI
@testable import Bleep

final class BridgeTests: XCTestCase {
    private var root: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
    }

    func testNativeErrorRetainsDomainCodeAndUnderlyingCode() {
        let error = NSError(domain: "AVFoundationErrorDomain", code: -11828, userInfo: [
            NSLocalizedDescriptionKey: "Cannot Open",
            NSUnderlyingErrorKey: NSError(domain: NSOSStatusErrorDomain, code: -12847)
        ])
        let message = errorMessage(error)
        XCTAssertTrue(message.contains("Cannot Open"))
        XCTAssertTrue(message.contains("AVFoundationErrorDomain (-11828)"))
        XCTAssertTrue(message.contains("NSOSStatusErrorDomain (-12847)"))
    }

    @MainActor
    func testRealPythonBridgeAnalysisAndExport() async throws {
        let python = root.appendingPathComponent(".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            throw XCTSkip("Local Python environment is required")
        }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-swift-test-\(UUID())")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let source = folder.appendingPathComponent("аудио source.wav")
        // Generate a tiny WAV with the standard library; no model or network required.
        let generator = Process()
        generator.executableURL = python
        generator.arguments = ["-c", "import wave,sys; w=wave.open(sys.argv[1],'wb'); w.setparams((1,2,48000,0,'NONE','')); w.writeframes(b'\\0\\0'*96000); w.close()", source.path]
        try generator.run(); generator.waitUntilExit()
        XCTAssertEqual(generator.terminationStatus, 0)
        let transcript = folder.appendingPathComponent("review.json")
        try Data("""
        {"words":[{"word":"test","start":0.5,"end":1,"profane":true}]}
        """.utf8).write(to: transcript)
        let bridge = PythonBridge()
        let data = try await bridge.run(root: root, python: python,
            request: ["operation": "analyze", "source": source.path, "transcript": transcript.path]) { _, _ in }
        let document = try JSONDecoder.bridge.decode(ReviewDocument.self, from: data)
        XCTAssertFalse(document.hasVideo)
        XCTAssertEqual(document.count, 1)
        XCTAssertEqual(document.words[0].muteStart, 0.6, accuracy: 0.0001)
        let output = folder.appendingPathComponent("clean.wav")
        _ = try await bridge.run(root: root, python: python, request: [
            "operation": "export", "output": output.path, "format": "audio", "sound": "beep",
            "document": try JSONSerialization.jsonObject(with: JSONEncoder.bridge.encode(document))
        ]) { _, _ in }
        XCTAssertTrue(FileManager.default.fileExists(atPath: output.path))
        do {
            _ = try await bridge.run(root: root, python: python,
                request: ["operation": "analyze", "source": "/does/not/exist"]) { _, _ in }
            XCTFail("Missing media must fail")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("does not exist"))
            XCTAssertEqual((error as? BridgeFailure)?.code, "processing_failed")
            XCTAssertTrue(error.localizedDescription.contains("Error code: processing_failed"))
        }
    }

    @MainActor
    func testWorkerCrashIncludesExitCodeAndDiagnostic() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-error-\(UUID())")
        let package = folder.appendingPathComponent("censor")
        try FileManager.default.createDirectory(at: package, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        try Data().write(to: package.appendingPathComponent("__init__.py"))
        try Data("import sys\nprint('Native model failed', file=sys.stderr)\nsys.exit(7)".utf8)
            .write(to: package.appendingPathComponent("desktop.py"))
        do {
            _ = try await PythonBridge().run(root: folder, python: URL(fileURLWithPath: "/usr/bin/python3"),
                request: ["operation": "test"]) { _, _ in }
            XCTFail("Worker must fail")
        } catch {
            XCTAssertEqual((error as? BridgeFailure)?.code, "worker_exit_7")
            XCTAssertTrue(error.localizedDescription.contains("Native model failed"))
            XCTAssertTrue(error.localizedDescription.contains("Error code: worker_exit_7"))
        }
    }

    @MainActor
    func testCancellationStopsWorkerGroup() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-cancel-\(UUID())")
        let package = folder.appendingPathComponent("censor")
        try FileManager.default.createDirectory(at: package, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        try Data().write(to: package.appendingPathComponent("__init__.py"))
        let script = """
        import os, signal, subprocess, sys, time
        os.setsid()
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        def stop(*_):
            child.wait(timeout=5)
            sys.exit(130)
        signal.signal(signal.SIGTERM, stop)
        print('{"version":1,"event":"progress","stage":"Running","fraction":0}', flush=True)
        time.sleep(60)
        """
        try Data(script.utf8).write(to: package.appendingPathComponent("desktop.py"))
        let bridge = PythonBridge()
        let started = Date()
        do {
            _ = try await bridge.run(root: folder, python: URL(fileURLWithPath: "/usr/bin/python3"),
                                     request: ["operation": "test"]) { _, _ in bridge.cancel() }
            XCTFail("Cancelled worker must not succeed")
        } catch { XCTAssertLessThan(Date().timeIntervalSince(started), 8) }
    }

    @MainActor
    func testRenderScreensForVisualReview() async throws {
        // These artifacts are ignored, and only generated by the local test suite.
        let folder = root.appendingPathComponent(".cache/macos-previews")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let model = AppModel()
        for scenario in ["ready", "analyzing", "review", "review-unchecked", "done", "fast-video", "fast-audio"] {
            let phase = AppModel.Phase(rawValue: scenario) ?? .review
            if phase == .review { model.document = nil; model.phase = .ready; model.selectMode(.advanced) }
            if phase == .ready { model.selectMode(.fast) }
            if phase == .done {
                model.selectMode(.fast)
                model.exportURL = URL(fileURLWithPath: "/tmp/Podcast_censored.wav")
            }
            model.phase = phase
            if phase == .analyzing { model.fraction = 0.43; model.stage = "Recognizing speech"; model.sourceName = "Podcast.wav" }
            if phase == .review {
                model.document = ReviewDocument(source: "/tmp/Podcast.wav", fingerprint: "preview", duration: 1123,
                    hasVideo: false, audioCount: 1,
                    words: (0..<8).map { index in
                        let start = Double(50 + index * 115)
                        return ReviewWord(word: "Review word \(index + 1)", start: start, end: start + 0.5,
                                          profane: true, muteStart: start + 0.1, muteEnd: start + 0.4)
                    })
            }
            if scenario.hasPrefix("fast-") {
                model.selectMode(.fast)
                model.exportURL = nil
                model.document?.hasVideo = scenario == "fast-video"
                model.document?.source = scenario == "fast-video" ? "/tmp/Podcast.mov" : "/tmp/Podcast.wav"
            }
            if scenario == "review-unchecked" {
                model.document?.words[0].reviewCandidate = true
                model.document?.words[0].profane = false
            }
            let view = NSHostingView(rootView: ContentView(model: model)
                .environment(\.colorScheme, .dark).frame(width: 1120, height: 780))
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1120, height: 780),
                                  styleMask: [.borderless], backing: .buffered, defer: false)
            window.appearance = NSAppearance(named: .darkAqua)
            window.contentView = view
            view.frame = NSRect(x: 0, y: 0, width: 1120, height: 780)
            window.orderFront(nil)
            view.layoutSubtreeIfNeeded()
            try await Task.sleep(nanoseconds: 150_000_000)
            view.layoutSubtreeIfNeeded()
            let bitmap = try XCTUnwrap(view.bitmapImageRepForCachingDisplay(in: view.bounds))
            view.cacheDisplay(in: view.bounds, to: bitmap)
            window.orderOut(nil)
            let png = try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
            try png.write(to: folder.appendingPathComponent("\(scenario).png"))
        }
    }
}
