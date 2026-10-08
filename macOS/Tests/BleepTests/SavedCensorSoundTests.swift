import XCTest
@testable import Bleep

@MainActor
final class SavedCensorSoundTests: XCTestCase {
    func testSoundAndSelectionSurviveRelaunchAndOriginalRemoval() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("saved-sound-test-\(UUID())")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let suite = "saved-sound-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let support = folder.appendingPathComponent("support")
        let original = folder.appendingPathComponent("My beep.wav")
        // Storage preserves bytes; playback/render tests separately exercise audio validity.
        try Data([1, 2, 3, 4]).write(to: original)
        let first = AppModel(defaults: defaults, supportDirectory: support)
        first.setSound(original)
        let saved = try XCTUnwrap(first.customSound)
        XCTAssertNotEqual(saved, original)
        XCTAssertEqual(saved.lastPathComponent, original.lastPathComponent)
        try FileManager.default.removeItem(at: original)
        let relaunched = AppModel(defaults: defaults, supportDirectory: support)
        XCTAssertEqual(relaunched.sound, "custom")
        XCTAssertEqual(relaunched.customSound, saved)
        XCTAssertEqual(try Data(contentsOf: XCTUnwrap(relaunched.customSound)), Data([1, 2, 3, 4]))
        relaunched.sound = "silence"
        let again = AppModel(defaults: defaults, supportDirectory: support)
        XCTAssertEqual(again.sound, "silence")
        XCTAssertEqual(again.customSound, saved, "Choosing another mode must not discard the custom sound")
        again.setSound(original) // Failed replacement preserves the last working choice.
        XCTAssertNotNil(again.error)
        XCTAssertEqual(again.sound, "silence")
        XCTAssertEqual(again.customSound, saved)
        try Data([5, 6]).write(to: original)
        again.setSound(original)
        XCTAssertNil(again.error)
        let replacement = try XCTUnwrap(again.customSound)
        XCTAssertEqual(try Data(contentsOf: replacement), Data([5, 6]))
        XCTAssertFalse(FileManager.default.fileExists(atPath: saved.path))
        let latest = AppModel(defaults: defaults, supportDirectory: support)
        XCTAssertEqual(latest.sound, "custom")
        XCTAssertEqual(latest.customSound, replacement)
        try FileManager.default.removeItem(at: replacement)
        let missing = AppModel(defaults: defaults, supportDirectory: support)
        XCTAssertNil(missing.customSound)
        XCTAssertEqual(missing.sound, "beep")
        XCTAssertNotNil(missing.error)
        let recovered = AppModel(defaults: defaults, supportDirectory: support)
        XCTAssertEqual(recovered.sound, "beep")
        XCTAssertNil(recovered.error)
    }
}
