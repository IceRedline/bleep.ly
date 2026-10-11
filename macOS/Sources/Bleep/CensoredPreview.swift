import Foundation

/// Reuse decoded source audio and patch immutable previews after review edits.
/// Video always stays in the original file.
@MainActor
final class CensoredPreview {
    private var bridge: PythonBridge?
    private var cached: [Data: URL] = [:]
    private var recentKeys: [Data] = []
    private var latest: [Data: URL] = [:]
    private var sessionDirectory: URL?

    func cancel() { bridge?.cancel() }

    func clear() {
        cancel()
        for url in cached.values { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        if let sessionDirectory { try? FileManager.default.removeItem(at: sessionDirectory) }
        sessionDirectory = nil
        cached.removeAll(); recentKeys.removeAll(); latest.removeAll()
    }

    private func request(document: ReviewDocument, track: Int, sound: String, customSound: URL?) throws -> (Data, Data, [String: Any]) {
        var selected = document
        selected.tracks = document.audioTracks.filter { $0.index == track }
        selected.words = document.words.filter { ($0.audioTrack ?? document.audioStream ?? 0) == track }
        selected.audioStream = track
        var request: [String: Any] = ["operation": "preview", "format": "audio", "sound": sound,
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
        var context = identity
        selected.words = []
        context["document"] = try JSONSerialization.jsonObject(with: JSONEncoder.bridge.encode(selected))
        return (try JSONSerialization.data(withJSONObject: identity, options: [.sortedKeys]),
                try JSONSerialization.data(withJSONObject: context, options: [.sortedKeys]), request)
    }

    private func cachedAudio(key: Data) -> URL? {
        guard let url = cached[key], FileManager.default.fileExists(atPath: url.path) else { return nil }
        recentKeys.removeAll { $0 == key }; recentKeys.append(key)
        return url
    }

    func cachedAudio(document: ReviewDocument, track: Int, sound: String, customSound: URL?) throws -> URL? {
        let (key, _, _) = try request(document: document, track: track, sound: sound, customSound: customSound)
        return cachedAudio(key: key)
    }

    func audio(document: ReviewDocument, track: Int, sound: String, customSound: URL?,
               root: URL, python: URL, progress: @escaping @MainActor (String, Double) -> Void) async throws -> URL {
        let (key, contextKey, baseRequest) = try request(document: document, track: track, sound: sound, customSound: customSound)
        if let url = cachedAudio(key: key) { return url }
        var request = baseRequest
        let session = sessionDirectory ?? FileManager.default.temporaryDirectory.appendingPathComponent("bleep-preview-\(UUID())")
        sessionDirectory = session
        let folder = session.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let output = folder.appendingPathComponent("censored.wav")
        request["output"] = output.path
        request["preview_cache"] = session.appendingPathComponent("audio").path
        if let previous = latest[contextKey], FileManager.default.fileExists(atPath: previous.path) {
            request["previous_output"] = previous.path
        }
        let worker = PythonBridge()
        bridge = worker
        defer { if bridge === worker { bridge = nil } }
        do {
            try Task.checkCancellation()
            _ = try await worker.run(root: root, python: python, request: request, progress: progress)
            try Task.checkCancellation()
            cached[key] = output
            latest[contextKey] = output
            recentKeys.removeAll { $0 == key }; recentKeys.append(key)
            // Retain the three modes for two tracks, plus a little room for recent edits.
            while recentKeys.count > 8 {
                let oldest = recentKeys.removeFirst()
                if let url = cached.removeValue(forKey: oldest) { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
            }
            return output
        } catch {
            try? FileManager.default.removeItem(at: folder)
            if sessionDirectory != session { try? FileManager.default.removeItem(at: session) }
            throw error
        }
    }
}
