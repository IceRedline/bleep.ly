import AppKit
import SwiftUI

/// Animate the native clip view: ScrollViewReader.scrollTo can jump on macOS
/// even inside a SwiftUI animation transaction. Fixed row metrics also allow
/// distant targets to be located before LazyVStack has instantiated them.
struct SmoothReviewScroll: NSViewRepresentable {
    static let rowHeight: CGFloat = 56
    static let rowSpacing: CGFloat = 4
    var selection: UUID?
    var index: Int?
    var reduceMotion: Bool

    final class View: NSView {
        var selection: UUID?
        var index: Int?
        var reduceMotion = false
        private var appliedSelection: UUID?
        private var appliedIndex: Int?
        private var scheduled = false

        override func hitTest(_ point: NSPoint) -> NSView? { nil }
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            scheduleScroll()
        }

        func scheduleScroll() {
            guard !scheduled else { return }
            scheduled = true
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                self.scheduled = false
                self.scrollToSelection()
            }
        }

        private func scrollToSelection() {
            guard selection != appliedSelection || index != appliedIndex else { return }
            guard let scroll = enclosingScrollView, let document = scroll.documentView else { return }
            appliedSelection = selection; appliedIndex = index
            guard let index else { return }
            scroll.layoutSubtreeIfNeeded()
            let clip = scroll.contentView
            let center = CGFloat(index) * (SmoothReviewScroll.rowHeight + SmoothReviewScroll.rowSpacing)
                + SmoothReviewScroll.rowHeight / 2
            let target = min(max(0, document.bounds.height - clip.bounds.height), max(0, center - clip.bounds.height / 2))
            guard abs(target - clip.bounds.minY) > 0.5 else { return }
            NSAnimationContext.runAnimationGroup { context in
                context.duration = reduceMotion ? 0 : 0.28
                context.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
                clip.animator().setBoundsOrigin(NSPoint(x: clip.bounds.minX, y: target))
            }
        }
    }

    func makeNSView(context: Context) -> View { View() }
    func updateNSView(_ view: View, context: Context) {
        view.selection = selection; view.index = index; view.reduceMotion = reduceMotion
        view.scheduleScroll()
    }
}
