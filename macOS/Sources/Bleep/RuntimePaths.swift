import Foundation
import CryptoKit

/// Release bundles own their engine; mutable data always lives outside the app.
enum RuntimePaths {
    /// Stable across launches and moves, different for a new build or installed copy.
    static func recognitionCacheIdentity(bundleURL: URL = Bundle.main.bundleURL,
                                         info: [String: Any] = Bundle.main.infoDictionary ?? [:]) throws -> String {
        let attributes = try FileManager.default.attributesOfItem(atPath: bundleURL.resolvingSymlinksInPath().path)
        guard let device = attributes[.systemNumber] as? NSNumber,
              let inode = attributes[.systemFileNumber] as? NSNumber,
              let created = attributes[.creationDate] as? Date else {
            throw BridgeFailure(message: "Cannot identify this app installation for the recognition cache.")
        }
        let identity: [String: String] = [
            "version": info["CFBundleShortVersionString"] as? String ?? "development",
            "build": info["CFBundleVersion"] as? String ?? "development",
            "build_id": info["BleepBuildID"] as? String ?? "unpackaged",
            "device": device.stringValue, "inode": inode.stringValue,
            "created": String(created.timeIntervalSince1970)
        ]
        let data = try JSONSerialization.data(withJSONObject: identity, options: [.sortedKeys])
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static var bundledRoot: URL? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        let root = resources.appendingPathComponent("Engine", isDirectory: true)
        return isBundled(root) ? root : nil
    }

    static func isBundled(_ root: URL) -> Bool {
        FileManager.default.fileExists(atPath: root.appendingPathComponent("runtime.json").path)
    }

    static func python(root: URL, experimental: Bool = false) -> URL {
        if isBundled(root) {
            return root.appendingPathComponent("../Runtime/\(experimental ? "PythonGPU" : "Python")/bin/python3.11")
                .standardizedFileURL
        }
        return root.appendingPathComponent(experimental ? ".cache/asr-env/bin/python" : ".venv/bin/python")
    }

    static func models(root: URL, support: URL) -> URL {
        isBundled(root) ? support.appendingPathComponent("models") : root.appendingPathComponent(".cache")
    }

    static func history(root: URL, support: URL) -> URL {
        isBundled(root) ? support.appendingPathComponent("recognition-history")
            : root.appendingPathComponent("тесты bleep.ly/recognition-history")
    }

    static func environment(root: URL, python: URL, support: URL,
                            inherited: [String: String]) -> [String: String] {
        var result = inherited
        result["PYTHONUNBUFFERED"] = "1"
        result["HF_HUB_DISABLE_TELEMETRY"] = "1"
        result["DO_NOT_TRACK"] = "1"
        if isBundled(root) {
            if SandboxFiles.enabled {
                result["HOME"] = NSHomeDirectory()
                result["TMPDIR"] = FileManager.default.temporaryDirectory.path
            }
            // Finder launches must not depend on shell, Homebrew or a user's Python.
            for key in ["PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"] {
                result.removeValue(forKey: key)
            }
            result["PATH"] = root.appendingPathComponent("../../Helpers").standardizedFileURL.path + ":/usr/bin:/bin"
            result["PYTHONNOUSERSITE"] = "1"
            result["PYTHONDONTWRITEBYTECODE"] = "1"
            result["BLEEP_MODEL_CACHE"] = models(root: root, support: support).path
            result["HF_HOME"] = models(root: root, support: support).appendingPathComponent("huggingface").path
            result["XDG_CACHE_HOME"] = support.appendingPathComponent("cache").path
            result["NUMBA_CACHE_DIR"] = support.appendingPathComponent("cache/numba").path
            result["MPLCONFIGDIR"] = support.appendingPathComponent("cache/matplotlib").path
            let certificates = python.deletingLastPathComponent().deletingLastPathComponent()
                .appendingPathComponent("lib/python3.11/site-packages/certifi/cacert.pem").path
            result["SSL_CERT_FILE"] = certificates
            result["REQUESTS_CA_BUNDLE"] = certificates
        } else {
            result["PATH"] = "\(root.appendingPathComponent(".venv/bin").path):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
            if result["HF_HOME"] == nil { result["HF_HOME"] = root.appendingPathComponent(".cache/huggingface").path }
        }
        return result
    }
}
