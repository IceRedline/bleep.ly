import XCTest
import SwiftUI
@testable import Bleep

@MainActor
final class PlaybackSliderTests: XCTestCase {
    private func findSlider(_ view: NSView) -> PlaybackSlider.Control? {
        if let slider = view as? PlaybackSlider.Control { return slider }
        return view.subviews.lazy.compactMap(findSlider).first
    }

    func testTimelineMarkersFollowNativeThumbAcrossRangeAndResize() async throws {
        let suite = "slider-layout-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let model = AppModel(defaults: defaults)
        model.selectMode(.advanced)
        model.document = ReviewDocument(source: "/tmp/slider.wav", fingerprint: "layout", duration: 100,
                                        hasVideo: false, audioCount: 2, words: [],
                                        tracks: [.init(index: 0, title: "Track 1"), .init(index: 1, title: "Track 2")])
        model.phase = .review
        var markers: [Int: CGRect] = [:]
        let host = NSHostingView(rootView: ContentView(model: model).defaultAppStorage(defaults)
            .onPreferenceChange(TimelinePlayheadFrameKey.self) { markers = $0 })
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 880, height: 780),
                              styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = host
        window.orderFront(nil)
        defer { window.orderOut(nil) }
        for width in [880.0, 1120.0, 1377.0] {
            window.setContentSize(NSSize(width: width, height: 780))
            for position in [0.0, 5, 25, 50, 75, 95, 100] {
                model.playhead = position
                try await Task.sleep(nanoseconds: 120_000_000)
                host.layoutSubtreeIfNeeded()
                let slider = try XCTUnwrap(findSlider(host))
                let cell = try XCTUnwrap(slider.cell as? NSSliderCell)
                let thumb = slider.convert(cell.knobRect(flipped: slider.isFlipped), to: host)
                XCTAssertEqual(slider.doubleValue, position)
                for track in [0, 1] {
                    let marker = try XCTUnwrap(markers[track])
                    XCTAssertEqual(marker.midX, thumb.midX, accuracy: 0.5,
                                   "width=\(width) time=\(position) insets=\(slider.travelInsets)")
                }
            }
        }
        let slider = try XCTUnwrap(findSlider(host))
        slider.doubleValue = 37
        slider.sendAction(slider.action, to: slider.target)
        XCTAssertEqual(model.playhead, 37, "Native slider actions must still seek")
        XCTAssertEqual(slider.accessibilityLabel(), "Playback position")
    }
}
