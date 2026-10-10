import SwiftUI
import AppKit

@main
struct BleepApp: App {
    @StateObject private var model = AppModel()
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    var body: some Scene {
        Window("bleep.ly", id: "main") {
            ContentView(model: model)
                .onAppear { delegate.model = model; NSApp.activate(ignoringOtherApps: true) }
        }
        .defaultSize(width: 1120, height: 780)
        .windowStyle(.hiddenTitleBar)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Home", action: model.goHome).keyboardShortcut("h", modifiers: [.command, .shift])
                Button("Open Media…", action: model.chooseSource).keyboardShortcut("o").disabled(model.busy)
                Button("Resume Last Review", action: model.restoreDraft).disabled(model.busy)
                Button("Import Reviewed Transcript…", action: model.importTranscript).disabled(model.busy)
            }
            CommandGroup(replacing: .undoRedo) {
                Button("Undo Review Change", action: model.undo).keyboardShortcut("z").disabled(!model.canUndo || model.busy)
            }
        }
        Settings { SettingsView() }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    weak var model: AppModel?
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let model else { return .terminateNow }
        if model.busy { model.cancel() }
        Task { @MainActor in
            // Keep the bridge alive long enough to reap workers (and force-stop
            // native inference if it does not respond to the initial signal).
            while model.busy { try? await Task.sleep(nanoseconds: 50_000_000) }
            await model.stopPreviewForTermination()
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

struct SettingsView: View {
    @AppStorage("projectRoot") private var projectRoot = AppModel.defaultRoot
    @AppStorage("pythonPath") private var pythonPath = ""
    @AppStorage("backend") private var backend = "faster-whisper"
    @AppStorage("recognitionModel") private var recognitionModel = RecognitionModel.largeV3.rawValue
    @AppStorage("allowDownloads") private var allowDownloads = false
    @AppStorage("censorStyle") private var censorStyle = "middle"
    @AppStorage("videoLanguage") private var videoLanguage = "ru"
    @State private var showWordLists = false

    var body: some View {
        Form {
            Section("Recognition") {
                Picker("Engine", selection: $backend) {
                    Text("CPU · Classic processing").tag("faster-whisper")
                    Text("Apple GPU · MLX / MPS").tag("mlx")
                    Text("WhisperKit · Experimental").tag("whisperkit")
                }
                if backend == "whisperkit" {
                    Text("Core ML · less accurate in our test: 2–3/4 explicit words; MLX: 4/4.")
                        .font(.caption).foregroundStyle(.orange)
                    Text("Uses Large v3 Turbo (~1.7 GB download). First run may take a few minutes.")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    Text(backend == "mlx" ? "Faster · GPU recognition" : "Classic · CPU recognition")
                        .font(.caption).foregroundStyle(.secondary)
                    Picker("Model · testing", selection: $recognitionModel) {
                        ForEach(RecognitionModel.choices(backend: backend, language: VideoLanguage(rawValue: videoLanguage) ?? .russian), id: \.rawValue) { model in
                            Text(model.title).tag(model.rawValue)
                        }
                    }
                    Text("Applies to the next file; each model has its own cache. New GPU models are experimental; GigaAM uses MPS.")
                        .font(.caption).foregroundStyle(.secondary)
                    if videoLanguage == "en" {
                        Text("English selected on Home. GigaAM v3 is available for Russian only.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                Toggle("Allow first-time model download", isOn: $allowDownloads)
                Text("Runs locally. Applies to new files. With downloads off, the selected model must already be cached.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .onChange(of: backend) { _, value in
                if !RecognitionModel.choices(backend: value, language: VideoLanguage(rawValue: videoLanguage) ?? .russian).contains(where: { $0.rawValue == recognitionModel }), value != "whisperkit" {
                    recognitionModel = RecognitionModel.largeV3.rawValue
                }
            }
            Section("Censoring") {
                Button("Edit word lists…") { showWordLists = true }
                Text("Customize censored words and exceptions for Russian and English.")
                    .font(.caption).foregroundStyle(.secondary)
                Picker("Mute interval", selection: $censorStyle) {
                    Text("Word middle (default)").tag("middle")
                    Text("Whole word").tag("full")
                }
                Text("Applies when opening media. Whole word mutes from word start to end. Existing reviewed intervals stay unchanged; the sound always plays once at its original speed.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Local setup") {
                HStack {
                    TextField("Project folder", text: $projectRoot)
                    Button("Choose…") {
                        let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false
                        if panel.runModal() == .OK, let url = panel.url { projectRoot = url.path }
                    }
                }
                TextField("Python executable (optional)", text: $pythonPath)
                Text("By default, uses .venv/bin/python in your project folder. FFmpeg must be installed.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Audio tracks") {
                Text("All audio tracks are processed separately. Advanced shows each track for review; Video export keeps them separate. Audio Only exports a stereo mix.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped).padding(16).frame(width: 590, height: 550)
        .onAppear { WhisperKitExperiment.migratePreferences(defaults: .standard) }
        .sheet(isPresented: $showWordLists) {
            WordListEditor(root: URL(fileURLWithPath: projectRoot), language: VideoLanguage(rawValue: videoLanguage) ?? .russian)
        }
    }
}
