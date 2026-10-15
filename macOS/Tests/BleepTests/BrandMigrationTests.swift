import XCTest
@testable import Bleep

final class BrandMigrationTests: XCTestCase {
    private func fixture() throws -> (URL, UserDefaults) {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("brand-migration-\(UUID())")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let name = "brand-migration-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        addTeardownBlock {
            try? FileManager.default.removeItem(at: root)
            defaults.removePersistentDomain(forName: name)
        }
        return (root, defaults)
    }

    private func write(_ value: String, to file: URL) throws {
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(value.utf8).write(to: file)
    }

    func testMovesModelsReviewBookmarkAndCustomSoundWithPreferencesIntact() throws {
        let (root, defaults) = try fixture()
        let legacy = root.appendingPathComponent(BrandMigration.legacyName)
        let current = root.appendingPathComponent("bleeply")
        for path in ["models/weights.bin", "last-review.json", "last-source.bookmark", "Custom Sounds/id/cue.wav"] {
            try write(path, to: legacy.appendingPathComponent(path))
        }
        defaults.set("id/cue.wav", forKey: "customSoundFile")
        defaults.set("custom", forKey: "censorSound")
        defaults.set(false, forKey: "allowDownloads")
        try BrandMigration.migrate(parent: root, defaults: defaults)
        XCTAssertFalse(FileManager.default.fileExists(atPath: legacy.path))
        for path in ["models/weights.bin", "last-review.json", "last-source.bookmark"] {
            XCTAssertEqual(try String(contentsOf: current.appendingPathComponent(path)), path)
        }
        let cue = try XCTUnwrap(SavedCensorSound(directory: current, defaults: defaults).url)
        XCTAssertEqual(try String(contentsOf: cue), "Custom Sounds/id/cue.wav")
        XCTAssertEqual(defaults.string(forKey: "censorSound"), "custom")
        XCTAssertFalse(defaults.bool(forKey: "allowDownloads"))
    }

    func testMergesMissingFilesWithoutOverwritingNewWorkOrFollowingSymlinks() throws {
        let (root, defaults) = try fixture()
        let legacy = root.appendingPathComponent(BrandMigration.legacyName)
        let current = root.appendingPathComponent("bleeply")
        try write("old", to: legacy.appendingPathComponent("last-review.json"))
        try write("new", to: current.appendingPathComponent("last-review.json"))
        try write("weights", to: legacy.appendingPathComponent("models/weights.bin"))
        try write("other", to: current.appendingPathComponent("models/other.bin"))
        try write("keep", to: root.appendingPathComponent("outside/value"))
        try FileManager.default.createSymbolicLink(at: current.appendingPathComponent("linked"), withDestinationURL: root.appendingPathComponent("outside"))
        try write("do not copy", to: legacy.appendingPathComponent("linked/unwanted"))
        try BrandMigration.migrate(parent: root, defaults: defaults)
        XCTAssertEqual(try String(contentsOf: current.appendingPathComponent("last-review.json")), "new")
        XCTAssertEqual(try String(contentsOf: legacy.appendingPathComponent("last-review.json")), "old")
        XCTAssertEqual(try String(contentsOf: current.appendingPathComponent("models/weights.bin")), "weights")
        XCTAssertEqual(try String(contentsOf: current.appendingPathComponent("models/other.bin")), "other")
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("outside/unwanted").path))
        try FileManager.default.removeItem(at: current.appendingPathComponent("models/weights.bin"))
        try BrandMigration.migrate(parent: root, defaults: defaults)
        XCTAssertFalse(FileManager.default.fileExists(atPath: current.appendingPathComponent("models/weights.bin").path))
    }

    func testFailedMigrationCanRetry() throws {
        let (root, defaults) = try fixture()
        let legacy = root.appendingPathComponent(BrandMigration.legacyName)
        let current = root.appendingPathComponent("bleeply")
        try write("review", to: legacy.appendingPathComponent("last-review.json"))
        try write("blocked", to: current)
        XCTAssertThrowsError(try BrandMigration.migrate(parent: root, defaults: defaults))
        XCTAssertFalse(defaults.bool(forKey: "migratedBleeplyStorage"))
        XCTAssertEqual(try String(contentsOf: legacy.appendingPathComponent("last-review.json")), "review")
        try FileManager.default.removeItem(at: current)
        try BrandMigration.migrate(parent: root, defaults: defaults)
        XCTAssertEqual(try String(contentsOf: current.appendingPathComponent("last-review.json")), "review")
    }

    func testFreshInstallDoesNotCreateStorageUntilNeeded() throws {
        let (root, defaults) = try fixture()
        try BrandMigration.migrate(parent: root, defaults: defaults)
        XCTAssertTrue(defaults.bool(forKey: "migratedBleeplyStorage"))
        XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: root.path).isEmpty)
    }
}
