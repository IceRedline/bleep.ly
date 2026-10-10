import XCTest
@testable import Bleep

final class RuntimePathsTests: XCTestCase {
    func testRelocatedBundleUsesItsOwnRuntimesAndWritableCaches() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-runtime-\(UUID())")
        defer { try? FileManager.default.removeItem(at: folder) }
        let root = folder.appendingPathComponent("Moved App.app/Contents/Resources/Engine")
        let support = folder.appendingPathComponent("User Support")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try Data("{}".utf8).write(to: root.appendingPathComponent("runtime.json"))
        let python = RuntimePaths.python(root: root)
        XCTAssertEqual(python.path, folder.appendingPathComponent("Moved App.app/Contents/Frameworks/Python/bin/python3.11").path)
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

    func testDevelopmentBuildRetainsExistingPathsAndHFOverride() {
        let root = URL(fileURLWithPath: "/tmp/bleep-development-source")
        let support = URL(fileURLWithPath: "/tmp/bleep-support")
        let python = RuntimePaths.python(root: root)
        XCTAssertEqual(python.path, root.appendingPathComponent(".venv/bin/python").path)
        XCTAssertEqual(RuntimePaths.python(root: root, experimental: true).path, root.appendingPathComponent(".cache/asr-env/bin/python").path)
        XCTAssertEqual(RuntimePaths.models(root: root, support: support).path, root.appendingPathComponent(".cache").path)
        XCTAssertEqual(RuntimePaths.environment(root: root, python: python, support: support,
            inherited: ["HF_HOME": "/custom/models"])["HF_HOME"], "/custom/models")
    }
}
