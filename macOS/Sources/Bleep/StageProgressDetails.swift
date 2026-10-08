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
            } else if StageProgress.usesEstimates(stage) || fraction > 0 {
                HStack(spacing: 16) {
                    metric("Progress", value: "\(StageProgress.usesEstimates(stage) && fraction < 1 ? "≈" : "")\(Int(fraction * 100))%")
                    metric("Elapsed", value: clockText(elapsed))
                    if StageProgress.usesEstimates(stage) {
                        metric("Remaining (est.)", value: StageProgress.remainingText(remaining))
                            .help("Estimated time left in this stage, based on recognition or export speed. Waiting for a progress update when unavailable.")
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
