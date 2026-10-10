import XCTest
@testable import Bleep

final class LegacyLabMigrationTests: XCTestCase {
    private func preferences() throws -> UserDefaults {
        let name = "migration-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        addTeardownBlock { defaults.removePersistentDomain(forName: name) }
        return defaults
    }
    private func folder() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("lab-migration-\(UUID())")
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }
    func testImportsMissingLabPreferencesReviewAndPrivateSoundOnce() throws {
        let root = try folder(), current = try preferences(), legacy = try preferences()
        let lab = root.appendingPathComponent("Lab"), normal = root.appendingPathComponent("Normal")
        let cue = root.appendingPathComponent("cue.wav")
        try Data([1, 2, 3]).write(to: cue)
        let labCue = try SavedCensorSound(directory: lab, defaults: legacy).save(cue)
        let review = Data("review".utf8)
        try review.write(to: lab.appendingPathComponent("last-review.json"))
        legacy.set("whisperkit", forKey: "backend")
        legacy.set("custom", forKey: "censorSound")
        legacy.set(true, forKey: "allowDownloads")
        try LegacyLabMigration.migrate(defaults: current, directory: normal, legacyDefaults: legacy, legacyDirectory: lab)
        XCTAssertEqual(current.string(forKey: "backend"), "whisperkit")
        XCTAssertTrue(current.bool(forKey: "allowDownloads"))
        XCTAssertEqual(current.string(forKey: "censorSound"), "custom")
        let copy = try XCTUnwrap(SavedCensorSound(directory: normal, defaults: current).url)
        XCTAssertNotEqual(copy, labCue)
        XCTAssertEqual(try Data(contentsOf: copy), try Data(contentsOf: labCue))
        XCTAssertEqual(try Data(contentsOf: normal.appendingPathComponent("last-review.json")), review)
        XCTAssertEqual(try Data(contentsOf: lab.appendingPathComponent("last-review.json")), review)
        current.removeObject(forKey: "backend")
        try LegacyLabMigration.migrate(defaults: current, directory: normal, legacyDefaults: legacy, legacyDirectory: lab)
        XCTAssertNil(current.object(forKey: "backend"), "Do not reimport preferences after the user changes them")
        XCTAssertEqual(SavedCensorSound(directory: normal, defaults: current).url, copy)
    }
    func testExistingStandardDataWinsIncludingFalseDownloadPreference() throws {
        let root = try folder(), current = try preferences(), legacy = try preferences()
        let cue = root.appendingPathComponent("cue.wav")
        try Data([1]).write(to: cue)
        let normal = root.appendingPathComponent("Normal"), lab = root.appendingPathComponent("Lab")
        let existing = try SavedCensorSound(directory: normal, defaults: current).save(cue)
        _ = try SavedCensorSound(directory: lab, defaults: legacy).save(cue)
        try Data("regular".utf8).write(to: normal.appendingPathComponent("last-review.json"))
        try Data("lab".utf8).write(to: lab.appendingPathComponent("last-review.json"))
        current.set("mlx", forKey: "backend"); current.set(false, forKey: "allowDownloads")
        current.set("silence", forKey: "censorSound")
        legacy.set(true, forKey: "experimentalWhisperKit"); legacy.set(true, forKey: "allowDownloads")
        legacy.set("custom", forKey: "censorSound")
        try LegacyLabMigration.migrate(defaults: current, directory: normal, legacyDefaults: legacy, legacyDirectory: lab)
        XCTAssertEqual(current.string(forKey: "backend"), "mlx")
        XCTAssertFalse(current.bool(forKey: "allowDownloads"))
        XCTAssertEqual(current.string(forKey: "censorSound"), "silence")
        XCTAssertEqual(SavedCensorSound(directory: normal, defaults: current).url, existing)
        XCTAssertEqual(try Data(contentsOf: normal.appendingPathComponent("last-review.json")), Data("regular".utf8))
    }
    func testFailedCopyCanRetryWithoutMarkingMigrationComplete() throws {
        let root = try folder(), current = try preferences(), legacy = try preferences()
        let target = root.appendingPathComponent("not-a-directory")
        try Data().write(to: target)
        try Data("review".utf8).write(to: root.appendingPathComponent("last-review.json"))
        XCTAssertThrowsError(try LegacyLabMigration.migrate(defaults: current, directory: target,
            legacyDefaults: legacy, legacyDirectory: root))
        XCTAssertFalse(current.bool(forKey: "importedLegacyLab"))
        try FileManager.default.removeItem(at: target)
        try LegacyLabMigration.migrate(defaults: current, directory: target, legacyDefaults: legacy, legacyDirectory: root)
        XCTAssertTrue(current.bool(forKey: "importedLegacyLab"))
    }
}
