import XCTest
import SwiftUI
@testable import Bleep

@MainActor
final class WordListTests: XCTestCase {
    func testLanguageListsPersistValidateBeforeSavingAndAllowEmptyReplacement() throws {
        let suite = "word-lists-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        XCTAssertTrue(try WordListPreferences.load(.russian, root: root, defaults: defaults).censor.contains("бля"))
        XCTAssertTrue(WordListPreferences.request(.english, defaults: defaults).isEmpty)
        let ru = WordListDraft(censor: "# Forms\nеб\nруг*", allow: "ебать")
        let en = WordListDraft(censor: "fuck*\nbanana", allow: "fucking # keep this form")
        try WordListPreferences.save([.russian: ru, .english: en], defaults: defaults)
        XCTAssertEqual(try WordListPreferences.load(.russian, root: root, defaults: defaults), ru)
        XCTAssertEqual(try WordListPreferences.load(.english, root: root, defaults: defaults), en)
        XCTAssertEqual(WordListPreferences.request(.english, defaults: defaults)["censor"], ["fuck*", "banana"])
        XCTAssertThrowsError(try WordListPreferences.save([
            .russian: WordListDraft(censor: "new invalid", allow: ""),
            .english: WordListDraft(censor: "changed", allow: "")], defaults: defaults))
        XCTAssertEqual(try WordListPreferences.load(.english, root: root, defaults: defaults), en, "Invalid drafts must not partially save")
        for invalid in ["fuck**", "two words", ".*", "бля"] {
            XCTAssertThrowsError(try WordListPreferences.validate(WordListDraft(censor: invalid, allow: ""), language: .english))
        }
        try WordListPreferences.save([.english: WordListDraft(censor: "", allow: "")], defaults: defaults)
        XCTAssertEqual(WordListPreferences.request(.english, defaults: defaults)["censor"], [""])
        // Reset loads defaults into a draft; persistence changes only after Save.
        _ = try WordListPreferences.builtIn(.english, root: root)
        XCTAssertEqual(try WordListPreferences.load(.english, root: root, defaults: defaults).censor, "")
    }

    func testWordListEditorLayout() async throws {
        let suite = "word-list-layout-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let folder = root.appendingPathComponent(".cache/macos-previews")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        for language in VideoLanguage.allCases {
            let host = NSHostingView(rootView: WordListEditor(root: root, defaults: defaults, language: language)
                .environment(\.colorScheme, .dark))
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 620, height: 660),
                                  styleMask: [.titled], backing: .buffered, defer: false)
            window.appearance = NSAppearance(named: .darkAqua)
            window.contentView = host
            window.orderFront(nil)
            defer { window.orderOut(nil) }
            try await Task.sleep(nanoseconds: 200_000_000)
            host.layoutSubtreeIfNeeded()
            let frame = try XCTUnwrap(host.superview)
            let bitmap = try XCTUnwrap(frame.bitmapImageRepForCachingDisplay(in: frame.bounds))
            frame.cacheDisplay(in: frame.bounds, to: bitmap)
            try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
                .write(to: folder.appendingPathComponent("word-lists-\(language.rawValue).png"))
        }
    }
}
