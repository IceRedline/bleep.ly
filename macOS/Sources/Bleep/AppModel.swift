import AppKit
import AVKit
import SwiftUI
import UniformTypeIdentifiers

@MainActor
final class AppModel: ObservableObject {
    enum Phase: String { case ready, analyzing, review, exporting, done }
    @Published var phase: Phase = .ready
    @Published var document: ReviewDocument?
    @Published var selected: UUID?
    @Published var stage = "Preparing"
    @Published var fraction = 0.0
    @Published var error: String?
    @Published var sourceName = ""
    @Published var sound = "beep"
    @Published var customSound: URL?
    @Published var exportFormat = "audio"
    @Published var exportURL: URL?
    @Published var playhead = 0.0
    @Published var isPlaying = false
    @Published var showAllWords = false
    @Published var search = ""
    @Published var cancelling = false
    @Published var hasEdits = false
    let player = AVPlayer()
    private let bridge = PythonBridge()
    private var observer: Any?
    private var auditionEnd: Double?
    private var previewGeneration = UUID()
    private var undoDocuments: [ReviewDocument] = []
    private var pendingSource: URL?

    static var support: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("bleep.ly", isDirectory: true)
    }
    static var defaultRoot: String {
        Bundle.main.object(forInfoDictionaryKey: "BleepProjectRoot") as? String ?? FileManager.default.currentDirectoryPath
    }
    var busy: Bool { phase == .analyzing || phase == .exporting }
    var canUndo: Bool { !undoDocuments.isEmpty }
    var root: URL {
        URL(fileURLWithPath: UserDefaults.standard.string(forKey: "projectRoot") ?? Self.defaultRoot)
    }
    var python: URL {
        let path = UserDefaults.standard.string(forKey: "pythonPath") ?? ""
        return path.isEmpty ? root.appendingPathComponent(".venv/bin/python") : URL(fileURLWithPath: path)
    }
    var visibleWords: [ReviewWord] {
        (document?.words ?? []).filter { (showAllWords || $0.profane) &&
            (search.isEmpty || $0.word.localizedCaseInsensitiveContains(search)) }
    }

    init() {
        observer = player.addPeriodicTimeObserver(forInterval: CMTime(seconds: 0.04, preferredTimescale: 600), queue: .main) { [weak self] time in
            Task { @MainActor in
                guard let self else { return }
                self.playhead = max(0, time.seconds.isFinite ? time.seconds : 0)
                if let end = self.auditionEnd, self.playhead >= end { self.pause() }
                self.isPlaying = self.player.rate != 0
            }
        }
    }

    func chooseSource() {
        guard !busy else { return }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.movie, .audio]
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url { open(url) }
    }

    func open(_ url: URL, transcript: URL? = nil) {
        guard !busy else { return }
        // A new source deliberately starts a fresh review; the last draft stays on disk until success.
        pause()
        pendingSource = url
        sourceName = url.lastPathComponent
        stage = "Reading media"
        fraction = 0
        cancelling = false
        error = nil
        phase = .analyzing
        Task {
            do {
                var request: [String: Any] = ["operation": "analyze", "source": url.path,
                    "cache_dir": Self.support.appendingPathComponent("cache").path,
                    "backend": UserDefaults.standard.string(forKey: "backend") ?? "faster-whisper",
                    "offline": !UserDefaults.standard.bool(forKey: "allowDownloads")]
                let stream = UserDefaults.standard.integer(forKey: "audioStream")
                // -1 requests automatic selection and reports ambiguous multi-track media.
                if stream > 0 { request["audio_stream"] = stream - 1 }
                if let transcript { request["transcript"] = transcript.path }
                let result = try await bridge.run(root: root, python: python, request: request, progress: updateProgress)
                document = try JSONDecoder.bridge.decode(ReviewDocument.self, from: result)
                undoDocuments = []
                hasEdits = false
                selected = document?.words.first(where: \.profane)?.id
                exportFormat = document?.hasVideo == true ? "video" : "audio"
                exportURL = nil
                player.replaceCurrentItem(with: AVPlayerItem(url: url))
                playhead = 0
                phase = .review
                saveDraft()
            } catch {
                if !cancelling { self.error = error.localizedDescription }
                phase = document == nil ? .ready : .review
            }
            cancelling = false
        }
    }

    func updateProgress(_ label: String, _ value: Double) {
        guard busy, !cancelling else { return }
        stage = label
        fraction = value
    }

    func cancel() { cancelling = true; stage = "Cancelling…"; bridge.cancel() }
    func pause() { previewGeneration = UUID(); player.pause(); isPlaying = false; auditionEnd = nil }
    func seek(_ seconds: Double) {
        pause()
        let value = min(document?.duration ?? 0, max(0, seconds))
        playhead = value
        player.seek(to: CMTime(seconds: value, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
    }
    func togglePlayback() {
        if isPlaying { pause() } else {
            auditionEnd = nil
            if playhead >= (document?.duration ?? 0) - 0.05 { seek(0) }
            player.play(); isPlaying = true
        }
    }
    func audition(_ word: ReviewWord) {
        pause()
        selected = word.id
        auditionEnd = min(document?.duration ?? word.end, word.end + 0.7)
        let token = UUID()
        previewGeneration = token
        player.seek(to: CMTime(seconds: max(0, word.start - 0.5), preferredTimescale: 600),
                    toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] finished in
            Task { @MainActor in
                guard let self, finished, self.previewGeneration == token else { return }
                self.player.play(); self.isPlaying = true
            }
        }
    }

    func edit(_ change: (inout ReviewDocument) -> Void) {
        guard !busy, var value = document else { return }
        undoDocuments.append(value)
        if undoDocuments.count > 100 { undoDocuments.removeFirst() }
        change(&value)
        document = value
        hasEdits = true
        exportURL = nil
        phase = .review
        saveDraft()
    }
    func toggle(_ word: ReviewWord) {
        edit { value in
            if let index = value.words.firstIndex(where: { $0.id == word.id }) { value.words[index].profane.toggle() }
        }
    }
    func undo() {
        guard !busy, let previous = undoDocuments.popLast() else { return }
        document = previous; exportURL = nil; phase = .review; saveDraft()
    }
    func addInterval(label: String, start: Double, end: Double) {
        guard document?.validateInterval(start: start, end: end) == true else { return }
        let word = ReviewWord(word: label.isEmpty ? "Manual interval" : label, start: start, end: end,
                              profane: true, muteStart: start, muteEnd: end)
        edit { value in value.words.append(word); value.words.sort { $0.start < $1.start } }
        selected = word.id
    }
    func updateInterval(id: UUID, start: Double, end: Double) {
        guard document?.validateInterval(start: start, end: end) == true else { return }
        edit { value in
            if let index = value.words.firstIndex(where: { $0.id == id }) {
                value.words[index].muteStart = start; value.words[index].muteEnd = end
            }
        }
    }
    func saveDraft() {
        guard let document else { return }
        do {
            try FileManager.default.createDirectory(at: Self.support, withIntermediateDirectories: true)
            try JSONEncoder.bridge.encode(document).write(to: Self.support.appendingPathComponent("last-review.json"), options: .atomic)
        } catch { self.error = "Could not save your review: \(error.localizedDescription)" }
    }
    func restoreDraft() {
        guard !busy else { return }
        do {
            let data = try Data(contentsOf: Self.support.appendingPathComponent("last-review.json"))
            let restored = try JSONDecoder.bridge.decode(ReviewDocument.self, from: data)
            guard FileManager.default.fileExists(atPath: restored.source) else {
                throw BridgeFailure(message: "The original media has moved. Open it again.")
            }
            pause(); document = restored; undoDocuments = []; selected = nil
            sourceName = restored.url.lastPathComponent
            player.replaceCurrentItem(with: AVPlayerItem(url: restored.url))
            exportFormat = restored.hasVideo ? "video" : "audio"
            exportURL = nil; phase = .review
        } catch { self.error = error.localizedDescription }
    }
    func importTranscript() {
        guard !busy, let source = document?.url ?? pendingSource else {
            error = "Open the source media first, then import its reviewed transcript."; return
        }
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.json]
        panel.message = "Import reviewed word timestamps for \(source.lastPathComponent)"
        if panel.runModal() == .OK, let url = panel.url { open(source, transcript: url) }
    }
    func chooseSound() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.audio]
        if panel.runModal() == .OK, let url = panel.url { setSound(url) }
    }
    func setSound(_ url: URL) { customSound = url; sound = "custom" }

    func export() {
        guard !busy, let document else { return }
        if sound == "custom" && customSound == nil { chooseSound(); return }
        let panel = NSSavePanel()
        let video = exportFormat == "video"
        panel.allowedContentTypes = video ? [.quickTimeMovie, .mpeg4Movie, UTType(filenameExtension: "mkv") ?? .movie] : [.wav]
        panel.nameFieldStringValue = document.url.deletingPathExtension().lastPathComponent + "_censored." + (video ? "mov" : "wav")
        panel.message = video ? "The original video stream is copied without re-encoding." : "48 kHz · 24-bit stereo WAV"
        guard panel.runModal() == .OK, let destination = panel.url else { return }
        if FileManager.default.fileExists(atPath: destination.path) {
            error = "Choose a new filename. Existing files are kept intact."; return
        }
        pause(); phase = .exporting; stage = "Preparing export"; fraction = 0; cancelling = false
        Task {
            do {
                var request: [String: Any] = ["operation": "export", "output": destination.path,
                    "format": exportFormat, "sound": sound,
                    "document": try JSONSerialization.jsonObject(with: JSONEncoder.bridge.encode(document))]
                if let customSound { request["custom_sound"] = customSound.path }
                _ = try await bridge.run(root: root, python: python, request: request, progress: updateProgress)
                exportURL = destination; phase = .done
            } catch {
                if !cancelling { self.error = error.localizedDescription }
                phase = .review
            }
            cancelling = false
        }
    }
}
