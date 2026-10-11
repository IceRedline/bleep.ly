import AppKit
import SwiftUI

struct SliderTravelInsets: Equatable {
    var leading: CGFloat = 0
    var trailing: CGFloat = 0
}

struct TimelinePlayheadFrameKey: PreferenceKey {
    static var defaultValue: [Int: CGRect] = [:]
    static func reduce(value: inout [Int: CGRect], nextValue: () -> [Int: CGRect]) {
        value.merge(nextValue(), uniquingKeysWith: { _, latest in latest })
    }
}

/// Share the native thumb's travel range with the timeline above it.
struct PlaybackSlider: NSViewRepresentable {
    @Binding var value: Double
    var duration: Double
    @Binding var travelInsets: SliderTravelInsets

    final class Control: NSSlider {
        var geometryChanged: ((SliderTravelInsets) -> Void)?

        var travelInsets: SliderTravelInsets {
            guard bounds.width > 0, let cell = cell as? NSSliderCell else { return .init() }
            // A copied cell recalculated against bounds loses AppKit's actual drawing
            // geometry on macOS 15. Measure the installed cell without sending actions
            // or displaying the temporary values, then restore the playback position.
            let position = cell.doubleValue
            defer { cell.doubleValue = position }
            cell.doubleValue = minValue
            let start = cell.knobRect(flipped: isFlipped).midX
            cell.doubleValue = maxValue
            let end = cell.knobRect(flipped: isFlipped).midX
            return .init(leading: start - bounds.minX, trailing: bounds.maxX - end)
        }

        override func layout() {
            super.layout()
            geometryChanged?(travelInsets)
        }
    }

    final class Coordinator: NSObject {
        var parent: PlaybackSlider
        init(_ parent: PlaybackSlider) { self.parent = parent }

        @objc func seek(_ slider: NSSlider) { parent.value = slider.doubleValue }

        func reportGeometry(_ insets: SliderTravelInsets) {
            // AppKit lays out during a SwiftUI update; publish after that pass.
            DispatchQueue.main.async { [weak self] in
                guard let self, parent.travelInsets != insets else { return }
                parent.travelInsets = insets
            }
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> Control {
        let slider = Control(value: value, minValue: 0, maxValue: duration,
                             target: context.coordinator, action: #selector(Coordinator.seek(_:)))
        slider.isContinuous = true
        slider.isVertical = false
        slider.trackFillColor = .systemMint
        slider.setAccessibilityLabel("Playback position")
        slider.geometryChanged = { [weak coordinator = context.coordinator] in coordinator?.reportGeometry($0) }
        return slider
    }

    func updateNSView(_ slider: Control, context: Context) {
        context.coordinator.parent = self
        slider.maxValue = duration
        slider.doubleValue = min(duration, max(0, value))
        slider.isEnabled = context.environment.isEnabled
        slider.needsLayout = true
    }
}
