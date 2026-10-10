import Foundation

/// Fill gaps in the standard app once, without overwriting either app's saved work.
enum LegacyLabMigration {
    static func migrate(defaults: UserDefaults, directory: URL,
                        legacyDefaults: UserDefaults, legacyDirectory: URL) throws {
        guard !defaults.bool(forKey: "importedLegacyLab") else { return }
        let files = FileManager.default
        let review = directory.appendingPathComponent("last-review.json")
        let legacyReview = legacyDirectory.appendingPathComponent("last-review.json")
        if !files.fileExists(atPath: review.path), files.fileExists(atPath: legacyReview.path) {
            try files.createDirectory(at: directory, withIntermediateDirectories: true)
            try files.copyItem(at: legacyReview, to: review)
        }
        if defaults.object(forKey: "customSoundFile") == nil,
           let cue = SavedCensorSound(directory: legacyDirectory, defaults: legacyDefaults).url {
            _ = try SavedCensorSound(directory: directory, defaults: defaults).save(cue)
        }
        for key in ["projectRoot", "pythonPath", "backend", "allowDownloads", "censorStyle", "workflowMode", "censorSound"] {
            guard defaults.object(forKey: key) == nil else { continue }
            if key == "backend", legacyDefaults.bool(forKey: "experimentalWhisperKit") {
                defaults.set("whisperkit", forKey: key)
            } else if let value = legacyDefaults.object(forKey: key) {
                defaults.set(value, forKey: key)
            }
        }
        defaults.set(true, forKey: "importedLegacyLab")
    }
}
