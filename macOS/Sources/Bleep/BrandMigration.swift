import Foundation

/// Historical paths are compatibility inputs, never the name of the current app.
enum BrandMigration {
    static let legacyName = "bleep.ly"

    static func migrate(parent: URL, defaults: UserDefaults) throws {
        guard !defaults.bool(forKey: "migratedBleeplyStorage") else { return }
        let files = FileManager.default
        let source = parent.appendingPathComponent(legacyName, isDirectory: true)
        let destination = parent.appendingPathComponent("bleeply", isDirectory: true)
        if files.fileExists(atPath: source.path) {
            if !files.fileExists(atPath: destination.path) {
                // Rename on the same volume instead of copying downloaded model weights.
                try files.moveItem(at: source, to: destination)
            } else {
                // A partial migration can be retried; newer saved work always wins.
                try copyMissing(from: source, to: destination)
            }
        }
        defaults.set(true, forKey: "migratedBleeplyStorage")
    }

    private static func copyMissing(from source: URL, to destination: URL) throws {
        let files = FileManager.default
        for child in try files.contentsOfDirectory(at: source, includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey]) {
            let target = destination.appendingPathComponent(child.lastPathComponent)
            if !files.fileExists(atPath: target.path) {
                try files.copyItem(at: child, to: target)
            } else {
                let original = try child.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
                let current = try target.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
                if original.isDirectory == true, original.isSymbolicLink != true,
                   current.isDirectory == true, current.isSymbolicLink != true {
                    try copyMissing(from: child, to: target)
                }
            }
        }
    }
}
