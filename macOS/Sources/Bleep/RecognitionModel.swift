import Foundation

enum VideoLanguage: String, CaseIterable {
    case russian = "ru"
    case english = "en"

    var title: String { self == .russian ? "Русский" : "English" }

    static func selected(defaults: UserDefaults) -> Self {
        Self(rawValue: defaults.string(forKey: "videoLanguage") ?? "") ?? .russian
    }
}

/// Temporary model comparison choice; WhisperKit keeps its pinned Core ML weights.
enum RecognitionModel: String, CaseIterable {
    case largeV3 = "large-v3"
    case turbo = "large-v3-turbo"
    case parakeetV3 = "parakeet-v3"
    case parakeetUltra = "parakeet-ultra"
    case qwen = "qwen3-asr"
    case gigaAM = "gigaam-v3"

    var title: String {
        switch self {
        case .largeV3: "Whisper Large v3"
        case .turbo: "Whisper Large v3 Turbo"
        case .parakeetV3: "Parakeet v3 · Experimental"
        case .parakeetUltra: "Parakeet Ultra · Experimental"
        case .qwen: "Qwen3-ASR 1.7B · Experimental"
        case .gigaAM: "GigaAM v3"
        }
    }

    static func choices(backend: String, language: VideoLanguage = .russian) -> [Self] {
        let candidates: [Self] = backend == "mlx" ? allCases : [.largeV3, .turbo]
        return candidates.filter { language == .russian || $0 != .gigaAM }
    }

    static func engine(model: String, selected: String) -> String {
        guard selected == "mlx" else { return selected }
        switch Self(rawValue: model) {
        case .parakeetV3, .parakeetUltra: return "parakeet-mlx"
        case .qwen: return "mlx-qwen3-asr"
        case .gigaAM: return "gigaam-mps"
        default: return selected
        }
    }

    static func requested(defaults: UserDefaults, backend: String) -> String {
        if backend == "whisperkit" { return Self.turbo.rawValue }
        let model = Self(rawValue: defaults.string(forKey: "recognitionModel") ?? "") ?? .largeV3
        return choices(backend: backend, language: VideoLanguage.selected(defaults: defaults)).contains(model)
            ? model.rawValue : Self.largeV3.rawValue
    }
}
