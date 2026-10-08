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
        guard let model, model.busy else { return .terminateNow }
        model.cancel()
        Task { @MainActor in
            // Keep the bridge alive long enough to reap workers (and force-stop
            // native inference if it does not respond to the initial signal).
            while model.busy { try? await Task.sleep(nanoseconds: 50_000_000) }
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
    @AppStorage("allowDownloads") private var allowDownloads = false
    @AppStorage("audioStream") private var audioStream = 0
    @AppStorage("censorStyle") private var censorStyle = "middle"

    var body: some View {
        Form {
            Section("Censoring") {
                Picker("Mute interval", selection: $censorStyle) {
                    Text("Word middle (default)").tag("middle")
                    Text("Whole word").tag("full")
                }
                Text("Applies when opening media. Whole word mutes from word start to end. Existing reviewed intervals stay unchanged; the sound always plays once at its original speed.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Local engine") {
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
                Picker("Recognition", selection: $backend) {
                    Text("CPU · faster-whisper").tag("faster-whisper")
                    Text("Apple GPU · MLX").tag("mlx")
                }
                Toggle("Allow first-time model download", isOn: $allowDownloads)
                Text("Russian speech · large-v3-turbo. Recognition runs on this Mac. With downloads off, the model must already be cached.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Audio track") {
                Picker("Track to process", selection: $audioStream) {
                    Text("Automatic (single track)").tag(0)
                    ForEach(1...16, id: \.self) { Text("Track \($0)").tag($0) }
                }
                Text("For media with multiple audio tracks, select one before opening. Only that track is exported, as stereo.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped).padding(16).frame(width: 590, height: 550)
    }
}
