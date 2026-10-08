import XCTest
@testable import Bleep

@MainActor
final class PlaybackFollowTests: XCTestCase {
    func testFollowRespectsIntervalsTracksEditsAndBackwardSeeking() throws {
        let suite = "follow-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let model = AppModel(defaults: defaults)
        let first = ReviewWord(word: "first", start: 1, end: 1.5, profane: true, muteStart: 1.2, muteEnd: 1.4, audioTrack: 0)
        let later = ReviewWord(word: "later", start: 4, end: 4.5, profane: true, muteStart: 4, muteEnd: 4.5, audioTrack: 0)
        let clean = ReviewWord(word: "clean", start: 2, end: 2.5, profane: false, muteStart: 2, muteEnd: 2.5, audioTrack: 0)
        let other = ReviewWord(word: "other", start: 3, end: 3.5, profane: true, muteStart: 3, muteEnd: 3.5, audioTrack: 1)
        model.document = ReviewDocument(source: "/unused.mov", fingerprint: "test", duration: 10, hasVideo: true,
            audioCount: 2, words: [later, clean, other, first])
        model.followPlayback(at: 1.1)
        XCTAssertNil(model.selected)
        model.followPlayback(at: 1.2)
        XCTAssertEqual(model.selected, first.id)
        model.followPlayback(at: 3.9)
        XCTAssertEqual(model.selected, first.id, "Keep the last censored word through clean words and other tracks")
        model.followPlayback(at: 5)
        XCTAssertEqual(model.selected, later.id)
        model.followPlayback(at: 2)
        XCTAssertEqual(model.selected, first.id, "Backward seeking must reset the followed word")
        model.document?.words[0].profane = false
        model.followPlayback(at: 5)
        XCTAssertEqual(model.selected, first.id, "Unchecked words must leave the follow index")
        model.selectedAudioTrack = 1
        model.followPlayback(at: 5)
        XCTAssertEqual(model.selected, other.id)
        model.document = nil
        model.followPlayback(at: 5)
        XCTAssertNil(model.selected)
    }
}
