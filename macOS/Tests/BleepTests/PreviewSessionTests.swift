import XCTest
import Darwin
@testable import Bleep

final class PreviewSessionTests: XCTestCase {
    private func root() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("cache-tests-\(UUID())")
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    func testActiveSessionsSurviveCleanupAndLastLeaseDeletesFiles() throws {
        let root = try root()
        var session: PreviewSession? = try PreviewSession(temporaryDirectory: root)
        let path = try XCTUnwrap(session?.directory)
        try Data([1, 2, 3]).write(to: path.appendingPathComponent("audio.wav"))
        PreviewSession.cleanAbandoned(in: root)
        XCTAssertTrue(FileManager.default.fileExists(atPath: path.path))
        var worker = session
        session = nil
        XCTAssertTrue(FileManager.default.fileExists(atPath: path.path))
        XCTAssertNotNil(worker)
        worker = nil
        XCTAssertFalse(FileManager.default.fileExists(atPath: path.path))
    }

    func testAbandonedSessionsRemovedButRecentLegacyAndUnrelatedFoldersPreserved() throws {
        let root = try root()
        for prefix in ["bleep-preview-", "bleep-request-"] {
            let abandoned = root.appendingPathComponent(prefix + UUID().uuidString)
            try FileManager.default.createDirectory(at: abandoned, withIntermediateDirectories: true)
            try Data().write(to: abandoned.appendingPathComponent(".owner-lock"))
            PreviewSession.cleanAbandoned(in: root)
            XCTAssertFalse(FileManager.default.fileExists(atPath: abandoned.path))
        }
        let recent = root.appendingPathComponent("bleep-preview-\(UUID())")
        let old = root.appendingPathComponent("bleep-preview-\(UUID())")
        let other = root.appendingPathComponent("source-videos")
        for folder in [recent, old, other] {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        }
        try FileManager.default.setAttributes([.modificationDate: Date(timeIntervalSinceNow: -172800)], ofItemAtPath: old.path)
        PreviewSession.cleanAbandoned(in: root)
        XCTAssertFalse(FileManager.default.fileExists(atPath: old.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: recent.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: other.path))
    }

    func testSymlinksAreNeverTraversed() throws {
        let root = try root()
        let recording = root.appendingPathComponent("recording.mov")
        try Data([1, 2, 3]).write(to: recording)
        let link = root.appendingPathComponent("bleep-preview-\(UUID())")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: root)
        PreviewSession.cleanAbandoned(in: root)
        XCTAssertEqual(try Data(contentsOf: recording), Data([1, 2, 3]))
    }
}
