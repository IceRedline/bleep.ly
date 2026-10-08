import Foundation

struct ReviewWord: Codable, Identifiable, Equatable {
    var id: UUID = UUID()
    var word: String
    var start: Double
    var end: Double
    var profane: Bool
    var muteStart: Double
    var muteEnd: Double

    enum CodingKeys: String, CodingKey { case word, start, end, profane, muteStart, muteEnd }
}

struct ReviewDocument: Codable, Equatable {
    var source: String
    var fingerprint: String
    var duration: Double
    var hasVideo: Bool
    var audioStream: Int?
    var audioCount: Int
    var words: [ReviewWord]
    var censorStyle: String? // Absent in reviews saved before this setting existed.

    var count: Int { words.filter(\.profane).count }
    var url: URL { URL(fileURLWithPath: source) }

    func validateInterval(start: Double, end: Double) -> Bool {
        start.isFinite && end.isFinite && start >= 0 && end > start && end <= duration
    }
}

extension JSONDecoder {
    static var bridge: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}

extension JSONEncoder {
    static var bridge: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }
}

func clockText(_ seconds: Double) -> String {
    guard seconds.isFinite else { return "0:00" }
    let value = max(0, Int(seconds))
    return value >= 3600
        ? String(format: "%d:%02d:%02d", value / 3600, value / 60 % 60, value % 60)
        : String(format: "%d:%02d", value / 60, value % 60)
}

struct BridgeFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

enum WorkflowMode: String, CaseIterable {
    case fast, advanced
}

extension ReviewDocument {
    /// Match supported source containers; use MKV for other video formats.
    /// The renderer still publishes atomically and refuses a racing overwrite.
    func automaticOutputURL() -> URL {
        let sourceExtension = url.pathExtension.lowercased()
        let ext = hasVideo ? (["mov", "mp4", "mkv"].contains(sourceExtension) ? sourceExtension : "mkv") : "wav"
        let stem = url.deletingPathExtension().lastPathComponent + "_censored"
        let folder = url.deletingLastPathComponent()
        var counter = 1
        while true {
            let name = stem + (counter == 1 ? "" : "_\(counter)") + "." + ext
            let candidate = folder.appendingPathComponent(name)
            if (try? FileManager.default.attributesOfItem(atPath: candidate.path)) == nil { return candidate }
            counter += 1
        }
    }
}
