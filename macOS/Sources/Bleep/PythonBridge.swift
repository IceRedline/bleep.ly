import Foundation
import Darwin

/// A single subprocess with line-delimited events. No shell interpolation.
@MainActor
final class PythonBridge {
    private var process: Process?
    private var cancelled = false

    func cancel() {
        cancelled = true
        guard let process, process.isRunning else { return }
        let pid = process.processIdentifier
        if kill(-pid, SIGTERM) != 0 { process.terminate() }
        // Model loading can be inside native code and ignore Python signals.
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self, weak process] in
            guard let self, self.cancelled, let process, process.isRunning else { return }
            kill(-pid, SIGKILL)
            kill(pid, SIGKILL)
        }
    }

    func run(root: URL, python: URL, request: [String: Any],
             progress: @escaping @MainActor (String, Double) -> Void,
             timing: @escaping @MainActor (Double) -> Void = { _ in }) async throws -> Data {
        guard process == nil else { throw BridgeFailure(message: "Another operation is still running.") }
        guard FileManager.default.fileExists(atPath: root.appendingPathComponent("censor/desktop.py").path) else {
            throw BridgeFailure(message: "Choose the bleep.ly project folder in Settings.")
        }
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            throw BridgeFailure(message: "Python was not found. Select the project's .venv/bin/python in Settings.")
        }
        cancelled = false
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-request-\(UUID())")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let requestURL = folder.appendingPathComponent("request.json")
        try JSONSerialization.data(withJSONObject: request).write(to: requestURL, options: .atomic)
        let errorURL = folder.appendingPathComponent("stderr.log")
        FileManager.default.createFile(atPath: errorURL.path, contents: nil)
        let errors = try FileHandle(forWritingTo: errorURL)
        defer { try? errors.close() }
        let output = Pipe()
        let child = Process()
        child.executableURL = python
        child.arguments = ["-u", "-m", "censor.desktop", requestURL.path]
        child.currentDirectoryURL = root
        child.environment = RuntimePaths.environment(root: root, python: python, support: AppModel.support,
                                                     inherited: ProcessInfo.processInfo.environment)
        child.standardOutput = output
        child.standardError = errors
        child.standardInput = FileHandle.nullDevice
        try child.run()
        process = child
        defer { process = nil }
        let data: Data = try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                var pending = Data()
                var result: Data?
                var failure: String?
                func consume(_ line: Data) {
                    guard let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
                          object["version"] as? Int == 1 else { return }
                    switch object["event"] as? String {
                    case "progress":
                        let stage = object["stage"] as? String ?? "Processing"
                        let fraction = object["fraction"] as? Double ?? 0
                        let duration = object["duration"] as? Double ?? 0
                        Task { @MainActor in
                            timing(duration)
                            progress(stage, min(1, max(0, fraction)))
                        }
                    case "result": result = line
                    case "error": failure = object["message"] as? String
                    default: break
                    }
                }
                while true {
                    let chunk = output.fileHandleForReading.availableData
                    if chunk.isEmpty { break }
                    pending.append(chunk)
                    while let newline = pending.firstIndex(of: 10) {
                        consume(Data(pending[..<newline]))
                        pending.removeSubrange(...newline)
                    }
                }
                if !pending.isEmpty { consume(pending) }
                child.waitUntilExit()
                try? output.fileHandleForReading.close()
                if child.terminationStatus == 0, let result {
                    continuation.resume(returning: result)
                } else {
                    let diagnostic = (try? String(contentsOf: errorURL, encoding: .utf8)) ?? ""
                    continuation.resume(throwing: BridgeFailure(message: failure ??
                        (diagnostic.isEmpty ? "Processing stopped (\(child.terminationStatus))." : String(diagnostic.suffix(4000)))))
                }
            }
        }
        if cancelled { throw CancellationError() }
        return data
    }
}
