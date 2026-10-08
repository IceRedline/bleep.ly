import Foundation

/// The standard bundle omits the helper and disables this capability flag.
/// A stale preference cannot turn the experiment on in a normal release.
enum WhisperKitExperiment {
    static var available: Bool {
        Bundle.main.object(forInfoDictionaryKey: "BleepWhisperKitExperiment") as? Bool == true
    }
    static func backend(defaults: UserDefaults, available: Bool = Self.available) -> String {
        let selected = defaults.string(forKey: "backend") ?? "faster-whisper"
        let choices = available ? ["faster-whisper", "mlx", "whisperkit"] : ["faster-whisper", "mlx"]
        return choices.contains(selected) ? selected : "faster-whisper"
    }

    /// Preserve an earlier Lab opt-in once, then use only the shared backend choice.
    static func migratePreferences(defaults: UserDefaults, available: Bool = Self.available) {
        if available && defaults.bool(forKey: "experimentalWhisperKit") {
            defaults.set("whisperkit", forKey: "backend")
        }
        defaults.removeObject(forKey: "experimentalWhisperKit")
        defaults.set(backend(defaults: defaults, available: available), forKey: "backend")
    }
    static var helper: URL {
        Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/BleepWhisperKit")
    }
}
