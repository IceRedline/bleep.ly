import SwiftUI
import AppKit

enum AppInformation: String, CaseIterable {
    case privacy = "privacy-policy", support, licenses = "third-party"

    var title: String {
        switch self {
        case .privacy: "Privacy Policy"
        case .support: "Support"
        case .licenses: "Open Source Licenses"
        }
    }

    @MainActor func text(resources: URL? = Bundle.main.resourceURL) -> String {
        let packaged = resources?.appendingPathComponent("Documentation/\(rawValue).md")
        let development = URL(fileURLWithPath: AppModel.defaultRoot).appendingPathComponent("docs/\(rawValue).md")
        // Local development has no Resources directory. Release preparation
        // requires all documents so the policy always works without a network.
        let url = packaged.flatMap { FileManager.default.fileExists(atPath: $0.path) ? $0 : nil } ?? development
        return (try? String(contentsOf: url, encoding: .utf8)) ?? "This document is unavailable. Contact support at https://github.com/IceRedline/bleeply/issues."
    }
}

struct AppInformationView: View {
    let document: AppInformation

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if document == .licenses, let resources = Bundle.main.resourceURL {
                    Button("Show Bundled Licenses and Sources") {
                        NSWorkspace.shared.activateFileViewerSelecting([resources.appendingPathComponent("ThirdParty")])
                    }
                }
                ForEach(Array(document.text().components(separatedBy: "\n\n").enumerated()), id: \.offset) { _, paragraph in
                    if paragraph.hasPrefix("# ") {
                        Text(String(paragraph.dropFirst(2))).font(.title).bold()
                    } else if paragraph.hasPrefix("## ") {
                        Text(String(paragraph.dropFirst(3))).font(.headline).padding(.top, 8)
                    } else {
                        Text(.init(paragraph)).font(.body).textSelection(.enabled)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading).padding(28)
        }
        .frame(minWidth: 480, minHeight: 420)
    }
}
