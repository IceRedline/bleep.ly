import XCTest
import SwiftUI
@testable import Bleep

@MainActor
final class WindowLayoutTests: XCTestCase {
    func testDropZoneStaysFixedAndNativeTitlebarIsTransparent() async throws {
        let suite = "layout-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let model = AppModel(defaults: defaults)
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let folder = root.appendingPathComponent(".cache/macos-previews")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        for size in [NSSize(width: 880, height: 690), NSSize(width: 1120, height: 780)] {
            var dropFrame = CGRect.zero
            model.selectMode(.fast)
            let host = NSHostingView(rootView: ContentView(model: model)
                .onPreferenceChange(DropZoneFrameKey.self) { dropFrame = $0 })
            let window = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                                  styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
            window.appearance = NSAppearance(named: .darkAqua)
            window.contentView = host
            window.orderFront(nil)
            defer { window.orderOut(nil) }
            try await Task.sleep(nanoseconds: 350_000_000)
            host.layoutSubtreeIfNeeded()
            let fast = dropFrame
            XCTAssertGreaterThan(fast.width, 0)
            XCTAssertTrue(window.titlebarAppearsTransparent)
            XCTAssertEqual(window.titleVisibility, .hidden)
            XCTAssertTrue(window.styleMask.contains(.fullSizeContentView))
            XCTAssertNotNil(window.standardWindowButton(.closeButton))
            for mode in [WorkflowMode.fast, .advanced] {
                model.selectMode(mode)
                try await Task.sleep(nanoseconds: 350_000_000)
                host.layoutSubtreeIfNeeded()
                XCTAssertEqual(dropFrame, fast, "Drop target must stay anchored when toggling modes")
                let frame = try XCTUnwrap(host.superview)
                let bitmap = try XCTUnwrap(frame.bitmapImageRepForCachingDisplay(in: frame.bounds))
                frame.cacheDisplay(in: frame.bounds, to: bitmap)
                try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
                    .write(to: folder.appendingPathComponent("window-\(mode.rawValue)-\(Int(size.width)).png"))
            }
        }
    }
}
