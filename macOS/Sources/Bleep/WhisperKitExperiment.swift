import Foundation

/// The standard bundle omits the helper and disables this capability flag.
/// A stale preference cannot turn the experiment on in a normal release.
enum WhisperKitExperiment {
    static var available: Bool {
        Bundle.main.object(forInfoDictionaryKey: "BleepWhisperKitExperiment") as? Bool == true
    }
    static func enabled(defaults: UserDefaults, available: Bool = Self.available) -> Bool {
        available && defaults.bool(forKey: "experimentalWhisperKit")
    }
    static var helper: URL {
        Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/BleepWhisperKit")
    }
}
