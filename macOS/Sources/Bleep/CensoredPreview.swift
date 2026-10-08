import Foundation

/// Preview uses the export mixer so mute boundaries, complete cue tails and limiting match.
/// Only the selected audio track is rendered; original video remains in AVFoundation.
@MainActor
final class CensoredPreview {
    private var bridge: PythonBridge?
    private var cachedKey: Data?
    private var cachedURL: URL?

    func cancel() { bridge?.cancel() }

    func clear() {
        cancel()
        if let cachedURL { try? FileManager.default.removeItem(at: cachedURL.deletingLastPathComponent()) }
        cachedKey = nil; cachedURL = nil
    }

    func audio(document: ReviewDocument, track: Int, sound: String, customSound: URL?,
               root: URL, python: URL, progress: @escaping @MainActor (String, Double) -> Void) async throws -> URL {
        var selected = document
        selected.tracks = document.audioTracks.filter { $0.index == track }
        selected.words = document.words.filter { ($0.audioTrack ?? document.audioStream ?? 0) == track }
        selected.audioStream = track
        var request: [String: Any] = ["operation": "export", "format": "audio", "sound": sound,
            "document": try JSONSerialization.jsonObject(with: JSONEncoder.bridge.encode(selected))]
        if let customSound { request["custom_sound"] = customSound.path }
        var identity = request
        // Replaced files must not reuse stale preview audio.
        for (name, url) in [("source", document.url), ("cue", sound == "custom" ? customSound : nil)] {
            if let url {
                let values = try url.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey])
                identity[name + "_size"] = values.fileSize
                identity[name + "_modified"] = values.contentModificationDate?.timeIntervalSince1970
            }
        }
        let key = try JSONSerialization.data(withJSONObject: identity, options: [.sortedKeys])
        if cachedKey == key, let cachedURL, FileManager.default.fileExists(atPath: cachedURL.path) { return cachedURL }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-preview-\(UUID())")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let output = folder.appendingPathComponent("censored.wav")
        request["output"] = output.path
        let worker = PythonBridge()
        bridge = worker
        defer { if bridge === worker { bridge = nil } }
        do {
            try Task.checkCancellation()
            _ = try await worker.run(root: root, python: python, request: request, progress: progress)
            try Task.checkCancellation()
            if let cachedURL { try? FileManager.default.removeItem(at: cachedURL.deletingLastPathComponent()) }
            cachedKey = key; cachedURL = output
            return output
        } catch {
            try? FileManager.default.removeItem(at: folder)
            throw error
        }
    }
}
