import Foundation
import Darwin

/// Keep a Powerbox/bookmark grant alive while players and workers use a file.
final class SecurityScopedFile {
    let url: URL
    private let accessing: Bool

    init(_ url: URL) {
        self.url = url
        accessing = url.startAccessingSecurityScopedResource()
    }

    deinit { if accessing { url.stopAccessingSecurityScopedResource() } }
}

enum SandboxFiles {
    static var enabled: Bool { Bundle.main.object(forInfoDictionaryKey: "BleepAppSandbox") as? Bool == true }

    static func saveBookmark(for url: URL, to destination: URL) throws {
        let bookmark = try url.bookmarkData(options: [.withSecurityScope, .securityScopeAllowOnlyReadAccess],
                                            includingResourceValuesForKeys: nil, relativeTo: nil)
        try bookmark.write(to: destination, options: .atomic)
    }

    static func restoreBookmark(from bookmark: URL, expected: URL) throws -> SecurityScopedFile {
        var stale = false
        let url = try URL(resolvingBookmarkData: Data(contentsOf: bookmark), options: [.withSecurityScope, .withoutUI],
                          relativeTo: nil, bookmarkDataIsStale: &stale)
        let access = SecurityScopedFile(url)
        guard url.standardizedFileURL.path == expected.standardizedFileURL.path else {
            throw BridgeFailure(message: "The original media has moved. Open it again.")
        }
        if stale { try saveBookmark(for: url, to: bookmark) }
        return access
    }

    /// A Save panel grants one destination, not permission to create sibling files.
    /// Render in the container first, then exclusively create that destination.
    static func publish(_ source: URL, to destination: URL) throws {
        try Task.checkCancellation()
        let input = try FileHandle(forReadingFrom: source)
        defer { try? input.close() }
        let fd = Darwin.open(destination.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
        guard fd >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        let output = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        var complete = false
        defer {
            if !complete {
                // Remove only the file we created; a concurrent replacement is never ours.
                var opened = stat(), current = stat()
                if fstat(fd, &opened) == 0, lstat(destination.path, &current) == 0,
                   opened.st_dev == current.st_dev, opened.st_ino == current.st_ino {
                    unlink(destination.path)
                }
            }
            try? output.close()
        }
        while let bytes = try input.read(upToCount: 1024 * 1024), !bytes.isEmpty {
            try Task.checkCancellation()
            try output.write(contentsOf: bytes)
        }
        try Task.checkCancellation()
        try output.synchronize()
        complete = true
    }
}
