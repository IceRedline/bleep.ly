import XCTest
import SwiftUI
@testable import Bleep

@MainActor
final class SmoothReviewScrollTests: XCTestCase {
    private final class Selection: ObservableObject {
        @Published var index: Int? = nil
        @Published var reduceMotion = false
        let ids = (0..<200).map { _ in UUID() }
    }
    private struct ListView: View {
        @ObservedObject var selection: Selection
        var body: some View {
            ScrollView {
                LazyVStack(spacing: SmoothReviewScroll.rowSpacing) {
                    ForEach(selection.ids.indices, id: \.self) { index in
                        Text("Word \(index)").frame(maxWidth: .infinity)
                            .frame(height: SmoothReviewScroll.rowHeight)
                            .background(selection.index == index ? Color.mint.opacity(0.2) : .clear)
                    }
                }.background(SmoothReviewScroll(selection: selection.index.map { selection.ids[$0] },
                    index: selection.index, reduceMotion: selection.reduceMotion))
            }
        }
    }
    private func findScroll(_ view: NSView) -> NSScrollView? {
        if let scroll = view as? NSScrollView { return scroll }
        return view.subviews.lazy.compactMap(findScroll).first
    }

    private func waitUntil(_ condition: () -> Bool) async throws {
        let deadline = Date().addingTimeInterval(5)
        while !condition() && Date() < deadline {
            try await Task.sleep(nanoseconds: 5_000_000)
        }
        XCTAssertTrue(condition(), "Scroll did not reach the expected position")
    }

    func testNativeScrollHasIntermediateFramesAndHandlesDistantTargetsAndReducedMotion() async throws {
        let selection = Selection()
        let host = NSHostingView(rootView: ListView(selection: selection))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 380, height: 300),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.contentView = host; window.orderFront(nil)
        defer { window.orderOut(nil) }
        try await Task.sleep(nanoseconds: 200_000_000)
        let scroll = try XCTUnwrap(findScroll(host))
        let clip = scroll.contentView
        var positions: [CGFloat] = []
        // Observe actual frames; hosted runners do not guarantee 60 Hz scheduling.
        clip.postsBoundsChangedNotifications = true
        let observer = NotificationCenter.default.addObserver(
            forName: NSView.boundsDidChangeNotification, object: clip, queue: .main
        ) { _ in
            MainActor.assumeIsolated { positions.append(clip.bounds.minY) }
        }
        defer { NotificationCenter.default.removeObserver(observer) }
        let target = CGFloat(5) * 60 + 28 - clip.bounds.height / 2
        selection.index = 5
        try await waitUntil { abs(clip.bounds.minY - target) < 1 }
        XCTAssertEqual(clip.bounds.minY, target, accuracy: 1)
        XCTAssertTrue(positions.contains { $0 > 1 && $0 < target - 1 },
                      "Scrolling must have intermediate frames instead of snapping")
        // AppKit can snap an interpolated fractional position to the next logical
        // pixel. Allow that rounding while still rejecting backward animation.
        for pair in zip(positions, positions.dropFirst()) { XCTAssertGreaterThanOrEqual(pair.1, pair.0 - 1) }
        selection.index = 180
        try await waitUntil { clip.bounds.minY > target + 1 }
        let interrupted = clip.bounds.minY
        let distantTarget = 180 * 60 + 28 - clip.bounds.height / 2
        XCTAssertLessThan(interrupted, distantTarget - 1)
        positions.removeAll()
        selection.index = 20
        let retarget = 20 * 60 + 28 - clip.bounds.height / 2
        try await waitUntil { abs(clip.bounds.minY - retarget) < 1 }
        XCTAssertFalse(positions.contains { $0 >= distantTarget - 1 },
                       "Retargeting must not jump to the previous destination")
        XCTAssertEqual(clip.bounds.minY, retarget, accuracy: 1)
        XCTAssertGreaterThan(interrupted, target)
        selection.reduceMotion = true
        selection.index = 190
        positions.removeAll()
        let reducedTarget = 190 * 60 + 28 - clip.bounds.height / 2
        try await waitUntil { abs(clip.bounds.minY - reducedTarget) < 1 }
        XCTAssertFalse(positions.contains { $0 > retarget + 1 && $0 < reducedTarget - 1 },
                       "Reduce Motion must jump without intermediate animation frames")
        XCTAssertEqual(clip.bounds.minY, reducedTarget, accuracy: 1)
        selection.index = 0
        try await waitUntil { abs(clip.bounds.minY) < 1 }
        XCTAssertEqual(clip.bounds.minY, 0, accuracy: 1)
    }
}
