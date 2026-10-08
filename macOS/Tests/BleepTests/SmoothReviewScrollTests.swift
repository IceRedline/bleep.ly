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
        selection.index = 5
        var positions: [CGFloat] = []
        for _ in 0..<24 {
            try await Task.sleep(nanoseconds: 16_666_667)
            positions.append(clip.bounds.minY)
        }
        let target = CGFloat(5) * 60 + 28 - clip.bounds.height / 2
        XCTAssertEqual(clip.bounds.minY, target, accuracy: 1)
        XCTAssertGreaterThan(positions.filter { $0 > 1 && $0 < target - 1 }.count, 5,
                             "Scrolling must traverse multiple intermediate frames instead of snapping")
        for pair in zip(positions, positions.dropFirst()) { XCTAssertGreaterThanOrEqual(pair.1, pair.0 - 0.5) }
        selection.index = 180
        try await Task.sleep(nanoseconds: 60_000_000)
        let interrupted = clip.bounds.minY
        selection.index = 20
        try await Task.sleep(nanoseconds: 20_000_000)
        XCTAssertLessThan(abs(clip.bounds.minY - interrupted), 600,
                          "Retargeting must continue from the visible position, not the previous destination")
        try await Task.sleep(nanoseconds: 400_000_000)
        XCTAssertEqual(clip.bounds.minY, 20 * 60 + 28 - clip.bounds.height / 2, accuracy: 1)
        XCTAssertGreaterThan(interrupted, target)
        selection.reduceMotion = true
        selection.index = 190
        try await Task.sleep(nanoseconds: 60_000_000)
        XCTAssertEqual(clip.bounds.minY, 190 * 60 + 28 - clip.bounds.height / 2, accuracy: 1)
        selection.index = 0
        try await Task.sleep(nanoseconds: 60_000_000)
        XCTAssertEqual(clip.bounds.minY, 0, accuracy: 1)
    }
}
