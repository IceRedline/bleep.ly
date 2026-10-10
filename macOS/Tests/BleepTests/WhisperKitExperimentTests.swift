import XCTest
import SwiftUI
@testable import Bleep

final class WhisperKitExperimentTests: XCTestCase {
    private func preferences() throws -> UserDefaults {
        let suite = "WhisperKitTests-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        addTeardownBlock { defaults.removePersistentDomain(forName: suite) }
        return defaults
    }

    func testSingleChoiceSelectsExactlyOneEngine() throws {
        let defaults = try preferences()
        XCTAssertEqual(WhisperKitExperiment.backend(defaults: defaults), "faster-whisper")
        for backend in ["whisperkit", "mlx", "faster-whisper"] {
            defaults.set(backend, forKey: "backend")
            XCTAssertEqual(WhisperKitExperiment.backend(defaults: defaults), backend)
        }
        defaults.set("unknown", forKey: "backend")
        XCTAssertEqual(WhisperKitExperiment.backend(defaults: defaults), "faster-whisper")
    }

    func testLegacyToggleMigratesOnceAndDoesNotOverrideLaterSelection() throws {
        let defaults = try preferences()
        defaults.set("mlx", forKey: "backend")
        defaults.set(true, forKey: "experimentalWhisperKit")
        WhisperKitExperiment.migratePreferences(defaults: defaults)
        XCTAssertEqual(defaults.string(forKey: "backend"), "whisperkit")
        XCTAssertNil(defaults.object(forKey: "experimentalWhisperKit"))
        defaults.set("mlx", forKey: "backend")
        WhisperKitExperiment.migratePreferences(defaults: defaults)
        XCTAssertEqual(defaults.string(forKey: "backend"), "mlx")
    }

    func testWhisperKitIsAvailableWithoutALabBundleFlag() throws {
        let defaults = try preferences()
        defaults.set("whisperkit", forKey: "backend")
        WhisperKitExperiment.migratePreferences(defaults: defaults)
        XCTAssertEqual(WhisperKitExperiment.backend(defaults: defaults), "whisperkit")
    }

    func testReviewRetainsRecognitionProvenance() throws {
        let payload = Data("""
        {"source":"/tmp/a.wav","fingerprint":"1:2","duration":3,"has_video":false,"audio_count":1,
        "words":[],"engine":"whisperkit","cache_hit":false,"analysis_seconds":4.5}
        """.utf8)
        let document = try JSONDecoder.bridge.decode(ReviewDocument.self, from: payload)
        let restored = try JSONDecoder.bridge.decode(ReviewDocument.self, from: JSONEncoder.bridge.encode(document))
        XCTAssertEqual(restored.engine, "whisperkit")
        XCTAssertEqual(restored.cacheHit, false)
        XCTAssertEqual(restored.analysisSeconds, 4.5)
    }
    @MainActor
    func testRenderUnifiedSettingsForVisualReview() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let output = root.appendingPathComponent(".cache/macos-previews/settings.png")
        try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
        let view = NSHostingView(rootView: SettingsView().environment(\.colorScheme, .dark))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 590, height: 550),
                              styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = NSAppearance(named: .darkAqua)
        window.contentView = view
        view.frame = NSRect(x: 0, y: 0, width: 590, height: 550)
        window.orderFront(nil)
        view.layoutSubtreeIfNeeded()
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
        let bitmap = try XCTUnwrap(view.bitmapImageRepForCachingDisplay(in: view.bounds))
        view.cacheDisplay(in: view.bounds, to: bitmap)
        window.orderOut(nil)
        try XCTUnwrap(bitmap.representation(using: .png, properties: [:])).write(to: output)
    }

}
