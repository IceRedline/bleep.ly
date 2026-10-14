import SwiftUI

/// Equal, compact metric columns keep numbers anchored as their digits change.
struct StageProgressDetails: View {
    let stage: String
    let fraction: Double
    let elapsed: Double
    var remaining: Double? = nil

    var body: some View {
        Group {
            if StageProgress.isReadingMedia(stage) {
                ProgressView().controlSize(.small)
            } else if StageProgress.usesEstimates(stage) || StageProgress.isDownloading(stage) || fraction > 0 {
                HStack(spacing: 16) {
                    metric("Progress", value: StageProgress.isIndeterminate(stage, fraction: fraction) ? "—"
                           : "\(StageProgress.usesEstimates(stage) && fraction < 1 ? "≈" : "")\(Int(fraction * 100))%")
                    metric("Elapsed", value: clockText(elapsed))
                    if StageProgress.usesEstimates(stage) || StageProgress.isDownloading(stage) {
                        metric("Remaining (est.)", value: remaining == nil && StageProgress.isDownloading(stage)
                               ? "Estimating…" : StageProgress.remainingText(remaining))
                            .help("Estimated time left in this stage, based on download, recognition or export speed. Waiting for progress measurements when unavailable.")
                    }
                }
            } else {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("\(clockText(elapsed)) elapsed").monospacedDigit().foregroundStyle(.secondary)
                }
            }
        }
        .frame(height: 44)
        .transaction { $0.animation = nil }
    }

    private func metric(_ label: String, value: String) -> some View {
        VStack(spacing: 4) {
            Text(value).monospacedDigit().fontWeight(.medium)
            Text(label).font(.caption).foregroundStyle(.secondary)
        }.frame(width: 96)
    }
}

/// Unknown preparation work stays visibly active; downloads show measured bytes.
struct StageProgressIndicator: View {
    let stage: String
    let fraction: Double
    let elapsed: Double
    var remaining: Double? = nil

    var body: some View {
        VStack(spacing: 8) {
            Text(StageProgress.title(stage)).font(.headline)
            Group {
                if StageProgress.isIndeterminate(stage, fraction: fraction) {
                    ProgressView().progressViewStyle(.linear)
                } else {
                    ProgressView(value: fraction).progressViewStyle(.linear)
                }
            }.tint(.mint).frame(width: 320).accessibilityLabel(StageProgress.title(stage))
            Text(StageProgress.downloadDetail(stage) ?? " ")
                .font(.caption).monospacedDigit().foregroundStyle(.secondary)
            StageProgressDetails(stage: stage, fraction: fraction, elapsed: elapsed, remaining: remaining)
        }.frame(height: 112)
    }
}
