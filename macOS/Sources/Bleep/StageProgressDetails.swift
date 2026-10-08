import SwiftUI

/// Stable columns: real callbacks and interpolated updates share one stage label.
struct StageProgressDetails: View {
    let stage: String
    let fraction: Double
    let elapsed: Double

    var body: some View {
        Group {
            if StageProgress.isReadingMedia(stage) {
                ProgressView().controlSize(.small)
            } else if StageProgress.usesEstimates(stage) || fraction > 0 {
                HStack(spacing: 6) {
                    Text(StageProgress.usesEstimates(stage) ? "Estimated" : "Progress")
                        .frame(width: 78, alignment: .trailing)
                    Text("\(Int(fraction * 100))%")
                        .frame(width: 44, alignment: .trailing)
                    Text("·")
                    Text(clockText(elapsed))
                        .frame(width: 72, alignment: .trailing)
                    Text("elapsed")
                }.monospacedDigit()
            } else {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.small)
                    Text(clockText(elapsed)).monospacedDigit().frame(width: 72, alignment: .trailing)
                    Text("elapsed")
                }
            }
        }
        .foregroundStyle(.secondary)
        .frame(height: 20)
        // Background color interpolation must not animate status text or geometry.
        .transaction { $0.animation = nil }
    }
}
