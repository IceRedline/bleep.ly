import AppKit
import AVKit
import SwiftUI
import UniformTypeIdentifiers

@MainActor
final class AppModel: ObservableObject {
    enum Phase: String { case ready, analyzing, review, exporting, done }
    @Published var phase: Phase = .ready
    @Published private(set) var workflowMode: WorkflowMode
    @Published private(set) var videoLanguage: VideoLanguage
    @Published var document: ReviewDocument? { didSet { rebuildPlaybackWords() } }
    @Published var selected: UUID?
    @Published var selectedAudioTrack = 0 { didSet { rebuildPlaybackWords() } }
    private var playbackWords: [ReviewWord] = []
    @Published var stage = "Preparing"
    @Published var fraction = 0.0
    @Published var progressIsEstimated = false
    @Published var stageElapsed = 0.0
    @Published var stageRemaining: Double?
    private var progressState = StageProgress()
    private var progressTask: Task<Void, Never>?
    @Published var error: String?
    @Published var sourceName = ""
    @Published var sound = "beep" {
        didSet {
            if sound != oldValue {
                defaults.set(sound, forKey: "censorSound")
                refreshCensoredPreview()
            }
        }
    }
    @Published private(set) var customSound: URL? { didSet { if customSound != oldValue { refreshCensoredPreview() } } }
    @Published private(set) var previewCensorship = true
    @Published private(set) var preparingPreview = false
    @Published private(set) var playingCensoredPreview = false
    @Published private(set) var loadingPlayer = false
    private var loadedSource: String?
    private var loadedTrack: Int?
    @Published private(set) var previewPreparation = "Preparing censored preview…"
    private let censoredPreview = CensoredPreview()
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
    private let defaults: UserDefaults
    private let supportDirectory: URL
    private var observer: Any?
    private var auditionEnd: Double?
    private var previewGeneration = UUID()
    private var undoDocuments: [ReviewDocument] = []
    private var pendingSource: URL?
    private var sourceAccess: SecurityScopedFile?
    private var pendingSourceAccess: SecurityScopedFile?
    private var exportAccess: SecurityScopedFile?
    private var publicationTask: Task<Void, Error>?
    private var returnHomeAfterCancel = false
    private var playerLoadTask: Task<Void, Never>?
    private var playerGeneration = UUID()

    static var support: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("bleep.ly", isDirectory: true)
    }
    static var defaultRoot: String {
        RuntimePaths.bundledRoot?.path ?? (Bundle.main.object(forInfoDictionaryKey: "BleepProjectRoot") as? String ?? FileManager.default.currentDirectoryPath)
    }
    var busy: Bool { phase == .analyzing || phase == .exporting }
    var canUndo: Bool { !undoDocuments.isEmpty }
    var root: URL {
        RuntimePaths.bundledRoot ?? URL(fileURLWithPath: defaults.string(forKey: "projectRoot") ?? Self.defaultRoot)
    }
    var python: URL {
        if RuntimePaths.isBundled(root) { return RuntimePaths.python(root: root) }
        let path = defaults.string(forKey: "pythonPath") ?? ""
        return path.isEmpty ? RuntimePaths.python(root: root) : URL(fileURLWithPath: path)
    }
    var visibleWords: [ReviewWord] {
        (document?.words ?? []).filter { ($0.audioTrack ?? document?.audioStream ?? 0) == selectedAudioTrack && (showAllWords || $0.isReviewCandidate) &&
            (search.isEmpty || $0.word.localizedCaseInsensitiveContains(search)) }
    }

    init(defaults: UserDefaults = .standard, supportDirectory: URL? = nil) {
        var migrationError: String?
        if defaults === UserDefaults.standard, supportDirectory == nil,
           let legacy = UserDefaults(suiteName: "ly.bleep.desktop.lab") {
            do {
                try LegacyLabMigration.migrate(defaults: defaults, directory: Self.support,
                    legacyDefaults: legacy, legacyDirectory: Self.support.deletingLastPathComponent().appendingPathComponent("bleep.ly Lab"))
            } catch { migrationError = "Could not import Lab data: \(error.localizedDescription)" }
        }
        WhisperKitExperiment.migratePreferences(defaults: defaults)
        self.defaults = defaults
        self.videoLanguage = VideoLanguage.selected(defaults: defaults)
        self.supportDirectory = supportDirectory ?? Self.support
        self.workflowMode = WorkflowMode(rawValue: defaults.string(forKey: "workflowMode") ?? "") ?? .fast
        self.customSound = SavedCensorSound(directory: self.supportDirectory, defaults: defaults).url
        let savedSound = defaults.string(forKey: "censorSound") ?? "beep"
        self.sound = ["beep", "silence", "custom"].contains(savedSound) ? savedSound : "beep"
        if self.sound == "custom" && self.customSound == nil {
            self.sound = "beep"
            defaults.set("beep", forKey: "censorSound")
            self.error = "The saved custom sound is unavailable. Choose it again."
        }
        if let migrationError { self.error = migrationError }
        observer = player.addPeriodicTimeObserver(forInterval: CMTime(seconds: 0.04, preferredTimescale: 600), queue: .main) { [weak self] time in
            Task { @MainActor in
                guard let self, self.player.currentItem != nil else { return }
                self.playhead = max(0, time.seconds.isFinite ? time.seconds : 0)
                if self.player.rate != 0 { self.followPlayback(at: self.playhead) }
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

    func selectLanguage(_ language: VideoLanguage) {
        guard !busy, language != videoLanguage else { return }
        videoLanguage = language
        defaults.set(language.rawValue, forKey: "videoLanguage")
        let currentBackend = WhisperKitExperiment.backend(defaults: defaults)
        #if arch(arm64)
        let recommended: RecognitionModel = language == .russian ? .gigaAM : .turbo
        let backend = language == .russian || currentBackend != "faster-whisper" ? "mlx" : "faster-whisper"
        #else
        let recommended: RecognitionModel = language == .russian ? .largeV3 : .turbo
        let backend = "faster-whisper"
        #endif
        defaults.set(backend, forKey: "backend")
        defaults.set(recommended.rawValue, forKey: "recognitionModel")
    }

    @discardableResult
    func open(_ url: URL, transcript: URL? = nil, workflow: WorkflowMode? = nil, replacingTrack: Int? = nil) -> Task<Void, Never>? {
        guard !busy else { return nil }
        let selectedMode = workflow ?? (transcript == nil ? workflowMode : .advanced)
        if selectedMode == .fast && sound == "custom" && customSound == nil {
            error = "Choose a custom censor sound before opening media, or select Beep or Silence."
            return nil
        }
        selectMode(selectedMode)
        let previousDocument = document
        let selectedBackend = WhisperKitExperiment.backend(defaults: defaults)
        let selectedLanguage = VideoLanguage.selected(defaults: defaults)
        let selectedWordLists = WordListPreferences.request(selectedLanguage, defaults: defaults)
        let selectedRecognitionModel = RecognitionModel.requested(defaults: defaults, backend: selectedBackend)
        let recognitionBackend = RecognitionModel.engine(model: selectedRecognitionModel, selected: selectedBackend)
        let experimental = transcript == nil && recognitionBackend != selectedBackend
        let recognitionPython = experimental && (RuntimePaths.isBundled(root) || (defaults.string(forKey: "pythonPath") ?? "").isEmpty)
            ? RuntimePaths.python(root: root, experimental: true) : python
        // A new source deliberately starts a fresh review; the last draft stays on disk until success.
        pause()
        playerLoadTask?.cancel(); playerGeneration = UUID()
        player.replaceCurrentItem(with: nil)
        censoredPreview.clear(); preparingPreview = false; loadingPlayer = false; playingCensoredPreview = false
        loadedSource = nil; loadedTrack = nil
        pendingSource = url
        let access = SecurityScopedFile(url)
        pendingSourceAccess = access
        let transcriptAccess = transcript.map(SecurityScopedFile.init)
        sourceName = url.lastPathComponent
        stage = "Reading media"
        fraction = 0
        cancelling = false
        error = nil
        phase = .analyzing
        beginProgressUpdates()
        return Task {
            defer {
                withExtendedLifetime(transcriptAccess) {}
                progressTask?.cancel(); progressTask = nil; progressIsEstimated = false; stageElapsed = 0; stageRemaining = nil
                if returnHomeAfterCancel { returnHomeAfterCancel = false; startNewFile() }
            }
            if cancelling {
                restoreReviewAfterOpenFailure()
                cancelling = false
                return
            }
            do {
                var request: [String: Any] = ["operation": "analyze", "source": url.path,
                    "cache_dir": supportDirectory.appendingPathComponent("cache").path,
                    "app_cache_identity": try RuntimePaths.recognitionCacheIdentity(),
                    "history_dir": RuntimePaths.history(root: root, support: supportDirectory).path,
                    "backend": recognitionBackend,
                    "model": selectedRecognitionModel,
                    "language": selectedLanguage.rawValue,
                    "word_lists": selectedWordLists,
                    "censor_style": defaults.string(forKey: "censorStyle") ?? "middle",
                    "offline": !defaults.bool(forKey: "allowDownloads")]
                if let replacingTrack { request["audio_stream"] = replacingTrack }
                if request["backend"] as? String == "whisperkit", transcript == nil {
                    request["whisperkit_executable"] = WhisperKitExperiment.helper.path
                    request["whisperkit_model_folder"] = RuntimePaths.models(root: root, support: supportDirectory).appendingPathComponent("whisperkit/model").path
                }
                if let transcript { request["transcript"] = transcript.path }
                if experimental && !FileManager.default.isExecutableFile(atPath: recognitionPython.path) {
                    throw BridgeFailure(message: "Install experimental GPU models with: bash scripts/setup-experimental-gpu.sh")
                }
                let result = try await bridge.run(root: root, python: recognitionPython, request: request, progress: updateProgress, timing: { self.progressState.duration = $0 })
                let analyzed = try JSONDecoder.bridge.decode(ReviewDocument.self, from: result)
                if let replacingTrack, var previous = previousDocument, previous.source == analyzed.source {
                    guard previous.fingerprint == analyzed.fingerprint else {
                        throw BridgeFailure(message: "Source changed since analysis. Open it again before importing a track.")
                    }
                    let fallbackTrack = previous.audioStream ?? 0
                    previous.words.removeAll { ($0.audioTrack ?? fallbackTrack) == replacingTrack }
                    previous.words += analyzed.words
                    document = previous
                } else { document = analyzed }
                sourceAccess = access
                pendingSourceAccess = nil
                selectedAudioTrack = replacingTrack ?? document?.audioTracks.first?.index ?? 0
                undoDocuments = []
                hasEdits = false
                selected = document?.words.first(where: \.profane)?.id
                exportFormat = document?.hasVideo == true ? "video" : "audio"
                exportURL = nil
                playhead = 0
                if selectedMode == .advanced { preparePlayer() }
                saveDraft()
                phase = .review
            } catch {
                if !cancelling { self.error = error.localizedDescription }
                restoreReviewAfterOpenFailure()
            }
            cancelling = false
        }
    }

    private func restoreReviewAfterOpenFailure() {
        phase = document == nil ? .ready : .review
        guard let document else { return }
        sourceName = document.url.lastPathComponent
        // Opening cleared the player, but a failed/cancelled attempt retains the review.
        if workflowMode == .advanced && !returnHomeAfterCancel { preparePlayer() }
    }

    func selectMode(_ mode: WorkflowMode) {
        guard !busy else { return }
        pause()
        workflowMode = mode
        defaults.set(mode.rawValue, forKey: "workflowMode")
        if mode == .advanced && document != nil { preparePlayer() }
        else if mode == .fast {
            playerLoadTask?.cancel(); playerGeneration = UUID(); censoredPreview.cancel(); preparingPreview = false; loadingPlayer = false
        }
    }

    func goHome() {
        if busy {
            returnHomeAfterCancel = true
            cancel()
        } else {
            startNewFile()
        }
    }

    func stopPreviewForTermination() async {
        let task = playerLoadTask
        playerLoadTask = nil
        task?.cancel(); playerGeneration = UUID()
        pause(); player.replaceCurrentItem(with: nil)
        censoredPreview.clear()
        preparingPreview = false; loadingPlayer = false; playingCensoredPreview = false
        await task?.value
    }

    func startNewFile() {
        guard !busy else { return }
        pause()
        playerLoadTask?.cancel(); playerGeneration = UUID()
        player.replaceCurrentItem(with: nil)
        censoredPreview.clear(); preparingPreview = false; loadingPlayer = false; playingCensoredPreview = false
        loadedSource = nil; loadedTrack = nil
        selectedAudioTrack = 0
        document = nil; selected = nil; exportURL = nil; error = nil
        undoDocuments = []; pendingSource = nil; sourceName = ""
        sourceAccess = nil; pendingSourceAccess = nil; exportAccess = nil
        search = ""; showAllWords = false; hasEdits = false
        fraction = 0; stage = "Preparing"; playhead = 0
        phase = .ready
    }

    private func beginProgressUpdates() {
        progressTask?.cancel()
        progressState = StageProgress()
        progressState.report(stage, fraction: 0, now: ProcessInfo.processInfo.systemUptime)
        progressTask = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 200_000_000)
                guard !Task.isCancelled, let self, self.busy else { return }
                let now = ProcessInfo.processInfo.systemUptime
                self.stageElapsed = max(0, now - self.progressState.started)
                guard !self.cancelling else { continue }
                self.progressState.advance(now: now)
                self.stageRemaining = self.progressState.displayRemaining(now: now)
                self.fraction = self.progressState.displayed
                self.progressIsEstimated = self.progressState.estimated
            }
        }
    }

    func updateProgress(_ label: String, _ value: Double) {
        guard busy, !cancelling else { return }
        progressState.report(label, fraction: value, now: ProcessInfo.processInfo.systemUptime)
        stage = label
        let now = ProcessInfo.processInfo.systemUptime
        stageElapsed = max(0, now - progressState.started)
        stageRemaining = progressState.displayRemaining(now: now)
        fraction = progressState.displayed
        progressIsEstimated = progressState.estimated
    }

    private func rebuildPlaybackWords() {
        playbackWords = (document?.words ?? []).filter {
            $0.profane && ($0.audioTrack ?? document?.audioStream ?? 0) == selectedAudioTrack
        }.sorted { $0.muteStart < $1.muteStart }
    }

    /// Keep the latest heard censor interval selected, including between words.
    /// Binary search avoids walking a long transcript on every player tick.
    func followPlayback(at seconds: Double) {
        guard auditionEnd == nil, seconds.isFinite else { return }
        var lower = 0, upper = playbackWords.count
        while lower < upper {
            let middle = (lower + upper) / 2
            if playbackWords[middle].muteStart <= seconds { lower = middle + 1 }
            else { upper = middle }
        }
        let id = lower > 0 ? playbackWords[lower - 1].id : nil
        if selected != id { selected = id }
    }

    func cancel() { cancelling = true; stage = "Cancelling…"; bridge.cancel(); publicationTask?.cancel() }
    func pause() { previewGeneration = UUID(); player.pause(); isPlaying = false; auditionEnd = nil }
    func seek(_ seconds: Double) {
        pause()
        let value = min(document?.duration ?? 0, max(0, seconds))
        playhead = value
        followPlayback(at: value)
        player.seek(to: CMTime(seconds: value, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
    }
    func togglePlayback() {
        guard player.currentItem != nil else { return }
        if isPlaying { pause() } else {
            auditionEnd = nil
            if playhead >= (document?.duration ?? 0) - 0.05 { seek(0) }
            player.play(); isPlaying = true
        }
    }
    @discardableResult
    func setPreviewCensorship(_ enabled: Bool) -> Task<Void, Never>? {
        guard !busy else { return nil }
        if enabled && sound == "custom" && customSound == nil {
            error = "Choose a custom censor sound first."
            return nil
        }
        previewCensorship = enabled
        return preparePlayer()
    }

    private func refreshCensoredPreview() {
        guard previewCensorship, document != nil, workflowMode == .advanced, !busy else { return }
        preparePlayer()
    }

    @discardableResult
    func selectAudioTrack(_ index: Int) -> Task<Void, Never>? {
        guard document?.audioTracks.contains(where: { $0.index == index }) == true else { return nil }
        pause(); selectedAudioTrack = index; selected = nil
        return preparePlayer()
    }

    private func makePlayerItem(document: ReviewDocument, track index: Int, audioURL: URL? = nil) async throws -> AVPlayerItem {
        if document.audioCount == 1 && audioURL == nil { return AVPlayerItem(url: document.url) }
        let asset = AVURLAsset(url: document.url)
        let audio = try await asset.loadTracks(withMediaType: .audio)
        let video = try await asset.loadTracks(withMediaType: .video)
        guard audio.indices.contains(index) else { throw BridgeFailure(message: "Audio track is unavailable.") }
        let composition = AVMutableComposition()
        var origin = CMTime.zero
        if let sourceVideo = video.first, document.hasVideo {
            let range = try await sourceVideo.load(.timeRange)
            origin = range.start
            let target = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)
            try target?.insertTimeRange(range, of: sourceVideo, at: .zero)
            target?.preferredTransform = try await sourceVideo.load(.preferredTransform)
        }
        let audioAsset = audioURL.map { AVURLAsset(url: $0) } ?? asset
        let sourceAudio: AVAssetTrack
        if audioURL != nil {
            let rendered = try await audioAsset.loadTracks(withMediaType: .audio)
            guard let first = rendered.first else { throw BridgeFailure(message: "Preview audio is unavailable.") }
            sourceAudio = first
        } else { sourceAudio = audio[index] }
        let audioOrigin = audioURL == nil ? origin : CMTime.zero
        let range = try await sourceAudio.load(.timeRange)
        let start = CMTimeMaximum(range.start, audioOrigin)
        let end = CMTimeMinimum(range.end, audioOrigin + CMTime(seconds: document.duration, preferredTimescale: 600))
        if end > start {
            let target = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)
            try target?.insertTimeRange(CMTimeRange(start: start, end: end), of: sourceAudio, at: start - audioOrigin)
        }
        withExtendedLifetime(audioAsset) {}
        return AVPlayerItem(asset: composition)
    }

    private func installPlayerItem(_ item: AVPlayerItem, document: ReviewDocument, track: Int,
                                   censored: Bool, generation: UUID) async {
        guard !Task.isCancelled, playerGeneration == generation else { return }
        // Capture the position at handoff, not where playback was when rendering started.
        let position = playhead
        let resume = player.rate != 0
        let playbackToken = previewGeneration
        player.pause()
        player.replaceCurrentItem(with: item)
        loadedSource = document.source; loadedTrack = track
        playingCensoredPreview = censored
        let finished = await player.seek(to: CMTime(seconds: position, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
        guard finished, !Task.isCancelled, playerGeneration == generation, previewGeneration == playbackToken else { return }
        if resume { player.play(); isPlaying = true }
    }

    @discardableResult
    private func preparePlayer() -> Task<Void, Never>? {
        playerLoadTask?.cancel(); playerLoadTask = nil
        censoredPreview.cancel(); preparingPreview = false; loadingPlayer = false
        let generation = UUID(); playerGeneration = generation
        guard let document else { return nil }
        let index = selectedAudioTrack
        let censored = previewCensorship
        let selectedSound = sound
        let cue = customSound
        let cached = censored ? try? censoredPreview.cachedAudio(document: document, track: index, sound: selectedSound, customSound: cue) : nil
        preparingPreview = censored && cached == nil
        previewPreparation = playingCensoredPreview ? "Updating censored preview…" : "Preparing censored preview…"
        if loadedSource != document.source || loadedTrack != index {
            player.replaceCurrentItem(with: nil)
            playingCensoredPreview = false
        }
        loadingPlayer = true
        let task = Task { @MainActor in
            defer {
                if playerGeneration == generation { preparingPreview = false; loadingPlayer = false }
            }
            do {
                if let cached {
                    let item = try await makePlayerItem(document: document, track: index, audioURL: cached)
                    await installPlayerItem(item, document: document, track: index, censored: true, generation: generation)
                    return
                }
                if player.currentItem == nil || (playingCensoredPreview && !censored) {
                    let original = try await makePlayerItem(document: document, track: index)
                    await installPlayerItem(original, document: document, track: index, censored: false, generation: generation)
                }
                guard !Task.isCancelled, playerGeneration == generation else { return }
                loadingPlayer = false
                guard censored else { return }
                // Keep current audio playable while preparing or patching the preview.
                try await Task.sleep(nanoseconds: 150_000_000)
                guard selectedSound != "custom" || cue != nil else {
                    throw BridgeFailure(message: "Choose a custom censor sound first.")
                }
                let url = try await censoredPreview.audio(document: document, track: index,
                    sound: selectedSound, customSound: cue, root: root, python: python) { [weak self] _, fraction in
                        guard let self, self.playerGeneration == generation else { return }
                        self.previewPreparation = "Updating censored preview · \(Int(fraction * 100))%"
                    }
                try Task.checkCancellation()
                let item = try await makePlayerItem(document: document, track: index, audioURL: url)
                await installPlayerItem(item, document: document, track: index, censored: true, generation: generation)
            } catch {
                if !Task.isCancelled && playerGeneration == generation {
                    self.error = "Could not prepare censored preview: \(error.localizedDescription)"
                    if playingCensoredPreview, let original = try? await makePlayerItem(document: document, track: index) {
                        await installPlayerItem(original, document: document, track: index, censored: false, generation: generation)
                    }
                }
            }
        }
        playerLoadTask = task
        return task
    }

    func audition(_ word: ReviewWord) {
        pause()
        let track = word.audioTrack ?? document?.audioStream ?? 0
        if track != selectedAudioTrack { selectAudioTrack(track) }
        selected = word.id
        let context = word.contextRange(duration: document?.duration ?? word.end)
        auditionEnd = context.upperBound
        let token = UUID(); previewGeneration = token
        Task { @MainActor in
            while loadingPlayer && previewGeneration == token { try? await Task.sleep(nanoseconds: 20_000_000) }
            guard previewGeneration == token, player.currentItem != nil else { return }
            player.seek(to: CMTime(seconds: context.lowerBound, preferredTimescale: 600),
                        toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] finished in
                Task { @MainActor in
                    guard let self, finished, self.previewGeneration == token else { return }
                    self.player.play(); self.isPlaying = true
                }
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
        refreshCensoredPreview()
    }
    func toggle(_ word: ReviewWord) {
        edit { value in
            if let index = value.words.firstIndex(where: { $0.id == word.id }) {
                value.words[index].reviewCandidate = true
                value.words[index].profane.toggle()
            }
        }
    }
    func undo() {
        guard !busy, let previous = undoDocuments.popLast() else { return }
        document = previous; exportURL = nil; phase = .review; saveDraft()
        refreshCensoredPreview()
    }
    func addInterval(label: String, start: Double, end: Double) {
        guard document?.validateInterval(start: start, end: end) == true else { return }
        let word = ReviewWord(word: label.isEmpty ? "Manual interval" : label, start: start, end: end,
                              profane: true, muteStart: start, muteEnd: end, audioTrack: selectedAudioTrack)
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
            try FileManager.default.createDirectory(at: supportDirectory, withIntermediateDirectories: true)
            if SandboxFiles.enabled, let sourceAccess {
                try SandboxFiles.saveBookmark(for: sourceAccess.url, to: supportDirectory.appendingPathComponent("last-source.bookmark"))
            }
            try JSONEncoder.bridge.encode(document).write(to: supportDirectory.appendingPathComponent("last-review.json"), options: .atomic)
        } catch { self.error = "Could not save your review: \(error.localizedDescription)" }
    }
    func restoreDraft() {
        guard !busy else { return }
        do {
            let data = try Data(contentsOf: supportDirectory.appendingPathComponent("last-review.json"))
            let restored = try JSONDecoder.bridge.decode(ReviewDocument.self, from: data)
            let access = try SandboxFiles.enabled
                ? SandboxFiles.restoreBookmark(from: supportDirectory.appendingPathComponent("last-source.bookmark"), expected: restored.url)
                : SecurityScopedFile(restored.url)
            guard FileManager.default.fileExists(atPath: restored.source) else {
                throw BridgeFailure(message: "The original media has moved. Open it again.")
            }
            selectMode(.advanced)
            sourceAccess = access
            pause(); document = restored; undoDocuments = []; selected = nil
            sourceName = restored.url.lastPathComponent
            selectedAudioTrack = restored.audioTracks.first?.index ?? 0
            preparePlayer()
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
        if panel.runModal() == .OK, let url = panel.url {
            open(source, transcript: url, replacingTrack: (document?.audioTracks.count ?? 0) > 1 ? selectedAudioTrack : nil)
        }
    }
    func chooseSound() {
        chooseSound { panel in panel.runModal() == .OK ? panel.url : nil }
    }
    func chooseSound(chooseFile: @MainActor (NSOpenPanel) -> URL?) {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.audio]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        if let url = chooseFile(panel) { setSound(url) }
    }
    func setSound(_ url: URL) {
        do {
            customSound = try SavedCensorSound(directory: supportDirectory, defaults: defaults).save(url)
            sound = "custom"
            error = nil
        } catch { self.error = "Could not save the custom sound: \(error.localizedDescription)" }
    }

    func export() {
        export(as: exportFormat)
    }

    @discardableResult
    func export(as format: String, chooseDestination: @MainActor (NSSavePanel) -> URL? = { panel in
        panel.runModal() == .OK ? panel.url : nil
    }) -> Task<Void, Never>? {
        guard !busy, let document else { return nil }
        guard format == "audio" || (format == "video" && document.hasVideo) else {
            error = "Choose an available export format."; return nil
        }
        if sound == "custom" && customSound == nil { chooseSound(); return nil }
        let panel = NSSavePanel()
        let video = format == "video"
        panel.allowedContentTypes = video ? [.quickTimeMovie, .mpeg4Movie, UTType(filenameExtension: "mkv") ?? .movie] : [.wav]
        panel.title = video ? "Save as Video" : "Save as Audio"
        let suggested = document.suggestedOutputURL(format: format)
        panel.directoryURL = suggested.deletingLastPathComponent()
        panel.nameFieldStringValue = suggested.lastPathComponent
        panel.message = video ? "The original video stream is copied without re-encoding." : "48 kHz · 24-bit stereo WAV"
        guard let destination = chooseDestination(panel) else { return nil }
        if FileManager.default.fileExists(atPath: destination.path) {
            error = "Choose a new filename. Existing files are kept intact."; return nil
        }
        return beginExport(to: destination, format: format)
    }

    @discardableResult
    func beginExport(to destination: URL, format: String) -> Task<Void, Never>? {
        guard !busy, let document else { return nil }
        guard sound != "custom" || customSound != nil else {
            error = "Choose a custom censor sound first."; return nil
        }
        let selectedSound = sound
        let selectedCustomSound = customSound
        let destinationAccess = SecurityScopedFile(destination)
        error = nil; exportURL = nil
        // Set busy synchronously so two clicks cannot launch competing exports.
        pause(); phase = .exporting; cancelling = false
        beginProgressUpdates()
        return Task {
            defer {
                withExtendedLifetime(destinationAccess) {}
                progressTask?.cancel(); progressTask = nil; progressIsEstimated = false; stageElapsed = 0; stageRemaining = nil
                if returnHomeAfterCancel { returnHomeAfterCancel = false; startNewFile() }
            }
            if cancelling { phase = .review; cancelling = false; return }
            do {
                try await render(document, to: destination, format: format, sound: selectedSound, customSound: selectedCustomSound)
                exportAccess = destinationAccess
            } catch {
                if !cancelling { self.error = error.localizedDescription }
                phase = .review
            }
            cancelling = false
        }
    }

    private func render(_ document: ReviewDocument, to destination: URL, format: String,
                        sound: String, customSound: URL?) async throws {
        pause()
        playerLoadTask?.cancel(); playerGeneration = UUID(); censoredPreview.cancel(); preparingPreview = false; loadingPlayer = false
        phase = .exporting
        updateProgress("Preparing export", 0)
        let staging = FileManager.default.temporaryDirectory.appendingPathComponent("bleep-save-\(UUID())")
        if SandboxFiles.enabled { try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true) }
        defer { if SandboxFiles.enabled { try? FileManager.default.removeItem(at: staging) } }
        let output = SandboxFiles.enabled ? staging.appendingPathComponent(destination.lastPathComponent) : destination
        var request: [String: Any] = ["operation": "export", "output": output.path,
            "format": format, "sound": sound,
            "document": try JSONSerialization.jsonObject(with: JSONEncoder.bridge.encode(document))]
        if let customSound { request["custom_sound"] = customSound.path }
        _ = try await bridge.run(root: root, python: python, request: request, progress: updateProgress, timing: { self.progressState.duration = $0 })
        if SandboxFiles.enabled {
            try Task.checkCancellation()
            if cancelling { throw CancellationError() }
            updateProgress("Saving export", 0)
            let task = Task.detached { try SandboxFiles.publish(output, to: destination) }
            publicationTask = task
            defer { publicationTask = nil }
            try await task.value
        }
        exportURL = destination; phase = .done
    }
}
