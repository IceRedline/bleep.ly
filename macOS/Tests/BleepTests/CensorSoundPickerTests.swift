import XCTest
import SwiftUI
@testable import Bleep

@MainActor
final class CensorSoundPickerTests: XCTestCase {
    private struct PickerHost: View {
        @ObservedObject var model: AppModel
        var chooseCustomSound: () -> Void

        var body: some View {
            CensorSoundPicker(selection: $model.sound, hasCustomSound: model.customSound != nil,
                              chooseCustomSound: chooseCustomSound)
                .frame(width: 250, height: 24)
        }
    }

    private func findControl(_ view: NSView) -> NSSegmentedControl? {
        if let control = view as? NSSegmentedControl { return control }
        return view.subviews.lazy.compactMap(findControl).first
    }

    func testCustomReusesSavedSoundAndOnlyPromptsWhenMissing() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("sound-picker-\(UUID())")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let suite = "sound-picker-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let model = AppModel(defaults: defaults, supportDirectory: folder.appendingPathComponent("support"))
        let cue = folder.appendingPathComponent("cue.wav")
        try Data([1, 2, 3]).write(to: cue)
        var nextFile: URL?
        var chooserCount = 0
        let host = NSHostingView(rootView: PickerHost(model: model) {
            chooserCount += 1
            if let nextFile { model.setSound(nextFile) }
        })
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 280, height: 60),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.contentView = host; window.orderFront(nil)
        defer { window.orderOut(nil) }
        try await Task.sleep(nanoseconds: 100_000_000)
        let control = try XCTUnwrap(findControl(host))
        func click(_ segment: Int) {
            control.selectedSegment = segment
            control.sendAction(control.action, to: control.target)
        }
        // Both previous modes must survive cancellation, visually and in preferences.
        for segment in [0, 1] {
            click(segment)
            let previous = model.sound
            let previousPreference = defaults.string(forKey: "censorSound")
            click(2)
            XCTAssertEqual(control.selectedSegment, segment)
            XCTAssertEqual(model.sound, previous)
            XCTAssertEqual(defaults.string(forKey: "censorSound"), previousPreference)
            XCTAssertNil(model.customSound)
            XCTAssertNil(model.error)
        }
        XCTAssertEqual(chooserCount, 2)
        nextFile = folder.appendingPathComponent("missing.wav")
        click(2)
        XCTAssertEqual(control.selectedSegment, 1)
        XCTAssertEqual(model.sound, "silence")
        XCTAssertNil(model.customSound)
        XCTAssertNotNil(model.error)
        nextFile = cue
        click(2)
        XCTAssertEqual(control.selectedSegment, 2)
        XCTAssertEqual(model.sound, "custom")
        let saved = try XCTUnwrap(model.customSound)
        XCTAssertEqual(try Data(contentsOf: saved), Data([1, 2, 3]))
        try await Task.sleep(nanoseconds: 100_000_000)
        // Clicking an already-selected Custom must not ask for the same file again.
        nextFile = nil
        click(2)
        XCTAssertEqual(chooserCount, 4)
        XCTAssertEqual(control.selectedSegment, 2)
        XCTAssertEqual(model.customSound, saved)
        // Switching back from either built-in mode reuses the saved file immediately.
        for segment in [0, 1] {
            click(segment); click(2)
            XCTAssertEqual(control.selectedSegment, 2)
            XCTAssertEqual(model.sound, "custom")
            XCTAssertEqual(defaults.string(forKey: "censorSound"), "custom")
            XCTAssertEqual(model.customSound, saved)
            XCTAssertEqual(chooserCount, 4)
            XCTAssertNil(model.error)
        }
        // The separate filename action still allows replacement; cancelling is harmless.
        for segment in [0, 1, 2] {
            click(segment)
            let previous = model.sound
            model.chooseSound { _ in nil }
            XCTAssertEqual(model.sound, previous)
            XCTAssertEqual(control.selectedSegment, segment)
            XCTAssertEqual(model.customSound, saved)
            XCTAssertEqual(defaults.string(forKey: "censorSound"), previous)
        }
        let replacement = folder.appendingPathComponent("replacement.wav")
        try Data([4, 5, 6]).write(to: replacement)
        model.chooseSound { _ in replacement }
        XCTAssertEqual(model.sound, "custom")
        XCTAssertEqual(try Data(contentsOf: XCTUnwrap(model.customSound)), Data([4, 5, 6]))
    }
}
