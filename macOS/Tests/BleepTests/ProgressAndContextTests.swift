import XCTest
import SwiftUI
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

    func testReadingMediaStaysIndeterminateAndEstimatedStageLabelIsStable() {
        var progress = StageProgress()
        for value in [0.0, 0.2, 0.7, 1.0] {
            progress.report("Track 2/2 · Reading media", fraction: value, now: value)
            progress.advance(now: value + 1)
            XCTAssertEqual(progress.displayed, 0)
        }
        progress.report("Recognizing speech", fraction: 0, now: 10)
        progress.advance(now: 12)
        XCTAssertTrue(progress.estimated)
        XCTAssertTrue(StageProgress.usesEstimates(progress.stage))
        progress.report("Recognizing speech", fraction: 0.5, now: 13)
        XCTAssertFalse(progress.estimated)
        // A real callback catching up must not remove the stage's Estimated label.
        XCTAssertTrue(StageProgress.usesEstimates(progress.stage))
    }

    @MainActor
    func testProgressColumnsStayFixedAcrossDigitAndTimeChanges() throws {
        let samples: [(Double, Double)] = [(0, 0), (0.01, 9), (0.09, 59), (0.10, 60), (0.99, 3599), (1, 3600)]
        var expected: NSSize?
        for (fraction, elapsed) in samples {
            let host = NSHostingView(rootView: StageProgressDetails(stage: "Recognizing speech", fraction: fraction, elapsed: elapsed))
            let size = host.fittingSize
            if let expected { XCTAssertEqual(size, expected) } else { expected = size }
        }
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let host = NSHostingView(rootView: VStack(spacing: 22) {
            Text("Recognizing speech").font(.headline)
            ForEach(samples.indices, id: \.self) { index in
                StageProgressDetails(stage: "Recognizing speech", fraction: samples[index].0, elapsed: samples[index].1)
            }
            Text("Reading media").font(.headline)
            StageProgressDetails(stage: "Reading media", fraction: 1, elapsed: 2)
        }.padding(30).frame(width: 480, height: 390).background(Color.black).environment(\.colorScheme, .dark))
        host.frame = NSRect(x: 0, y: 0, width: 480, height: 390)
        host.layoutSubtreeIfNeeded()
        let bitmap = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: bitmap)
        let folder = root.appendingPathComponent(".cache/macos-previews")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
            .write(to: folder.appendingPathComponent("stable-progress.png"))
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
