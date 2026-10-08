import Foundation

/// Cache processed audio by review, track and sound; video always stays in the original file.
@MainActor
final class CensoredPreview {
    private var bridge: PythonBridge?
    private var cached: [Data: URL] = [:]
    private var recentKeys: [Data] = []

    func cancel() { bridge?.cancel() }

    func clear() {
        cancel()
        for url in cached.values { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        cached.removeAll(); recentKeys.removeAll()
    }

    private func request(document: ReviewDocument, track: Int, sound: String, customSound: URL?) throws -> (Data, [String: Any]) {
        var selected = document
        selected.tracks = document.audioTracks.filter { $0.index == track }
        selected.words = document.words.filter { ($0.audioTrack ?? document.audioStream ?? 0) == track }
        selected.audioStream = track
        var request: [String: Any] = ["operation": "export", "format": "audio", "sound": sound,
            "document": try JSONSerialization.jsonObject(with: JSONEncoder.bridge.encode(selected))]
        if sound == "custom", let customSound { request["custom_sound"] = customSound.path }
        var identity = request
        for (name, url) in [("source", document.url), ("cue", sound == "custom" ? customSound : nil)] {
            if let url {
                let values = try url.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey])
                identity[name + "_size"] = values.fileSize
                identity[name + "_modified"] = values.contentModificationDate?.timeIntervalSince1970
            }
        }
        return (try JSONSerialization.data(withJSONObject: identity, options: [.sortedKeys]), request)
    }

    private func cachedAudio(key: Data) -> URL? {
        guard let url = cached[key], FileManager.default.fileExists(atPath: url.path) else { return nil }
        recentKeys.removeAll { $0 == key }; recentKeys.append(key)
        return url
    }

    func cachedAudio(document: ReviewDocument, track: Int, sound: String, customSound: URL?) throws -> URL? {
        let (key, _) = try request(document: document, track: track, sound: sound, customSound: customSound)
        return cachedAudio(key: key)
    }

    func audio(document: ReviewDocument, track: Int, sound: String, customSound: URL?,
               root: URL, python: URL, progress: @escaping @MainActor (String, Double) -> Void) async throws -> URL {
        let (key, baseRequest) = try request(document: document, track: track, sound: sound, customSound: customSound)
        if let url = cachedAudio(key: key) { return url }
        var request = baseRequest
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
            cached[key] = output
            recentKeys.removeAll { $0 == key }; recentKeys.append(key)
            // Retain the three modes for two tracks, plus a little room for recent edits.
            while recentKeys.count > 8 {
                let oldest = recentKeys.removeFirst()
                if let url = cached.removeValue(forKey: oldest) { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
            }
            return output
        } catch {
            try? FileManager.default.removeItem(at: folder)
            throw error
        }
    }
}
