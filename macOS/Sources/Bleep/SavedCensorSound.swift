import Foundation

/// Keep a private copy so a moved/deleted source sound remains available next launch.
struct SavedCensorSound {
    let directory: URL
    let defaults: UserDefaults
    private var root: URL { directory.appendingPathComponent("Custom Sounds", isDirectory: true) }

    var url: URL? {
        guard let relative = defaults.string(forKey: "customSoundFile") else { return nil }
        let candidate = root.appendingPathComponent(relative).standardizedFileURL
        guard candidate.path.hasPrefix(root.standardizedFileURL.path + "/"),
              FileManager.default.isReadableFile(atPath: candidate.path) else { return nil }
        return candidate
    }

    func save(_ source: URL) throws -> URL {
        let access = source.startAccessingSecurityScopedResource()
        defer { if access { source.stopAccessingSecurityScopedResource() } }
        guard try source.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile == true else {
            throw BridgeFailure(message: "Choose an audio file for the custom censor sound.")
        }
        let previous = url
        let folder = root.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let destination = folder.appendingPathComponent(source.lastPathComponent)
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try FileManager.default.copyItem(at: source, to: destination)
            // Publish only after a complete copy. A failed replacement keeps the saved choice.
            defaults.set(folder.lastPathComponent + "/" + source.lastPathComponent, forKey: "customSoundFile")
        } catch {
            try? FileManager.default.removeItem(at: folder)
            throw error
        }
        if let previous, previous.deletingLastPathComponent().deletingLastPathComponent().standardizedFileURL == root.standardizedFileURL {
            try? FileManager.default.removeItem(at: previous.deletingLastPathComponent())
        }
        return destination
    }
}
