import XCTest
@testable import Bleep

@MainActor
final class ReviewListTests: XCTestCase {
    func testUncheckedWordsStayInFlaggedListAndSurviveDraftRoundTrip() throws {
        let suite = "review-list-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(suite)
        defer { try? FileManager.default.removeItem(at: folder) }
        let model = AppModel(defaults: defaults, supportDirectory: folder)
        let flagged = ReviewWord(word: "flagged", start: 1, end: 2, profane: true, muteStart: 1.2, muteEnd: 1.6)
        let clean = ReviewWord(word: "clean", start: 3, end: 4, profane: false, muteStart: 3.2, muteEnd: 3.6)
        let other = ReviewWord(word: "other", start: 2, end: 3, profane: true, muteStart: 2.2, muteEnd: 2.6, audioTrack: 1)
        model.document = ReviewDocument(source: "/unused.mov", fingerprint: "test", duration: 5,
                                        hasVideo: true, audioCount: 2, words: [flagged, clean, other])
        XCTAssertEqual(model.visibleWords.map(\.id), [flagged.id])
        model.toggle(flagged)
        XCTAssertEqual(model.visibleWords.map(\.id), [flagged.id])
        XCTAssertFalse(try XCTUnwrap(model.visibleWords.first).profane)
        XCTAssertEqual(model.document?.reviewCount, 2)
        XCTAssertEqual(model.document?.count, 1)
        XCTAssertEqual(model.visibleWords.first?.muteStart, 1.2)
        XCTAssertEqual(model.visibleWords.first?.muteEnd, 1.6)
        model.toggle(try XCTUnwrap(model.visibleWords.first))
        XCTAssertTrue(try XCTUnwrap(model.visibleWords.first).profane)
        model.undo()
        XCTAssertFalse(try XCTUnwrap(model.visibleWords.first).profane)

        // Manually selected transcript words must also remain available after
        // switching back to Flagged and turning their censorship off.
        model.showAllWords = true
        model.toggle(clean)
        model.showAllWords = false
        model.toggle(clean)
        XCTAssertEqual(model.visibleWords.map(\.id), [flagged.id, clean.id])
        XCTAssertTrue(model.visibleWords.allSatisfy { !$0.profane })
        model.search = "clean"
        XCTAssertEqual(model.visibleWords.map(\.id), [clean.id])
        model.search = ""
        model.selectedAudioTrack = 1
        XCTAssertEqual(model.visibleWords.map(\.id), [other.id])

        let saved = try Data(contentsOf: folder.appendingPathComponent("last-review.json"))
        let reopened = AppModel(defaults: defaults, supportDirectory: folder)
        reopened.document = try JSONDecoder.bridge.decode(ReviewDocument.self, from: saved)
        XCTAssertEqual(reopened.visibleWords.map(\.word), ["flagged", "clean"])
        XCTAssertTrue(reopened.visibleWords.allSatisfy { !$0.profane })
        reopened.toggle(try XCTUnwrap(reopened.visibleWords.first))
        XCTAssertTrue(try XCTUnwrap(reopened.visibleWords.first).profane)
        XCTAssertNil(reopened.error)
    }
}
