import XCTest
import SwiftUI
@testable import Bleep

final class ProgressAndContextTests: XCTestCase {
    func testDownloadCountersKeepTheirStageAndUseMeasuredSpeedWithoutFakeProgress() throws {
        var progress = StageProgress()
        progress.report("Checking GigaAM model", fraction: 0, now: 0)
        XCTAssertTrue(StageProgress.isIndeterminate(progress.stage, fraction: progress.displayed))
        progress.report("Track 1/2 · Downloading GigaAM — 0 / 100 MB", fraction: 0, now: 5)
        progress.report("Track 1/2 · Downloading GigaAM — 10 / 100 MB", fraction: 0.1, now: 7)
        XCTAssertNil(progress.remaining(now: 7))
        progress.report("Track 1/2 · Downloading GigaAM — 30 / 100 MB", fraction: 0.3, now: 9)
        XCTAssertEqual(progress.stage, "Track 1/2 · Downloading GigaAM")
        XCTAssertEqual(progress.started, 5)
        XCTAssertEqual(try XCTUnwrap(progress.remaining(now: 9)), 7, accuracy: 0.001)
        progress.advance(now: 12)
        XCTAssertEqual(progress.displayed, 0.3)
        XCTAssertFalse(progress.estimated)
        XCTAssertNil(progress.remaining(now: 30), "A stalled transfer must not keep counting down")
        XCTAssertFalse(StageProgress.isIndeterminate("Downloading GigaAM — 0 / 100 MB", fraction: 0))
        XCTAssertTrue(StageProgress.isIndeterminate("Downloading GigaAM — 50 MB", fraction: 0))
    }

    func testDownloadETAExcludesResumeOffsetAndResetsAfterRetry() throws {
        var progress = StageProgress()
        progress.report("Downloading Qwen — 750 / 1000 MB", fraction: 0.75, now: 10)
        XCTAssertNil(progress.remaining(now: 10))
        progress.report("Downloading Qwen — 800 / 1000 MB", fraction: 0.8, now: 15)
        XCTAssertEqual(try XCTUnwrap(progress.remaining(now: 15)), 20, accuracy: 0.001)
        progress.report("Downloading Qwen — 200 / 1000 MB", fraction: 0.2, now: 16)
        XCTAssertEqual(progress.displayed, 0.2)
        XCTAssertNil(progress.remaining(now: 16))
        progress.report("Downloading Qwen — 300 / 1000 MB", fraction: 0.3, now: 17)
        XCTAssertEqual(try XCTUnwrap(progress.remaining(now: 17)), 7, accuracy: 0.001)
        progress.report("Downloading Qwen — 1000 / 1000 MB", fraction: 1, now: 18)
        XCTAssertEqual(progress.remaining(now: 18), 0)
        progress.report("Loading word alignment model", fraction: 0, now: 19)
        progress.advance(now: 34)
        XCTAssertTrue(StageProgress.isIndeterminate(progress.stage, fraction: progress.displayed))
        XCTAssertNil(progress.remaining(now: 34))
    }

    func testNetworkDownloadBytesKeepTimerWithoutInventingPercentOrETA() {
        var progress = StageProgress()
        for (time, bytes) in [(10.0, "0.0"), (15.0, "25.4"), (20.0, "61.2")] {
            let label = "Track 1/2 · Downloading Qwen ForcedAligner — \(bytes) MB downloaded"
            progress.report(label, fraction: 0, now: time)
            progress.advance(now: time + 2)
            XCTAssertEqual(progress.started, 10)
            XCTAssertTrue(StageProgress.isDownloading(label))
            XCTAssertTrue(StageProgress.isIndeterminate(label, fraction: progress.displayed))
            XCTAssertEqual(StageProgress.downloadDetail(label), "\(bytes) MB downloaded")
            XCTAssertEqual(progress.displayed, 0)
            XCTAssertNil(progress.remaining(now: time + 2))
        }
    }

    @MainActor
    func testDownloadAndPreparationLayoutKeepsSpaceForVisibleProgress() throws {
        let samples: [(String, Double, Double, Double?)] = [
            ("Checking GigaAM model", 0, 15, nil),
            ("Downloading GigaAM — 204.5 / 448.9 MB", 0.455, 34, 60),
            ("Downloading Qwen ForcedAligner — 541.2 MB downloaded", 0, 200, nil),
            ("Loading word alignment model", 0, 12, nil)
        ]
        var expected: NSSize?
        for (stage, fraction, elapsed, remaining) in samples {
            let host = NSHostingView(rootView: StageProgressIndicator(stage: stage, fraction: fraction, elapsed: elapsed, remaining: remaining))
            let size = host.fittingSize
            XCTAssertEqual(size.height, 112)
            if let expected { XCTAssertEqual(size, expected) } else { expected = size }
        }
        let host = NSHostingView(rootView: VStack(spacing: 28) {
            ForEach(samples.indices, id: \.self) { index in
                let item = samples[index]
                StageProgressIndicator(stage: item.0, fraction: item.1, elapsed: item.2, remaining: item.3)
            }
        }.padding(32).frame(width: 560, height: 640).background(Color(red: 0.06, green: 0.09, blue: 0.14))
            .environment(\.colorScheme, .dark))
        host.frame = NSRect(x: 0, y: 0, width: 560, height: 640)
        host.layoutSubtreeIfNeeded()
        let bitmap = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: bitmap)
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let folder = root.appendingPathComponent(".cache/macos-previews")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
            .write(to: folder.appendingPathComponent("model-download-progress.png"))
    }

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
        // A real callback catching up must not remove the stage's approximation marker.
        XCTAssertTrue(StageProgress.usesEstimates(progress.stage))
    }

    func testRemainingTimeUsesWorkerSpeedAndResetsBetweenStages() throws {
        var progress = StageProgress()
        progress.report("Recognizing speech", fraction: 0, now: 0)
        progress.advance(now: 30)
        XCTAssertGreaterThan(progress.displayed, 0)
        XCTAssertNil(progress.remaining(now: 30), "Synthetic progress is not throughput evidence")
        progress.report("Recognizing speech", fraction: 0.11, now: 64)
        XCTAssertEqual(try XCTUnwrap(progress.remaining(now: 64)), 64 / 0.11 - 64, accuracy: 0.01)
        XCTAssertEqual(try XCTUnwrap(progress.remaining(now: 74)), 64 / 0.11 - 74, accuracy: 0.01)
        XCTAssertNil(progress.remaining(now: 600), "Do not claim zero while the worker is unfinished")
        progress.report("Recognizing speech", fraction: 1, now: 601)
        XCTAssertEqual(progress.remaining(now: 601), 0)
        progress.report("Exporting video", fraction: 0, now: 602)
        XCTAssertNil(progress.remaining(now: 602))
        progress.report("Exporting video", fraction: 0.5, now: 612)
        XCTAssertEqual(progress.remaining(now: 612), 10)
        progress.report("Reading media", fraction: 0.5, now: 613)
        XCTAssertNil(progress.remaining(now: 613))
    }

    func testSmoothedEstimateAndCoarseStepsResistSmallOscillations() throws {
        var progress = StageProgress()
        progress.report("Recognizing speech", fraction: 0, now: 0)
        progress.report("Recognizing speech", fraction: 0.25, now: 30)
        XCTAssertEqual(progress.displayRemaining(now: 30), 90)
        // A new measurement implies 120 seconds remaining, but the filter should absorb the jump.
        progress.report("Recognizing speech", fraction: 0.26, now: 42)
        let smoothed = try XCTUnwrap(progress.remaining(now: 42))
        XCTAssertGreaterThan(smoothed, 78)
        XCTAssertLessThan(smoothed, 120)
        XCTAssertEqual(progress.displayRemaining(now: 42), 90)
        // A tiny fluctuation does not immediately promote the next bucket.
        progress.report("Recognizing speech", fraction: 0.27, now: 43)
        XCTAssertEqual(progress.displayRemaining(now: 43), 90)
        // Sustained slowdown must still be reflected, rather than forcing a false countdown.
        progress.report("Recognizing speech", fraction: 0.28, now: 100)
        XCTAssertGreaterThan(try XCTUnwrap(progress.displayRemaining(now: 100)), 90)
        progress.report("Exporting video", fraction: 0, now: 101)
        XCTAssertNil(progress.displayRemaining(now: 101))
        progress.report("Exporting video", fraction: 0.2, now: 131)
        XCTAssertEqual(progress.displayRemaining(now: 131), 120)
        XCTAssertEqual(progress.displayRemaining(now: 161), 90)
        XCTAssertEqual(progress.displayRemaining(now: 191), 60)
        XCTAssertEqual(StageProgress.remainingText(120), "~2 min")
        XCTAssertEqual(StageProgress.remainingText(90), "~1.5 min")
        XCTAssertEqual(StageProgress.remainingText(60), "~1 min")
        XCTAssertEqual(StageProgress.remainingText(30), "~30 sec")
        XCTAssertEqual(StageProgress.remainingText(nil), "—")
    }

    @MainActor
    func testProgressColumnsStayFixedAcrossDigitAndTimeChanges() throws {
        let samples: [(Double, Double)] = [(0, 0), (0.01, 9), (0.09, 59), (0.10, 60), (0.99, 3599), (1, 3600)]
        var expected: NSSize?
        for (fraction, elapsed) in samples {
            let host = NSHostingView(rootView: StageProgressDetails(stage: "Recognizing speech", fraction: fraction, elapsed: elapsed, remaining: fraction == 0 ? nil : 6000 * (1 - fraction)))
            let size = host.fittingSize
            if let expected { XCTAssertEqual(size, expected) } else { expected = size }
        }
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let host = NSHostingView(rootView: VStack(spacing: 22) {
            Text("Recognizing speech").font(.headline)
            ForEach(samples.indices, id: \.self) { index in
                StageProgressDetails(stage: "Recognizing speech", fraction: samples[index].0, elapsed: samples[index].1, remaining: index == 0 ? nil : [120.0, 120, 90, 60, 30, 0][index])
            }
            Text("Reading media").font(.headline)
            StageProgressDetails(stage: "Reading media", fraction: 1, elapsed: 2)
        }.padding(30).frame(width: 480, height: 560).background(Color.black).environment(\.colorScheme, .dark))
        host.frame = NSRect(x: 0, y: 0, width: 480, height: 560)
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
