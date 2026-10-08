import Foundation

/// Sparse model callbacks are supplemented by a clearly labeled estimate.
/// Only a real worker event can complete a stage; estimates never reach 100%.
struct StageProgress {
    private(set) var stage = ""
    private(set) var actual = 0.0
    private(set) var displayed = 0.0
    private(set) var started = 0.0
    private(set) var estimated = false
    private var measuredExpected: Double?
    var duration = 0.0

    static func isReadingMedia(_ stage: String) -> Bool {
        stage.localizedCaseInsensitiveContains("Reading media")
    }

    static func usesEstimates(_ stage: String) -> Bool {
        stage.localizedCaseInsensitiveContains("recognizing") ||
            stage.localizedCaseInsensitiveContains("exporting") || stage.contains("Preparing audio")
    }

    mutating func report(_ label: String, fraction: Double, now: Double) {
        if label != stage {
            stage = label; started = now; actual = 0; displayed = 0; estimated = false; measuredExpected = nil
        }
        // File hashing is a brief preparation step, not useful percentage feedback.
        guard !Self.isReadingMedia(label) else { return }
        if fraction > actual && fraction > 0.01 && now > started {
            measuredExpected = max(1, (now - started) / fraction)
        }
        actual = max(actual, min(1, max(0, fraction)))
        displayed = max(displayed, actual)
        estimated = displayed > actual
    }

    mutating func advance(now: Double) {
        let elapsed = max(0, now - started)
        guard Self.usesEstimates(stage), actual < 1 else { return }
        let initial = stage.localizedCaseInsensitiveContains("exporting") ? max(3, duration * 0.08) : max(12, duration * 0.4 + 5)
        let expected = measuredExpected ?? initial
        displayed = max(displayed, min(0.9, 0.9 * (1 - exp(-elapsed / expected))))
        estimated = displayed > actual + 0.001
    }
}
