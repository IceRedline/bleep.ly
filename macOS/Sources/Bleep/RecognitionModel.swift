import Foundation

/// Temporary model comparison choice; WhisperKit keeps its pinned Core ML weights.
enum RecognitionModel: String, CaseIterable {
    case largeV3 = "large-v3"
    case turbo = "large-v3-turbo"

    static func requested(defaults: UserDefaults, backend: String) -> String {
        if backend == "whisperkit" { return Self.turbo.rawValue }
        return Self(rawValue: defaults.string(forKey: "recognitionModel") ?? "")?.rawValue
            ?? Self.largeV3.rawValue
    }
}
