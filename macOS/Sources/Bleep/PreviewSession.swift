import Foundation
import Darwin

/// A lease keeps another app instance's cleanup away from live preview audio.
final class PreviewSession {
    enum Kind: String { case preview = "bleep-preview-", request = "bleep-request-" }
    let directory: URL
    private var descriptor: Int32 = -1

    init(temporaryDirectory: URL = FileManager.default.temporaryDirectory, kind: Kind = .preview) throws {
        Self.cleanAbandoned(in: temporaryDirectory)
        directory = temporaryDirectory.appendingPathComponent("\(kind.rawValue)\(UUID())")
        // Publish the directory only after taking the lease, so another instance
        // cannot collect it in the gap between creating the marker and locking it.
        let staging = temporaryDirectory.appendingPathComponent(".bleep-session-\(UUID())")
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
        descriptor = Darwin.open(staging.appendingPathComponent(".owner-lock").path,
                                 O_CREAT | O_RDWR | O_NOFOLLOW, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else {
            try? FileManager.default.removeItem(at: staging)
            throw BridgeFailure(message: "Could not reserve temporary preview storage.")
        }
        guard flock(descriptor, LOCK_SH | LOCK_NB) == 0 else {
            close(descriptor); descriptor = -1
            try? FileManager.default.removeItem(at: staging)
            throw BridgeFailure(message: "Temporary preview storage is in use.")
        }
        do { try FileManager.default.moveItem(at: staging, to: directory) }
        catch {
            close(descriptor); descriptor = -1
            try? FileManager.default.removeItem(at: staging)
            throw error
        }
    }

    deinit {
        try? FileManager.default.removeItem(at: directory)
        if descriptor >= 0 { close(descriptor) }
    }

    static func cleanAbandoned(in root: URL = FileManager.default.temporaryDirectory, now: Date = Date()) {
        let manager = FileManager.default
        guard let entries = try? manager.contentsOfDirectory(at: root,
            includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey, .contentModificationDateKey]) else { return }
        for folder in entries {
            guard let prefix = [Kind.preview.rawValue, Kind.request.rawValue].first(where: { folder.lastPathComponent.hasPrefix($0) }),
                  UUID(uuidString: String(folder.lastPathComponent.dropFirst(prefix.count))) != nil,
                  let values = try? folder.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey, .contentModificationDateKey]),
                  values.isDirectory == true, values.isSymbolicLink != true else { continue }
            let marker = folder.appendingPathComponent(".owner-lock")
            if !manager.fileExists(atPath: marker.path) {
                // Legacy sessions had no lease. Leave recent folders alone.
                guard let modified = values.contentModificationDate, now.timeIntervalSince(modified) > 86400 else { continue }
            }
            let descriptor = Darwin.open(marker.path, O_CREAT | O_RDWR | O_NOFOLLOW, S_IRUSR | S_IWUSR)
            guard descriptor >= 0 else { continue }
            if flock(descriptor, LOCK_EX | LOCK_NB) == 0 {
                try? manager.removeItem(at: folder)
            }
            close(descriptor)
        }
    }
}
