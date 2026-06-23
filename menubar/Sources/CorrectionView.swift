import SwiftUI

/// Window host for the "Fix Last Note" correction panel. Mirrors
/// SettingsWindowController: a single reused window with a fresh hosting controller.
final class CorrectionWindowController {
    static let shared = CorrectionWindowController()
    private var window: NSWindow?

    func show() {
        let controller = NSHostingController(rootView: CorrectionView())
        if let win = window {
            win.contentViewController = controller
        } else {
            let win = NSWindow(contentViewController: controller)
            win.title = "Fix Last Note"
            win.styleMask = [.titled, .closable]
            win.setContentSize(NSSize(width: 440, height: 320))
            win.center()
            win.isReleasedWhenClosed = false
            window = win
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func close() { window?.close() }
}

/// Type a plain-English correction for the most recent note. Scribe re-reads the
/// recording's transcript with the correction as the source of truth and
/// regenerates the note, propagating the fix (e.g. a reversed speaker name)
/// throughout. Checked-off action items are preserved.
struct CorrectionView: View {
    @ObservedObject private var recorder = RecordingManager.shared
    @State private var text = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Fix Last Note").font(.headline)

            if let note = recorder.lastNoteFile {
                Text(Self.displayTitle(note))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            Text("Describe what's wrong in plain English. Scribe re-reads the transcript with your correction as the source of truth and regenerates the note — fixing names, owners, and the summary throughout. Your checked-off items are kept.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            TextEditor(text: $text)
                .font(.body)
                .frame(minHeight: 90)
                .padding(4)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.gray.opacity(0.3)))
                .disabled(recorder.isCorrecting)

            HStack {
                if recorder.isCorrecting {
                    ProgressView().controlSize(.small)
                    Text("Applying… this may take a few seconds.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Cancel") { CorrectionWindowController.shared.close() }
                Button("Apply Correction") { apply() }
                    .buttonStyle(.borderedProminent)
                    .disabled(recorder.isCorrecting
                              || recorder.lastNoteFile == nil
                              || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(16)
        .frame(width: 440, height: 320)
    }

    private func apply() {
        guard let note = recorder.lastNoteFile else { return }
        let message = text
        Task { @MainActor in
            await recorder.applyCorrection(file: note, message: message)
            // Close on success; keep the window (and typed text) open on failure so
            // the user can adjust and retry. lastError is set only on failure.
            if recorder.lastError == nil {
                text = ""
                CorrectionWindowController.shared.close()
            }
        }
    }

    /// Turn "20260623_1101_Some Title.md" into a readable "Some Title".
    static func displayTitle(_ filename: String) -> String {
        var name = filename
        if name.hasSuffix(".md") { name = String(name.dropLast(3)) }
        if let r = name.range(of: #"^\d{8}_\d{4}_"#, options: .regularExpression) {
            name.removeSubrange(r)
        }
        return name
    }
}
