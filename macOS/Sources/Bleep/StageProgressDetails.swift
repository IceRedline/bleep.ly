import SwiftUI

/// Equal, compact metric columns keep numbers anchored as their digits change.
struct StageProgressDetails: View {
    let stage: String
    let fraction: Double
    let elapsed: Double
    var remaining: Double? = nil

    var body: some View {
        Group {
            if let preparationDetail {
                Text(preparationDetail)
                    .font(.callout).foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(width: 320)
            } else if StageProgress.usesEstimates(stage) || fraction > 0 {
                HStack(spacing: 16) {
                    metric("Progress", value: StageProgress.isIndeterminate(stage, fraction: fraction) ? "—"
                           : "\(StageProgress.usesEstimates(stage) && fraction < 1 ? "≈" : "")\(Int(fraction * 100))%")
                    metric("Elapsed", value: clockText(elapsed))
                    if StageProgress.usesEstimates(stage) {
                        metric("Remaining (est.)", value: StageProgress.remainingText(remaining))
                            .help("Estimated time left in this stage, based on recognition or export speed. Waiting for progress measurements when unavailable.")
                    }
                }
            } else {
                Text("\(clockText(elapsed)) elapsed").monospacedDigit().foregroundStyle(.secondary)
            }
        }
        .frame(height: 44)
        .transaction { $0.animation = nil }
    }

    private var preparationDetail: String? {
        if StageProgress.isReadingMedia(stage) {
            return "Checking your media before processing.\nYour original file stays unchanged."
        }
        guard StageProgress.isModelPreparation(stage) else { return nil }
        if stage.localizedCaseInsensitiveContains("download size") {
            return "Checking which model files are needed\nand how much needs to be downloaded."
        }
        if stage.localizedCaseInsensitiveContains("Connecting") {
            return "Connecting to the model download server.\nThe transfer will begin automatically."
        }
        if stage.localizedCaseInsensitiveContains("Checking") {
            return "Checking saved model files.\nProcessing will continue automatically."
        }
        if stage.localizedCaseInsensitiveContains("Loading") {
            return "Loading the model into memory.\nProcessing will continue automatically."
        }
        return "Preparing the model for local processing.\nThis can take a moment."
    }

    private func metric(_ label: String, value: String) -> some View {
        VStack(spacing: 4) {
            Text(value).monospacedDigit().fontWeight(.medium)
            Text(label).font(.caption).foregroundStyle(.secondary)
        }.frame(width: 96)
    }
}

/// Preparation copy, download bytes and processing metrics share one fixed slot.
/// The lower section owns the download bar only; all other stages use the upper ring.
struct StageProgressIndicator: View {
    let stage: String
    let fraction: Double
    let elapsed: Double
    var remaining: Double? = nil

    var body: some View {
        VStack(spacing: 12) {
            Text(stage.isEmpty ? "Preparing your media" : StageProgress.title(stage))
                .font(.headline).multilineTextAlignment(.center).lineLimit(2)
                .frame(height: 32, alignment: .bottom)
            Group {
                if StageProgress.isDownloading(stage) {
                    VStack(spacing: 8) {
                        ProgressView(value: StageProgress.isIndeterminate(stage, fraction: fraction) ? nil : fraction)
                            .progressViewStyle(.linear).tint(.mint)
                            .accessibilityIdentifier("processing-progress-linear")
                            .accessibilityLabel(StageProgress.title(stage))
                        Text(StageProgress.downloadDetail(stage) ?? "Starting download…")
                            .font(.caption).monospacedDigit().foregroundStyle(.secondary)
                    }.frame(width: 320)
                } else {
                    StageProgressDetails(stage: stage, fraction: fraction, elapsed: elapsed, remaining: remaining)
                }
            }.frame(height: 44)
        }.frame(width: 360)
    }
}

/// One indicator per operation: a download bar or a circular progress ring.
struct ProcessingProgressView: View {
    let stage: String
    let fraction: Double
    let elapsed: Double
    var remaining: Double? = nil
    let sourceName: String
    var exporting = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 28) {
            ZStack {
                if !StageProgress.isDownloading(stage) {
                    ring
                }
                Image(systemName: exporting ? "arrow.up.doc" : "waveform")
                    .font(.system(size: 44, weight: .light)).foregroundStyle(.mint)
                    .accessibilityHidden(true)
            }.frame(width: 140, height: 140)
            VStack(spacing: 10) {
                Text(exporting ? "Making the clean cut." : "Listening for the little slips.")
                    .font(.system(size: 30, weight: .semibold)).tracking(-0.7)
                Text(sourceName).foregroundStyle(.secondary)
            }
            StageProgressIndicator(stage: stage, fraction: fraction, elapsed: elapsed, remaining: remaining)
        }
    }

    private var ring: some View {
        let indeterminate = fraction <= 0 || StageProgress.isIndeterminate(stage, fraction: fraction)
        return TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !indeterminate || reduceMotion)) { context in
            ZStack {
                Circle().stroke(.white.opacity(0.08), lineWidth: 8)
                Circle().trim(from: 0, to: indeterminate ? 0.22 : fraction)
                    .stroke(.mint, style: StrokeStyle(lineWidth: 8, lineCap: .round))
                    .rotationEffect(.degrees(-90 + (indeterminate && !reduceMotion
                        ? context.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1.5) / 1.5 * 360 : 0)))
                    .animation(indeterminate || reduceMotion ? nil : .easeOut(duration: 0.2), value: fraction)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(StageProgress.title(stage))
        .accessibilityValue(indeterminate ? "In progress" : "\(Int(fraction * 100))%")
        .accessibilityIdentifier("processing-progress-circular")
    }
}
