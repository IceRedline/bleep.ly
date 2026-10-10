import SwiftUI

struct WordListDraft: Equatable {
    var censor: String
    var allow: String
}

enum WordListPreferences {
    static func builtIn(_ language: VideoLanguage, root: URL) throws -> WordListDraft {
        let filename = language == .russian ? "profanity.txt" : "profanity.en.txt"
        return WordListDraft(censor: try String(contentsOf: root.appendingPathComponent(filename), encoding: .utf8), allow: "")
    }

    static func load(_ language: VideoLanguage, root: URL, defaults: UserDefaults) throws -> WordListDraft {
        let censor = try defaults.string(forKey: "censorWords.\(language.rawValue)") ?? builtIn(language, root: root).censor
        return WordListDraft(censor: censor, allow: defaults.string(forKey: "allowedWords.\(language.rawValue)") ?? "")
    }

    static func validate(_ draft: WordListDraft, language: VideoLanguage) throws {
        let alphabet = language == .russian ? "А-Яа-яЁё" : "A-Za-z"
        for (name, text) in [("Censor words", draft.censor), ("Never censor", draft.allow)] {
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let entry = String(line.split(separator: "#", maxSplits: 1, omittingEmptySubsequences: false)[0])
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                if !entry.isEmpty && entry.range(of: "^[\(alphabet)]+\\*?$", options: .regularExpression) == nil {
                    throw BridgeFailure(message: "\(language.title) · \(name), line \(index + 1): enter one word or prefix* using this language’s letters.")
                }
            }
        }
    }

    static func save(_ drafts: [VideoLanguage: WordListDraft], defaults: UserDefaults) throws {
        // Validate every language before saving any changes.
        for (language, draft) in drafts { try validate(draft, language: language) }
        for (language, draft) in drafts {
            defaults.set(draft.censor, forKey: "censorWords.\(language.rawValue)")
            defaults.set(draft.allow, forKey: "allowedWords.\(language.rawValue)")
        }
    }

    static func request(_ language: VideoLanguage, defaults: UserDefaults) -> [String: [String]] {
        var rules: [String: [String]] = [:]
        if let words = defaults.string(forKey: "censorWords.\(language.rawValue)") {
            rules["censor"] = words.components(separatedBy: .newlines)
        }
        if let words = defaults.string(forKey: "allowedWords.\(language.rawValue)") {
            rules["allow"] = words.components(separatedBy: .newlines)
        }
        return rules
    }
}

struct WordListEditor: View {
    let root: URL
    var defaults: UserDefaults = .standard
    @State var language: VideoLanguage = .russian
    @Environment(\.dismiss) private var dismiss
    @State private var drafts: [VideoLanguage: WordListDraft] = [:]
    @State private var error: String?

    private func text(_ key: WritableKeyPath<WordListDraft, String>) -> Binding<String> {
        Binding(get: { drafts[language]?[keyPath: key] ?? "" }, set: { value in
            guard var draft = drafts[language] else { return }
            draft[keyPath: key] = value
            drafts[language] = draft
            error = nil
        })
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Word lists").font(.title2.bold())
                Spacer()
                Picker("Language", selection: $language) {
                    ForEach(VideoLanguage.allCases, id: \.rawValue) { Text($0.title).tag($0) }
                }.fixedSize()
            }
            Text("One word per line. Add * for a prefix; # starts a comment. Never censor takes priority.")
                .font(.callout).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 6) {
                Text("Censor words").font(.headline)
                TextEditor(text: text(\.censor)).font(.system(.body, design: .monospaced))
                    .frame(height: 175).border(.secondary.opacity(0.25)).accessibilityLabel("Censor words")
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("Never censor").font(.headline)
                TextEditor(text: text(\.allow)).font(.system(.body, design: .monospaced))
                    .frame(height: 105).border(.secondary.opacity(0.25)).accessibilityLabel("Never censor")
            }
            Text(language == .russian
                 ? "Known censor stems (бля, еб, пизд, ху…) include their Russian forms. Other entries match exact words. Exceptions match exact words or prefixes, without automatic forms."
                 : "English entries match exact words. For example, fuck* includes fucking and fucker; an exception for fucking keeps that word audible.")
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            Text("Applies when you open a file again. Cached speech is reused; saved reviews keep manual edits.")
                .font(.caption).foregroundStyle(.secondary)
            Text(error ?? " ").font(.caption).foregroundStyle(.red)
                .fixedSize(horizontal: false, vertical: true).frame(minHeight: 28, alignment: .topLeading)
            Spacer(minLength: 0)
            HStack {
                Button("Reset this language") {
                    do { drafts[language] = try WordListPreferences.builtIn(language, root: root); error = nil }
                    catch { self.error = error.localizedDescription }
                }
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Save") {
                    do { try WordListPreferences.save(drafts, defaults: defaults); dismiss() }
                    catch { self.error = error.localizedDescription }
                }.keyboardShortcut(.defaultAction).disabled(drafts.count != VideoLanguage.allCases.count)
            }
        }.padding(24).frame(width: 620, height: 660)
            .onAppear {
                do {
                    for language in VideoLanguage.allCases {
                        drafts[language] = try WordListPreferences.load(language, root: root, defaults: defaults)
                    }
                } catch { self.error = error.localizedDescription }
            }
    }
}
