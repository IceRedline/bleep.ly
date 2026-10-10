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
        let model = AppModel(defaults: defaults, supportDirectory: folder.appendingPathComponent("support"))
        for (backend, choice, expected) in [
            ("faster-whisper", "", "large-v3"),
            ("faster-whisper", "large-v3-turbo", "large-v3-turbo"),
            ("mlx", "large-v3", "large-v3"),
            ("mlx", "large-v3-turbo", "large-v3-turbo"),
            ("mlx", "invalid", "large-v3"),
            ("whisperkit", "large-v3", "large-v3-turbo")
        ] {
            defaults.set(backend, forKey: "backend")
            defaults.set(choice, forKey: "recognitionModel")
            await model.open(folder.appendingPathComponent("source.wav"), workflow: .advanced)?.value
            XCTAssertEqual(model.error, "Request captured without inference")
            let data = try Data(contentsOf: folder.appendingPathComponent("captured.json"))
            let request = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            XCTAssertEqual(request["model"] as? String, expected)
            XCTAssertEqual(request["backend"] as? String, backend)
            XCTAssertEqual(defaults.string(forKey: "recognitionModel"), choice, "WhisperKit must not overwrite the CPU/MLX choice")
        }
    }
}
