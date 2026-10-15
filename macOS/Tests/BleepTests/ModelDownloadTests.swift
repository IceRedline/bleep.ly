import XCTest
import SwiftUI
@testable import Bleep

@MainActor
final class ModelDownloadTests: XCTestCase {
    private func fixture() throws -> (AppModel, UserDefaults, URL, URL) {
        let suite = "downloads-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(suite)
        let engine = folder.appendingPathComponent("censor")
        try FileManager.default.createDirectory(at: engine, withIntermediateDirectories: true)
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        defaults.set(folder.path, forKey: "projectRoot")
        defaults.set(root.appendingPathComponent(".venv/bin/python").path, forKey: "pythonPath")
        try Data("""
        import json, pathlib, sys
        request = json.loads(pathlib.Path(sys.argv[1]).read_text())
        with pathlib.Path('requests.jsonl').open('a') as log:
            log.write(json.dumps(request) + '\\n')
        if pathlib.Path('cached').exists():
            print(json.dumps({'version': 1, 'event': 'error', 'message': 'Cached model used'}))
        elif request['offline']:
            print(json.dumps({'version': 1, 'event': 'error', 'code': 'model_download_required', 'message': 'Missing model'}))
        else:
            print(json.dumps({'version': 1, 'event': 'error', 'message': 'Download started'}))
        sys.exit(1)
        """.utf8).write(to: engine.appendingPathComponent("desktop.py"))
        let source = folder.appendingPathComponent("source.wav")
        try Data().write(to: source)
        let model = AppModel(defaults: defaults, supportDirectory: folder.appendingPathComponent("support"))
        addTeardownBlock {
            await MainActor.run { model.cancel(); defaults.removePersistentDomain(forName: suite) }
            try? FileManager.default.removeItem(at: folder)
        }
        return (model, defaults, source, folder)
    }

    private func waitForPrompt(_ model: AppModel) async throws {
        for _ in 0..<500 where !model.requestingModelDownload && model.busy {
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTAssertTrue(model.requestingModelDownload, model.error ?? "No download prompt")
    }

    func testAcceptRetriesSameFileAndRemembersPermission() async throws {
        let (model, defaults, source, folder) = try fixture()
        let host = NSHostingView(rootView: ContentView(model: model).defaultAppStorage(defaults))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1120, height: 780),
                              styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.contentView = host
        window.orderFront(nil)
        defer { window.orderOut(nil) }
        XCTAssertEqual(ModelDownloadPermission.selected(defaults: defaults), .ask)
        let task = try XCTUnwrap(model.open(source))
        try await waitForPrompt(model)
        XCTAssertTrue(model.modelDownloadMessage.contains("Whisper Large v3 · CPU"))
        XCTAssertTrue(model.modelDownloadMessage.contains("3.1 GB"))
        for _ in 0..<100 where window.attachedSheet == nil {
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        let sheet = try XCTUnwrap(window.attachedSheet)
        func buttons(in view: NSView) -> [NSButton] {
            (view as? NSButton).map { [$0] } ?? view.subviews.flatMap { buttons(in: $0) }
        }
        let choices = buttons(in: try XCTUnwrap(sheet.contentView))
        XCTAssertTrue(choices.contains { $0.title == "Not Now" })
        let accept = try XCTUnwrap(choices.first { $0.title == "Allow Download" })
        accept.performClick(nil)
        await task.value
        XCTAssertFalse(model.requestingModelDownload)
        XCTAssertEqual(ModelDownloadPermission.selected(defaults: defaults), .allowed)
        XCTAssertEqual(model.error, "Download started")
        let lines = try String(contentsOf: folder.appendingPathComponent("requests.jsonl")).split(separator: "\n")
        let requests = try lines.map { try JSONSerialization.jsonObject(with: Data($0.utf8)) as! [String: Any] }
        XCTAssertEqual(requests.count, 2)
        XCTAssertEqual(requests.map { $0["offline"] as? Bool }, [true, false])
        XCTAssertTrue(requests.allSatisfy { $0["source"] as? String == source.path })
        await model.open(source)?.value
        XCTAssertEqual(model.error, "Download started")
        XCTAssertFalse(model.requestingModelDownload)
    }

    func testDeclineDoesNotDownloadAndSettingsCanReenable() async throws {
        let (model, defaults, source, folder) = try fixture()
        let task = try XCTUnwrap(model.open(source))
        try await waitForPrompt(model)
        model.answerModelDownload(false)
        await task.value
        XCTAssertNil(model.error)
        XCTAssertEqual(model.phase, .ready)
        XCTAssertEqual(ModelDownloadPermission.selected(defaults: defaults), .denied)
        XCTAssertEqual(try String(contentsOf: folder.appendingPathComponent("requests.jsonl")).split(separator: "\n").count, 1)
        await model.open(source)?.value
        XCTAssertFalse(model.requestingModelDownload)
        XCTAssertEqual(model.error, "Missing model\nError code: model_download_required")
        defaults.set(true, forKey: "allowDownloads")
        await model.open(source)?.value
        XCTAssertEqual(model.error, "Download started")
    }

    func testCancelDismissesPromptWithoutSavingDecision() async throws {
        let (model, defaults, source, _) = try fixture()
        let task = try XCTUnwrap(model.open(source))
        try await waitForPrompt(model)
        model.cancel()
        await task.value
        XCTAssertFalse(model.requestingModelDownload)
        XCTAssertNil(model.error)
        XCTAssertFalse(model.busy)
        XCTAssertEqual(ModelDownloadPermission.selected(defaults: defaults), .ask)
    }

    func testCachedModelDoesNotPromptAndLegacyPermissionIsRespected() async throws {
        let (model, defaults, source, folder) = try fixture()
        try Data().write(to: folder.appendingPathComponent("cached"))
        await model.open(source)?.value
        XCTAssertFalse(model.requestingModelDownload)
        XCTAssertEqual(model.error, "Cached model used")
        XCTAssertEqual(ModelDownloadPermission.selected(defaults: defaults), .ask)
        defaults.set(true, forKey: "allowDownloads")
        XCTAssertEqual(ModelDownloadPermission.selected(defaults: defaults), .allowed)
    }

    func testEverySelectableModelHasSizeAndRequiredComponents() {
        for engine in ["faster-whisper", "mlx", "whisperkit"] {
            for language in VideoLanguage.allCases {
                for model in RecognitionModel.choices(backend: engine, language: language) {
                    let backend = RecognitionModel.engine(model: model.rawValue, selected: engine)
                    let estimate = ModelDownloadEstimate(backend: backend, model: model.rawValue)
                    XCTAssertGreaterThan(estimate.bytes, 0)
                    XCTAssertTrue(estimate.summary.contains("GB"))
                    if engine == "mlx", model == .gigaAM || model == .qwen {
                        XCTAssertTrue(estimate.includesAligner)
                        XCTAssertGreaterThan(estimate.bytes, 1_840_013_484)
                        XCTAssertTrue(estimate.consentMessage.contains("word alignment"))
                    }
                }
            }
        }
        XCTAssertEqual(ModelDownloadEstimate(backend: "gigaam-mps", model: "gigaam-v3").size, "2.3 GB")
        XCTAssertEqual(ModelDownloadEstimate(backend: "mlx-qwen3-asr", model: "qwen3-asr").size, "6.6 GB")
    }
}
