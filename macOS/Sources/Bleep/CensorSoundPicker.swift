import AppKit
import SwiftUI

/// Reuse a saved custom sound; ask for a file only when none has been saved.
struct CensorSoundPicker: NSViewRepresentable {
    @Binding var selection: String
    var hasCustomSound: Bool
    var chooseCustomSound: () -> Void
    private static let modes = ["beep", "silence", "custom"]

    final class Coordinator: NSObject {
        var parent: CensorSoundPicker
        init(_ parent: CensorSoundPicker) { self.parent = parent }

        @objc func selectSound(_ control: NSSegmentedControl) {
            guard CensorSoundPicker.modes.indices.contains(control.selectedSegment) else { return }
            let mode = CensorSoundPicker.modes[control.selectedSegment]
            if mode == "custom" && !parent.hasCustomSound {
                parent.chooseCustomSound()
            } else {
                parent.selection = mode
            }
            // Cancellation or a failed import leaves the bound mode unchanged.
            // Restore the native segment too, even if SwiftUI has no state update.
            control.selectedSegment = CensorSoundPicker.modes.firstIndex(of: parent.selection) ?? 0
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> NSSegmentedControl {
        let control = NSSegmentedControl(labels: ["Beep", "Silence", "Custom"], trackingMode: .selectOne,
            target: context.coordinator, action: #selector(Coordinator.selectSound(_:)))
        control.segmentDistribution = .fillEqually
        control.selectedSegmentBezelColor = .systemMint
        control.setAccessibilityLabel("Censor sound")
        return control
    }
    func updateNSView(_ control: NSSegmentedControl, context: Context) {
        context.coordinator.parent = self
        control.isEnabled = context.environment.isEnabled
        control.selectedSegment = Self.modes.firstIndex(of: selection) ?? 0
    }
}
