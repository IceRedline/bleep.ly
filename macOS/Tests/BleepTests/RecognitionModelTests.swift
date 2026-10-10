import XCTest
@testable import Bleep

@MainActor
final class RecognitionModelTests: XCTestCase {
    func testSelectionIsForwardedToPythonAndWhisperKitKeepsTurbo() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("model-request-\(UUID())")
        let package = folder.appendingPathComponent("censor")
        try FileManager.default.createDirectory(at: package, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        try Data().write(to: package.appendingPathComponent("__init__.py"))
        try Data("""
        import json, sys
        from pathlib import Path
        request = json.loads(Path(sys.argv[1]).read_text())
        Path('captured.json').write_text(json.dumps(request))
        print(json.dumps(dict(version=1, event='error', message='Request captured without inference')))
        sys.exit(1)
        """.utf8).write(to: package.appendingPathComponent("desktop.py"))
        let suite = "model-choice-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set(folder.path, forKey: "projectRoot")
        defaults.set("/usr/bin/python3", forKey: "pythonPath")
        try WordListPreferences.save([.russian: WordListDraft(censor: "бля", allow: "бляха")], defaults: defaults)
        let model = AppModel(defaults: defaults, supportDirectory: folder.appendingPathComponent("support"))
        for (backend, choice, expected, engine) in [
            ("faster-whisper", "", "large-v3", "faster-whisper"),
            ("faster-whisper", "large-v3-turbo", "large-v3-turbo", "faster-whisper"),
            ("faster-whisper", "qwen3-asr", "large-v3", "faster-whisper"),
            ("mlx", "large-v3", "large-v3", "mlx"),
            ("mlx", "large-v3-turbo", "large-v3-turbo", "mlx"),
            ("mlx", "invalid", "large-v3", "mlx"),
            ("mlx", "parakeet-v3", "parakeet-v3", "parakeet-mlx"),
            ("mlx", "parakeet-ultra", "parakeet-ultra", "parakeet-mlx"),
            ("mlx", "qwen3-asr", "qwen3-asr", "mlx-qwen3-asr"),
            ("mlx", "gigaam-v3", "gigaam-v3", "gigaam-mps"),
            ("whisperkit", "large-v3", "large-v3-turbo", "whisperkit")
        ] {
            defaults.set(backend, forKey: "backend")
            defaults.set(choice, forKey: "recognitionModel")
            await model.open(folder.appendingPathComponent("source.wav"), workflow: .advanced)?.value
            XCTAssertEqual(model.error, "Request captured without inference")
            let data = try Data(contentsOf: folder.appendingPathComponent("captured.json"))
            let request = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            let lists = try XCTUnwrap(request["word_lists"] as? [String: [String]])
            XCTAssertEqual(lists["censor"], ["бля"])
            XCTAssertEqual(lists["allow"], ["бляха"])
            XCTAssertEqual(request["model"] as? String, expected)
            XCTAssertEqual(request["backend"] as? String, engine)
            XCTAssertEqual(request["history_dir"] as? String, folder.appendingPathComponent("тесты bleep.ly/recognition-history").path)
            XCTAssertEqual(defaults.string(forKey: "recognitionModel"), choice, "WhisperKit must not overwrite the CPU/MLX choice")
        }
        defaults.set("mlx", forKey: "backend")
        defaults.set("gigaam-v3", forKey: "recognitionModel")
        model.selectLanguage(.english)
        XCTAssertEqual(defaults.string(forKey: "recognitionModel"), "large-v3-turbo")
        XCTAssertFalse(RecognitionModel.choices(backend: "mlx", language: .english).contains(.gigaAM))
        await model.open(folder.appendingPathComponent("source.wav"), workflow: .advanced)?.value
        let englishRequest = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: folder.appendingPathComponent("captured.json"))) as? [String: Any])
        XCTAssertEqual(englishRequest["language"] as? String, "en")
        XCTAssertEqual(englishRequest["backend"] as? String, "mlx")
        XCTAssertEqual(englishRequest["model"] as? String, "large-v3-turbo")
        let restored = AppModel(defaults: defaults, supportDirectory: folder.appendingPathComponent("support2"))
        XCTAssertEqual(restored.videoLanguage, .english)
        defaults.set("parakeet-v3", forKey: "recognitionModel")
        model.selectLanguage(.russian)
        XCTAssertEqual(defaults.string(forKey: "recognitionModel"), "gigaam-v3")
        XCTAssertEqual(defaults.string(forKey: "backend"), "mlx")
        await model.open(folder.appendingPathComponent("source.wav"), workflow: .advanced)?.value
        let russianRequest = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: folder.appendingPathComponent("captured.json"))) as? [String: Any])
        XCTAssertEqual(russianRequest["backend"] as? String, "gigaam-mps")
        XCTAssertEqual(russianRequest["language"] as? String, "ru")
        defaults.set("qwen3-asr", forKey: "recognitionModel")
        model.selectLanguage(.russian)
        XCTAssertEqual(defaults.string(forKey: "recognitionModel"), "qwen3-asr", "Selecting the same language keeps a manual override")
        defaults.set("whisperkit", forKey: "backend")
        model.selectLanguage(.english)
        XCTAssertEqual(defaults.string(forKey: "backend"), "mlx")
        XCTAssertEqual(defaults.string(forKey: "recognitionModel"), "large-v3-turbo")
        defaults.set("faster-whisper", forKey: "backend")
        model.selectLanguage(.russian)
        XCTAssertEqual(defaults.string(forKey: "backend"), "mlx")
        defaults.set("faster-whisper", forKey: "backend")
        model.selectLanguage(.english)
        XCTAssertEqual(defaults.string(forKey: "backend"), "faster-whisper")
        XCTAssertEqual(defaults.string(forKey: "recognitionModel"), "large-v3-turbo")
        model.selectLanguage(.russian)
        XCTAssertTrue(RecognitionModel.choices(backend: "mlx", language: .russian).contains(.gigaAM))
        defaults.removeObject(forKey: "pythonPath")
        defaults.set("mlx", forKey: "backend")
        defaults.set("parakeet-v3", forKey: "recognitionModel")
        let experimentalPython = folder.appendingPathComponent(".cache/asr-env/bin/python")
        try FileManager.default.createDirectory(at: experimentalPython.deletingLastPathComponent(), withIntermediateDirectories: true)
        // macOS /usr/bin/python3 is an argv[0]-sensitive shim, not a symlinkable Python binary.
        let launcher = Data("#!/bin/sh\nexec /usr/bin/python3 \"$@\"\n".utf8)
        try launcher.write(to: experimentalPython)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: experimentalPython.path)
        await model.open(folder.appendingPathComponent("source.wav"), workflow: .advanced)?.value
        XCTAssertEqual(model.error, "Request captured without inference", "Experimental models must automatically select their separate runtime")

        try FileManager.default.removeItem(at: experimentalPython)
        let standardPython = folder.appendingPathComponent(".venv/bin/python")
        try FileManager.default.createDirectory(at: standardPython.deletingLastPathComponent(), withIntermediateDirectories: true)
        try launcher.write(to: standardPython)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: standardPython.path)
        await model.open(folder.appendingPathComponent("source.wav"), transcript: folder.appendingPathComponent("review.json"), workflow: .advanced)?.value
        XCTAssertEqual(model.error, "Request captured without inference", "Importing reviewed words must not require experimental inference dependencies")
    }
}
