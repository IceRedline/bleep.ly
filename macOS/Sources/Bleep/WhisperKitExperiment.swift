import Foundation

/// WhisperKit remains experimental, but is included in the single desktop app.
enum WhisperKitExperiment {
    static func backend(defaults: UserDefaults) -> String {
        let selected = defaults.string(forKey: "backend") ?? "faster-whisper"
        let choices = ["faster-whisper", "mlx", "whisperkit"]
        return choices.contains(selected) ? selected : "faster-whisper"
    }

    /// Preserve an earlier Lab opt-in once, then use only the shared backend choice.
    static func migratePreferences(defaults: UserDefaults) {
        if defaults.bool(forKey: "experimentalWhisperKit") {
            defaults.set("whisperkit", forKey: "backend")
        }
        defaults.removeObject(forKey: "experimentalWhisperKit")
        defaults.set(backend(defaults: defaults), forKey: "backend")
    }
    static var helper: URL {
        Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/BleepWhisperKit")
    }
}
