import XCTest
@testable import Bleep

final class ReviewTests: XCTestCase {
    func testBridgeDecodesAndRoundTripsExplicitMuteIntervals() throws {
        let payload = Data("""
        {"version":1,"event":"result","source":"/tmp/видео.mov","fingerprint":"42:99",
        "duration":12.5,"has_video":true,"audio_stream":null,"audio_count":1,
        "words":[{"word":"test","start":1,"end":2,"profane":true,"mute_start":1.3,"mute_end":1.6}]}
        """.utf8)
        let document = try JSONDecoder.bridge.decode(ReviewDocument.self, from: payload)
        XCTAssertTrue(document.hasVideo)
        XCTAssertEqual(document.count, 1)
        XCTAssertEqual(document.words[0].muteStart, 1.3)
        let data = try JSONEncoder.bridge.encode(document)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let words = try XCTUnwrap(object["words"] as? [[String: Any]])
        XCTAssertEqual(words[0]["mute_end"] as? Double, 1.6)
        XCTAssertEqual(object["has_video"] as? Bool, true)
        XCTAssertNotNil(try JSONDecoder.bridge.decode(ReviewDocument.self, from: data))
    }
    func testRejectsInvalidManualIntervals() {
        let document = ReviewDocument(source: "", fingerprint: "", duration: 5, hasVideo: false, audioCount: 1, words: [])
        XCTAssertTrue(document.validateInterval(start: 0, end: 5))
        for (start, end) in [(Double.nan, 1), (0, Double.infinity), (-1, 1), (2, 1), (1, 1), (4, 6)] {
            XCTAssertFalse(document.validateInterval(start: start, end: end))
        }
    }
}
