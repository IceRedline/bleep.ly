import Foundation

enum ModelDownloadPermission {
    case ask, allowed, denied

    static func selected(defaults: UserDefaults) -> Self {
        // Preserve prior explicit permission, including preferences from older apps.
        if defaults.bool(forKey: "allowDownloads") { return .allowed }
        return defaults.bool(forKey: "modelDownloadConsentAnswered") ? .denied : .ask
    }

    static func save(_ allowed: Bool, defaults: UserDefaults) {
        defaults.set(allowed, forKey: "allowDownloads")
        defaults.set(true, forKey: "modelDownloadConsentAnswered")
    }
}
