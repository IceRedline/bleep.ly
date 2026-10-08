import XCTest
import SwiftUI
@testable import Bleep

@MainActor
final class CensorSoundPickerTests: XCTestCase {
    private func findControl(_ view: NSView) -> NSSegmentedControl? {
        if let control = view as? NSSegmentedControl { return control }
        return view.subviews.lazy.compactMap(findControl).first
    }

    func testCustomOpensChooserAndCancellationRestoresPreviousNativeSegment() async throws {
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
        let host = NSHostingView(rootView: CensorSoundPicker(selection: Binding(get: { model.sound }, set: { model.sound = $0 })) {
            chooserCount += 1
            if let nextFile { model.setSound(nextFile) }
        }.frame(width: 250, height: 24))
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
        nextFile = cue
        click(2)
        XCTAssertEqual(control.selectedSegment, 2)
        XCTAssertEqual(model.sound, "custom")
        let saved = try XCTUnwrap(model.customSound)
        XCTAssertEqual(try Data(contentsOf: saved), Data([1, 2, 3]))
        // Clicking an already-selected Custom still opens the chooser.
        nextFile = nil
        click(2)
        XCTAssertEqual(chooserCount, 4)
        XCTAssertEqual(control.selectedSegment, 2)
        XCTAssertEqual(model.customSound, saved)
        // An existing saved file must not silently select Custom when the chooser is cancelled.
        click(1); click(2)
        XCTAssertEqual(control.selectedSegment, 1)
        XCTAssertEqual(model.sound, "silence")
        XCTAssertEqual(model.customSound, saved)
        // A failed import also keeps the previous usable mode and saved cue.
        nextFile = folder.appendingPathComponent("missing.wav")
        click(2)
        XCTAssertEqual(control.selectedSegment, 1)
        XCTAssertEqual(model.sound, "silence")
        XCTAssertEqual(model.customSound, saved)
        XCTAssertNotNil(model.error)
    }
}
