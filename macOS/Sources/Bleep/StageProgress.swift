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
    private var lastMeasurement: Double?
    private var downloadMeasurement: (fraction: Double, time: Double)?
    private var presentedRemaining: Double?
    private var lastPresentation = -Double.infinity
    var duration = 0.0

    static func isReadingMedia(_ stage: String) -> Bool {
        stage.localizedCaseInsensitiveContains("Reading media")
    }

    static func usesEstimates(_ stage: String) -> Bool {
        stage.localizedCaseInsensitiveContains("recognizing") ||
            stage.localizedCaseInsensitiveContains("exporting") || stage.contains("Preparing audio")
    }

    static func isDownloading(_ stage: String) -> Bool {
        stage.localizedCaseInsensitiveContains("Downloading ")
    }

    static func title(_ stage: String) -> String {
        isDownloading(stage) ? String(stage.components(separatedBy: " — ")[0]) : stage
    }

    static func downloadDetail(_ stage: String) -> String? {
        guard isDownloading(stage), let split = stage.range(of: " — ") else { return nil }
        return String(stage[split.upperBound...])
    }

    static func isIndeterminate(_ stage: String, fraction: Double) -> Bool {
        if isReadingMedia(stage) { return true }
        if isDownloading(stage) { return downloadDetail(stage)?.contains(" / ") != true }
        return !usesEstimates(stage) && fraction <= 0
    }

    mutating func report(_ label: String, fraction: Double, now: Double) {
        let identity = Self.title(label)
        if identity != stage {
            stage = identity; started = now; actual = 0; displayed = 0; estimated = false; measuredExpected = nil
            lastMeasurement = nil; presentedRemaining = nil; lastPresentation = -.infinity
            downloadMeasurement = nil
        }
        // File hashing is a brief preparation step, not useful percentage feedback.
        guard !Self.isReadingMedia(label) else { return }
        if Self.isDownloading(label) {
            let value = fraction.isFinite ? min(1, max(0, fraction)) : actual
            if value < actual {
                // A downloader can restart a failed transfer. Show its actual bytes.
                downloadMeasurement = value > 0 ? (value, now) : nil
                measuredExpected = nil; presentedRemaining = nil; lastMeasurement = nil
            }
            if value > actual {
                if let previous = downloadMeasurement, now > previous.time {
                    // Measure newly transferred bytes, not a resumed file's initial offset.
                    let rate = (value - previous.fraction) / (now - previous.time)
                    let sample = now - started + (1 - value) / rate
                    if let expected = measuredExpected {
                        let weight = 1 - exp(-(now - previous.time) / 5)
                        measuredExpected = expected + weight * (sample - expected)
                    } else { measuredExpected = sample }
                }
                downloadMeasurement = (value, now)
                lastMeasurement = now
            }
            actual = value; displayed = value; estimated = false
            return
        }
        if fraction > actual && fraction > 0.01 && now > started {
            let sample = max(1, (now - started) / fraction)
            if let previous = measuredExpected, let lastMeasurement {
                // A time-based filter behaves consistently with sparse and frequent callbacks.
                let weight = 1 - exp(-max(0, now - lastMeasurement) / 20)
                measuredExpected = previous + weight * (sample - previous)
            } else { measuredExpected = sample }
            lastMeasurement = now
        }
        actual = max(actual, min(1, max(0, fraction)))
        displayed = max(displayed, actual)
        estimated = displayed > actual
    }

    /// ETA uses measured worker throughput only, never the interpolated percentage.
    /// If the estimate expires without another callback, wait for fresh evidence.
    func remaining(now: Double) -> Double? {
        guard Self.usesEstimates(stage) || Self.isDownloading(stage) else { return nil }
        if actual >= 1 { return 0 }
        if Self.isDownloading(stage), let lastMeasurement, now - lastMeasurement > 15 { return nil }
        guard let measuredExpected, measuredExpected > now - started else { return nil }
        return measuredExpected - max(0, now - started)
    }

    /// Coarse steps plus hysteresis prevent small throughput changes from flipping labels.
    mutating func displayRemaining(now: Double) -> Double? {
        guard let raw = remaining(now: now) else { presentedRemaining = nil; return nil }
        if raw == 0 { presentedRemaining = 0; return 0 }
        let step: Double = raw <= 300 ? 30 : (raw <= 600 ? 60 : 300)
        let candidate = ceil(raw / step) * step
        if let previous = presentedRemaining {
            guard now - lastPresentation >= 5 else { return previous }
            if candidate > previous && raw < previous + min(30, step / 3) { return previous }
            if candidate == previous { return previous }
        }
        presentedRemaining = candidate
        lastPresentation = now
        return candidate
    }

    static func remainingText(_ seconds: Double?) -> String {
        guard let seconds, seconds.isFinite else { return "—" }
        if seconds <= 0 { return "Done" }
        if seconds <= 30 { return "~30 sec" }
        let minutes = seconds / 60
        return minutes == minutes.rounded() ? "~\(Int(minutes)) min" : String(format: "~%.1f min", minutes)
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
