import XCTest
@testable import Bleep

final class ProgressAndContextTests: XCTestCase {
    func testSparseProgressMovesButOnlyWorkerCanComplete() {
        var progress = StageProgress()
        progress.duration = 100
        progress.report("Track 1/2 · Recognizing speech", fraction: 0, now: 10)
        progress.advance(now: 15)
        XCTAssertGreaterThan(progress.displayed, 0)
        XCTAssertTrue(progress.estimated)
        let displayed = progress.displayed
        progress.report("Track 1/2 · Recognizing speech", fraction: 0.01, now: 16)
        XCTAssertGreaterThanOrEqual(progress.displayed, displayed)
        progress.report("Track 1/2 · Recognizing speech", fraction: 0.2, now: 20)
        progress.advance(now: 50)
        XCTAssertGreaterThan(progress.displayed, 0.2)
        progress.advance(now: 10000)
        XCTAssertLessThan(progress.displayed, 1)
        progress.report("Track 1/2 · Recognizing speech", fraction: 1, now: 10001)
        XCTAssertEqual(progress.displayed, 1)
        XCTAssertFalse(progress.estimated)
        progress.report("Track 2/2 · Loading model", fraction: 0, now: 10002)
        progress.advance(now: 10100)
        XCTAssertEqual(progress.displayed, 0)
        XCTAssertFalse(progress.estimated)
        progress.report("Exporting video", fraction: 0, now: 10200)
        progress.advance(now: 10201)
        XCTAssertGreaterThan(progress.displayed, 0)
    }

    func testContextIsWordPlusPointTwoAtEachEdge() {
        var word = ReviewWord(word: "test", start: 1, end: 1.3, profane: true, muteStart: 1.1, muteEnd: 1.2)
        XCTAssertEqual(word.contextRange(duration: 3).lowerBound, 0.8, accuracy: 0.0001)
        XCTAssertEqual(word.contextRange(duration: 3).upperBound, 1.5, accuracy: 0.0001)
        word.start = 0.1; word.end = 0.3
        XCTAssertEqual(word.contextRange(duration: 3), 0...0.5)
        word.start = 2.6; word.end = 2.9
        XCTAssertEqual(word.contextRange(duration: 3).upperBound, 3)
    }
}
