import AppKit
import SwiftUI

/// Custom is both a selection and an action, including when already selected.
/// Commit the mode only after the file chooser has accepted a sound.
struct CensorSoundPicker: NSViewRepresentable {
    @Binding var selection: String
    var chooseCustomSound: () -> Void
    private static let modes = ["beep", "silence", "custom"]

    final class Coordinator: NSObject {
        var parent: CensorSoundPicker
        init(_ parent: CensorSoundPicker) { self.parent = parent }

        @objc func selectSound(_ control: NSSegmentedControl) {
            guard CensorSoundPicker.modes.indices.contains(control.selectedSegment) else { return }
            let mode = CensorSoundPicker.modes[control.selectedSegment]
            if mode == "custom" {
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
        control.setAccessibilityLabel("Censor sound")
        return control
    }
    func updateNSView(_ control: NSSegmentedControl, context: Context) {
        context.coordinator.parent = self
        control.isEnabled = context.environment.isEnabled
        control.selectedSegment = Self.modes.firstIndex(of: selection) ?? 0
    }
}
