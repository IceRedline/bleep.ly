import XCTest
@testable import Bleep

final class RuntimePathsTests: XCTestCase {
    func testRecognitionCacheSurvivesRelaunchAndMoveButNotReinstallation() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-install-\(UUID())")
        defer { try? FileManager.default.removeItem(at: folder) }
        let app = folder.appendingPathComponent("bleep.ly.app")
        let moved = folder.appendingPathComponent("Moved.app")
        try FileManager.default.createDirectory(at: app, withIntermediateDirectories: true)
        let info = ["CFBundleShortVersionString": "0.1.1", "CFBundleVersion": "7", "BleepBuildID": "build-a"]
        let initial = try RuntimePaths.recognitionCacheIdentity(bundleURL: app, info: info)
        XCTAssertEqual(try RuntimePaths.recognitionCacheIdentity(bundleURL: app, info: info), initial)
        // An unrelated change to the directory's modification time is not an installation.
        try Data().write(to: app.appendingPathComponent("unrelated-file"))
        XCTAssertEqual(try RuntimePaths.recognitionCacheIdentity(bundleURL: app, info: info), initial)
        try FileManager.default.moveItem(at: app, to: moved)
        XCTAssertEqual(try RuntimePaths.recognitionCacheIdentity(bundleURL: moved, info: info), initial)
        // Reinstall the exact same build at the original path, with a new directory identity.
        try FileManager.default.copyItem(at: moved, to: app)
        let reinstalled = try RuntimePaths.recognitionCacheIdentity(bundleURL: app, info: info)
        XCTAssertNotEqual(reinstalled, initial)
        XCTAssertEqual(try RuntimePaths.recognitionCacheIdentity(bundleURL: app, info: info), reinstalled)
    }

    func testRecognitionCacheChangesForVersionBuildAndRebuild() throws {
        let info = ["CFBundleShortVersionString": "0.1.1", "CFBundleVersion": "7", "BleepBuildID": "build-a"]
        let original = try RuntimePaths.recognitionCacheIdentity(info: info)
        for (key, value) in [("CFBundleShortVersionString", "0.1.2"), ("CFBundleVersion", "8"), ("BleepBuildID", "build-b")] {
            var updated = info
            updated[key] = value
            XCTAssertNotEqual(try RuntimePaths.recognitionCacheIdentity(info: updated), original)
        }
    }

    func testRelocatedBundleUsesItsOwnRuntimesAndWritableCaches() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-runtime-\(UUID())")
        defer { try? FileManager.default.removeItem(at: folder) }
        let root = folder.appendingPathComponent("Moved App.app/Contents/Resources/Engine")
        let support = folder.appendingPathComponent("User Support")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try Data("{}".utf8).write(to: root.appendingPathComponent("runtime.json"))
        let python = RuntimePaths.python(root: root)
        XCTAssertEqual(python.path, folder.appendingPathComponent("Moved App.app/Contents/Resources/Runtime/Python/bin/python3.11").path)
        XCTAssertTrue(RuntimePaths.python(root: root, experimental: true).path.contains("/PythonGPU/"))
        let environment = RuntimePaths.environment(root: root, python: python, support: support,
            inherited: ["HOME": "/Users/example", "PYTHONHOME": "/old/python", "PYTHONPATH": "/old/project",
                        "HF_HOME": "/old/models", "DYLD_LIBRARY_PATH": "/opt/homebrew/lib"])
        XCTAssertNil(environment["PYTHONHOME"])
        XCTAssertNil(environment["PYTHONPATH"])
        XCTAssertNil(environment["DYLD_LIBRARY_PATH"])
        XCTAssertEqual(environment["HOME"], "/Users/example")
        XCTAssertFalse(try XCTUnwrap(environment["PATH"]).contains("homebrew"))
        XCTAssertEqual(environment["HF_HOME"], support.appendingPathComponent("models/huggingface").path)
        XCTAssertEqual(environment["BLEEP_MODEL_CACHE"], support.appendingPathComponent("models").path)
        XCTAssertEqual(environment["NUMBA_CACHE_DIR"], support.appendingPathComponent("cache/numba").path)
        XCTAssertEqual(RuntimePaths.history(root: root, support: support).path, support.appendingPathComponent("recognition-history").path)
    }

    func testDevelopmentRuntimeSurvivesCacheDeletion() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-cache-removal-\(UUID())")
        defer { try? FileManager.default.removeItem(at: root) }
        let python = RuntimePaths.python(root: root, experimental: true)
        try FileManager.default.createDirectory(at: python.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("runtime fixture".utf8).write(to: python)
        let cache = RuntimePaths.models(root: root, support: root)
        try FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
        try Data().write(to: cache.appendingPathComponent("model.bin"))
        try FileManager.default.removeItem(at: cache)
        XCTAssertEqual(try Data(contentsOf: RuntimePaths.python(root: root, experimental: true)), Data("runtime fixture".utf8))
    }

    func testDevelopmentBuildUsesPersistentRuntimeAndHFOverride() {
        let root = URL(fileURLWithPath: "/tmp/bleep-development-source")
        let support = URL(fileURLWithPath: "/tmp/bleep-support")
        let python = RuntimePaths.python(root: root)
        XCTAssertEqual(python.path, root.appendingPathComponent(".venv/bin/python").path)
        XCTAssertEqual(RuntimePaths.python(root: root, experimental: true).path, root.appendingPathComponent(".runtime/asr-env/bin/python").path)
        XCTAssertEqual(RuntimePaths.models(root: root, support: support).path, root.appendingPathComponent(".cache").path)
        XCTAssertEqual(RuntimePaths.environment(root: root, python: python, support: support,
            inherited: ["HF_HOME": "/custom/models"])["HF_HOME"], "/custom/models")
    }
}
