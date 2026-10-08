import SwiftUI
import AVKit
import UniformTypeIdentifiers

struct ContentView: View {
    @ObservedObject var model: AppModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @State private var dropTarget = false
    @State private var showInterval = false
    @State private var editingWord: ReviewWord?

    private var tint: Color {
        switch model.phase {
        case .ready: return Color(red: 0.12, green: 0.47, blue: 0.85)
        case .analyzing: return Color(red: 0.48 + model.fraction * 0.12, green: 0.28, blue: 0.8)
        case .review: return Color(red: 0.26, green: 0.42, blue: 0.64)
        case .exporting: return Color(red: 0.17, green: 0.56, blue: 0.66)
        case .done: return Color(red: 0.16, green: 0.60, blue: 0.43)
        }
    }
    var body: some View {
        ZStack {
            Color(red: 0.035, green: 0.055, blue: 0.11)
            RadialGradient(colors: [tint.opacity(reduceTransparency ? 0.3 : 0.48), .clear],
                           center: .topLeading, startRadius: 30, endRadius: 950)
            RadialGradient(colors: [tint.opacity(0.20), .clear], center: .bottomTrailing, startRadius: 0, endRadius: 650)
            VStack(spacing: 0) {
                header
                if model.busy { processing }
                else if let document = model.document { review(document) }
                else { welcome }
            }.padding(30)
        }
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.65), value: tint)
        .preferredColorScheme(.dark)
        .tint(.mint)
        .frame(minWidth: 880, minHeight: 690)
        .alert("Couldn’t complete the operation", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("OK", role: .cancel) { model.error = nil }
        } message: { Text(model.error ?? "") }
        .sheet(isPresented: $showInterval) {
            IntervalEditor(model: model, word: editingWord)
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: "waveform").font(.title2.weight(.semibold)).foregroundStyle(.mint)
            Text("bleep.ly").font(.system(size: 24, weight: .bold, design: .rounded)).tracking(-0.7)
            Text("A little less explicit.").font(.callout).foregroundStyle(.secondary).padding(.leading, 12)
            Spacer()
            if model.document != nil && !model.busy {
                Button(action: model.chooseSource) { Label("Open", systemImage: "plus") }.buttonStyle(.borderless)
            }
            SettingsLink { Image(systemName: "slider.horizontal.3").font(.title3) }
                .buttonStyle(.borderless).help("Local engine settings")
                .disabled(model.busy)
        }.padding(.top, 10).padding(.bottom, 28)
    }

    private var welcome: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 10)
            VStack(spacing: 26) {
                ZStack {
                    Circle().fill(.white.opacity(0.045)).frame(width: 112, height: 112)
                    Image(systemName: dropTarget ? "arrow.down.circle.fill" : "waveform.badge.plus")
                        .font(.system(size: 43, weight: .light)).foregroundStyle(.mint)
                }
                VStack(spacing: 12) {
                    Text("Drop your video or audio here")
                        .font(.system(size: 30, weight: .semibold)).tracking(-0.7)
                    Text("Keep the story. Clean up the language.")
                        .font(.system(size: 16)).foregroundStyle(.secondary)
                }
                Button("Choose a file…", action: model.chooseSource)
                    .buttonStyle(.borderedProminent).controlSize(.large)
                Text("MOV, MP4, WAV, MP3 and more").font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, minHeight: 370)
            .background(.white.opacity(dropTarget ? 0.09 : 0.025), in: RoundedRectangle(cornerRadius: 28))
            .overlay(RoundedRectangle(cornerRadius: 28).strokeBorder(dropTarget ? Color.mint : .white.opacity(0.17), style: StrokeStyle(lineWidth: 1.5, dash: [7, 7])))
            .dropDestination(for: URL.self) { urls, _ in
                guard let url = urls.first, url.isFileURL, urls.count == 1 else { return false }
                model.open(url); return true
            } isTargeted: { dropTarget = $0 }
            HStack(spacing: 32) {
                Label("On-device recognition", systemImage: "lock.shield")
                Label("Review every word", systemImage: "waveform.path")
                Label("Original video quality", systemImage: "film")
            }.font(.callout).foregroundStyle(.secondary)
            Button("Resume last review", action: model.restoreDraft).buttonStyle(.plain).foregroundStyle(.mint)
            Spacer(minLength: 10)
            Text("Made for the final cut.").font(.caption).foregroundStyle(.secondary)
        }
    }

    private var processing: some View {
        VStack(spacing: 28) {
            Spacer()
            ZStack {
                Circle().stroke(.white.opacity(0.08), lineWidth: 8)
                Circle().trim(from: 0, to: max(0.015, model.fraction))
                    .stroke(.mint, style: StrokeStyle(lineWidth: 8, lineCap: .round)).rotationEffect(.degrees(-90))
                Image(systemName: model.phase == .exporting ? "arrow.up.doc" : "waveform")
                    .font(.system(size: 44, weight: .light)).foregroundStyle(.mint)
            }.frame(width: 140, height: 140)
            VStack(spacing: 10) {
                Text(model.phase == .exporting ? "Making the clean cut." : "Listening for the little slips.")
                    .font(.system(size: 30, weight: .semibold)).tracking(-0.7)
                Text(model.sourceName).foregroundStyle(.secondary)
            }
            VStack(spacing: 8) {
                Text(model.stage).font(.headline)
                if model.fraction > 0 {
                    Text("\(Int(model.fraction * 100))% of this stage").monospacedDigit().foregroundStyle(.secondary)
                } else { ProgressView().controlSize(.small) }
            }.frame(height: 48)
            Text(model.phase == .analyzing ? "Audio stays on your Mac. The first model load can take a moment." : "Your review and original media are kept intact.")
                .font(.callout).foregroundStyle(.secondary)
            Button("Cancel", action: model.cancel).disabled(model.cancelling)
            Spacer()
        }.frame(maxWidth: .infinity)
    }

    private func review(_ document: ReviewDocument) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 7) {
                    HStack(spacing: 10) {
                        Text(document.url.lastPathComponent).lineLimit(1).truncationMode(.middle)
                        Text("— \(clockText(document.duration))").foregroundStyle(.secondary)
                    }.font(.system(size: 25, weight: .semibold)).tracking(-0.5)
                    Text(document.count == 0 ? "No words selected for censoring. Review the transcript or add an interval." :
                            "Found \(document.count) potentially explicit \(document.count == 1 ? "word" : "words").")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Label("Ready to review", systemImage: "checkmark.circle.fill")
                    .font(.caption.weight(.medium)).foregroundStyle(.mint)
            }
            HStack(alignment: .top, spacing: 20) {
                VStack(spacing: 12) {
                    if document.hasVideo {
                        VideoPlayer(player: model.player).frame(minHeight: 150, maxHeight: .infinity)
                            .clipShape(RoundedRectangle(cornerRadius: 16))
                    } else {
                        VStack(spacing: 14) {
                            Image(systemName: "waveform").font(.system(size: 48, weight: .ultraLight)).foregroundStyle(.mint)
                            Text("Audio Only").foregroundStyle(.secondary)
                        }.frame(maxWidth: .infinity, maxHeight: .infinity)
                            .background(.black.opacity(0.2), in: RoundedRectangle(cornerRadius: 16))
                    }
                    HStack {
                        Button(action: model.togglePlayback) {
                            Label(model.isPlaying ? "Pause" : "Play", systemImage: model.isPlaying ? "pause.fill" : "play.fill")
                        }.buttonStyle(.borderless)
                        Text(clockText(model.playhead)).monospacedDigit().font(.caption)
                        Spacer()
                        Text("Original audio preview").font(.caption).foregroundStyle(.secondary)
                    }
                }.frame(maxWidth: .infinity)
                wordList(document).frame(width: 345)
            }.frame(minHeight: 210, maxHeight: .infinity)
            timeline(document)
            if let url = model.exportURL {
                HStack {
                    Label("Your clean cut is ready.", systemImage: "checkmark.circle.fill").foregroundStyle(.mint)
                    Spacer()
                    Button("Play export") { NSWorkspace.shared.open(url) }
                    Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([url]) }
                }.padding(12).background(.mint.opacity(0.1), in: RoundedRectangle(cornerRadius: 12))
            }
            exportControls(document)
        }
    }

    private func wordList(_ document: ReviewDocument) -> some View {
        VStack(spacing: 10) {
            HStack {
                Text("REVIEW WORDS").font(.caption.weight(.semibold)).tracking(1.2).foregroundStyle(.secondary)
                Spacer()
                Button { editingWord = nil; showInterval = true } label: { Image(systemName: "plus") }
                    .help("Add a missed interval")
                Button(action: model.undo) { Image(systemName: "arrow.uturn.backward") }.disabled(!model.canUndo).help("Undo")
            }
            Picker("Show", selection: $model.showAllWords) {
                Text("Flagged").tag(false); Text("All words").tag(true)
            }.pickerStyle(.segmented)
            TextField("Search transcript", text: $model.search).textFieldStyle(.roundedBorder)
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 4) {
                        if model.visibleWords.isEmpty {
                            Text("Nothing here. Switch to All words or add a missed interval.")
                                .font(.callout).foregroundStyle(.secondary).padding(18)
                        }
                        ForEach(model.visibleWords) { word in
                            HStack(spacing: 9) {
                                Button { model.audition(word) } label: {
                                    HStack {
                                        Image(systemName: "play.circle").foregroundStyle(.mint)
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text(word.word).lineLimit(1)
                                            Text("\(clockText(word.start)) · \(word.muteEnd - word.muteStart, specifier: "%.2f")s muted")
                                                .font(.caption2).foregroundStyle(.secondary).monospacedDigit()
                                        }
                                        Spacer(minLength: 0)
                                    }.contentShape(Rectangle())
                                }.buttonStyle(.plain).help("Listen in context")
                                Button { editingWord = word; showInterval = true } label: {
                                    Image(systemName: "slider.horizontal.3").foregroundStyle(.secondary)
                                }.buttonStyle(.borderless).help("Adjust mute timing")
                                Toggle("Censor \(word.word)", isOn: Binding(get: { word.profane }, set: { _ in model.toggle(word) }))
                                    .labelsHidden().toggleStyle(.checkbox)
                            }.padding(10)
                                .background(model.selected == word.id ? .white.opacity(0.1) : .clear, in: RoundedRectangle(cornerRadius: 9))
                                .id(word.id)
                        }
                    }
                }.onChange(of: model.selected) { _, id in if let id { proxy.scrollTo(id, anchor: .center) } }
            }
        }.padding(14).background(.black.opacity(0.15), in: RoundedRectangle(cornerRadius: 16))
    }

    private func timeline(_ document: ReviewDocument) -> some View {
        VStack(spacing: 8) {
            HStack {
                Text("CENSOR TIMELINE").font(.caption.weight(.semibold)).tracking(1.2)
                Spacer()
                Label("Selected intervals", systemImage: "rectangle.fill").font(.caption).foregroundStyle(.orange.opacity(0.9))
                Button("Add interval") { editingWord = nil; showInterval = true }.buttonStyle(.borderless)
            }.foregroundStyle(.secondary)
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 8).fill(.white.opacity(0.045))
                    Path { path in
                        for step in 0...40 {
                            let x = geo.size.width * Double(step) / 40
                            path.move(to: CGPoint(x: x, y: step % 5 == 0 ? 22 : 34))
                            path.addLine(to: CGPoint(x: x, y: 46))
                        }
                    }.stroke(.white.opacity(0.14), lineWidth: 1)
                    ForEach(document.words.filter(\.profane)) { word in
                        Button { model.audition(word) } label: {
                            RoundedRectangle(cornerRadius: 3)
                                .fill(model.selected == word.id ? Color.mint : Color.orange.opacity(0.85))
                                .frame(width: max(5, geo.size.width * (word.muteEnd - word.muteStart) / document.duration), height: 30)
                        }.buttonStyle(.plain)
                            .offset(x: min(geo.size.width - 5, geo.size.width * word.muteStart / document.duration))
                            .help("\(word.word) · \(clockText(word.start))")
                            .accessibilityLabel("Preview \(word.word) at \(clockText(word.start))")
                    }
                    Rectangle().fill(.white).frame(width: 1.5, height: 48)
                        .offset(x: geo.size.width * min(1, model.playhead / document.duration)).allowsHitTesting(false)
                }
            }.frame(height: 48)
            Slider(value: Binding(get: { min(document.duration, model.playhead) }, set: { model.seek($0) }), in: 0...document.duration)
                .accessibilityLabel("Playback position")
            HStack { Text("0:00"); Spacer(); Text(clockText(document.duration)) }
                .font(.caption2).monospacedDigit().foregroundStyle(.secondary)
        }
    }

    private func exportControls(_ document: ReviewDocument) -> some View {
        HStack(alignment: .center, spacing: 22) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Censor sound").font(.caption).foregroundStyle(.secondary)
                Picker("Censor sound", selection: $model.sound) {
                    Text("Beep").tag("beep"); Text("Silence").tag("silence"); Text("Custom").tag("custom")
                }.labelsHidden().pickerStyle(.segmented).frame(width: 250)
                Button(action: model.chooseSound) {
                    Text(model.customSound?.lastPathComponent ?? "Drop a sound here or choose…").lineLimit(1).truncationMode(.middle)
                }.buttonStyle(.borderless).font(.caption)
                    .frame(width: 250, alignment: .leading)
                    .dropDestination(for: URL.self) { urls, _ in
                        guard urls.count == 1, let url = urls.first, url.isFileURL else { return false }
                        model.setSound(url); return true
                    }
            }
            VStack(alignment: .leading, spacing: 8) {
                Text("Export as").font(.caption).foregroundStyle(.secondary)
                Picker("Export format", selection: $model.exportFormat) {
                    Text("Audio Only").tag("audio")
                    if document.hasVideo { Text("Video").tag("video") }
                }.labelsHidden().pickerStyle(.segmented).frame(width: 200)
                Text(model.exportFormat == "video" ? "Original video · no re-encoding" : "WAV · 48 kHz · 24-bit stereo")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            Button(action: model.export) { Label("Export", systemImage: "square.and.arrow.up").frame(minWidth: 96) }
                .buttonStyle(.borderedProminent).controlSize(.large).keyboardShortcut("e", modifiers: .command)
                .disabled(model.sound == "custom" && model.customSound == nil)
        }.padding(18).background(.white.opacity(0.045), in: RoundedRectangle(cornerRadius: 18))
    }
}

struct IntervalEditor: View {
    @ObservedObject var model: AppModel
    var word: ReviewWord?
    @Environment(\.dismiss) private var dismiss
    @State private var label = ""
    @State private var start = 0.0
    @State private var end = 0.0
    var valid: Bool { model.document?.validateInterval(start: start, end: end) == true }
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(word == nil ? "Add a missed interval" : "Adjust mute timing").font(.title2.bold())
            TextField("Word or note", text: $label).disabled(word != nil)
            HStack {
                TextField("Start (seconds)", value: $start, format: .number.precision(.fractionLength(3)))
                TextField("End (seconds)", value: $end, format: .number.precision(.fractionLength(3)))
            }
            Text("These exact seconds will be muted. The selected sound plays once at its original speed; its tail can continue over speech.")
                .font(.callout).foregroundStyle(.secondary)
            if !valid { Text("Use 0 ≤ start < end ≤ media duration.").foregroundStyle(.orange).font(.caption) }
            HStack {
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Spacer()
                Button("Save interval") {
                    if let word { model.updateInterval(id: word.id, start: start, end: end) }
                    else { model.addInterval(label: label, start: start, end: end) }
                    dismiss()
                }.buttonStyle(.borderedProminent).disabled(!valid).keyboardShortcut(.defaultAction)
            }
        }.padding(28).frame(width: 450)
            .onAppear {
                label = word?.word ?? ""
                start = word?.muteStart ?? min(model.playhead, max(0, (model.document?.duration ?? 1) - 0.1))
                end = word?.muteEnd ?? min(model.document?.duration ?? 1, start + 0.3)
            }
    }
}
