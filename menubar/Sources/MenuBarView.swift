import SwiftUI
import KeyboardShortcuts

struct MenuBarView: View {
    @EnvironmentObject var recorder: RecordingManager

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if recorder.isRecording {
                HStack {
                    Circle()
                        .fill(.red)
                        .frame(width: 8, height: 8)
                    // Live elapsed time is shown in the menu-bar icon itself; keeping
                    // it out of the dropdown means this menu never re-renders while
                    // open, so hover highlighting stays stable.
                    Text("Recording")
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .allowsHitTesting(false)

                Button("Stop Recording") {
                    Task { await recorder.stopRecording() }
                }
                // Shows the user's *current* Toggle Recording shortcut and updates
                // live when they change it in Settings (not a hardcoded ⌘⇧R).
                .globalKeyboardShortcut(.toggleRecording)

                Button("Stop & Cancel") {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                        NSApp.activate(ignoringOtherApps: true)
                        let alert = NSAlert()
                        alert.messageText = "Cancel Recording?"
                        alert.informativeText = "The recording will be deleted and not processed."
                        alert.alertStyle = .warning
                        alert.addButton(withTitle: "Delete Recording")
                        alert.addButton(withTitle: "Keep Recording")
                        if alert.runModal() == .alertFirstButtonReturn {
                            Task { await recorder.cancelRecording() }
                        }
                    }
                }

            } else if recorder.isProcessing {
                // Multi-step progress
                VStack(alignment: .leading, spacing: 6) {
                    Text("Processing")
                        .fontWeight(.semibold)

                    ProcessingStepView(
                        label: "Transcribing audio",
                        state: recorder.stepState(for: "transcribing")
                    )
                    ProcessingStepView(
                        label: "Extracting notes (\(recorder.llmProvider))",
                        state: recorder.stepState(for: "processing")
                    )
                    ProcessingStepView(
                        label: "Saving & exporting",
                        state: recorder.stepState(for: "saving")
                    )

                    // Always render this row (even when empty) at a fixed height.
                    // If it toggled in/out, every menu item below it would shift by
                    // a row as stages advance, and while the menu is open that frame
                    // change scrambles AppKit's hover highlighting (items "bounce").
                    Text(recorder.processingDetail.isEmpty ? " " : recorder.processingDetail)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                        .frame(height: 14, alignment: .leading)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .frame(minWidth: 260)
                .allowsHitTesting(false)

            } else {
                Button("Start Recording") {
                    Task { await recorder.startRecording() }
                }
                .globalKeyboardShortcut(.toggleRecording)

                Button("Process Audio File...") {
                    recorder.pickAndProcessAudioFile()
                }
                .globalKeyboardShortcut(.quickProcess)
            }

            Divider()

            if let error = recorder.lastError {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Processing failed:")
                        .font(.caption2)
                        .foregroundStyle(.red)
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .lineLimit(4)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .allowsHitTesting(false)
                Divider()
            } else if let lastNote = recorder.lastNote, !lastNote.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Last note:")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                    Text(lastNote)
                        .font(.caption)
                        .lineLimit(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 2)
                .frame(maxWidth: 260, alignment: .leading)
                .allowsHitTesting(false)
                Divider()
            }

            Button("Open Dashboard") {
                recorder.openDashboard()
            }

            Button("Open Notes Folder") {
                recorder.openNotesFolder()
            }

            Button("Open Recordings Folder") {
                recorder.openRecordingsFolder()
            }

            Divider()

            Button("Manage Speakers...") {
                SpeakerWindowController.shared.show()
            }

            Button("Settings...") {
                SettingsWindowController.shared.show()
            }
            .keyboardShortcut(",")

            Button("Quit Scribe") {
                NSApplication.shared.terminate(nil)
            }
            .keyboardShortcut("q")
        }
        .padding(.vertical, 4)
    }
}


enum StepState {
    case pending
    case active
    case done
}

struct ProcessingStepView: View {
    let label: String
    let state: StepState

    var body: some View {
        stateIcon + Text("  \(label)").font(.caption)
    }

    private var stateIcon: Text {
        switch state {
        case .pending:
            return Text("○").font(.caption).foregroundStyle(.quaternary)
        case .active:
            return Text("◉").font(.caption).foregroundStyle(.blue)
        case .done:
            return Text("✓").font(.caption).foregroundStyle(.green)
        }
    }
}
