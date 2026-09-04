import SwiftUI
import KeyboardShortcuts

struct MenuBarView: View {
    @EnvironmentObject var recorder: RecordingManager

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if recorder.isRecording {
                HStack {
                    Circle()
                        .fill(recorder.isPaused ? Color.gray : .red)
                        .frame(width: 8, height: 8)
                    // Live elapsed time is shown in the menu-bar icon itself; keeping
                    // it out of the dropdown means this menu never re-renders while
                    // open, so hover highlighting stays stable.
                    Text(recorder.isPaused
                         ? recorder.pauseStatusText
                         : (recorder.captureMode == .idea ? "Recording idea" : "Recording"))
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .allowsHitTesting(false)

                Button(recorder.isPaused ? "Resume Recording" : "Pause Recording") {
                    recorder.togglePause()
                }

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
                        state: recorder.stepState(for: "transcribing"),
                        progress: recorder.transcribeProgress
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

            } else if recorder.isCorrecting {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Applying your correction…")
                        .fontWeight(.semibold)
                    Text("Re-reading the transcript and regenerating the note.")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .lineLimit(2)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .frame(minWidth: 260, alignment: .leading)
                .allowsHitTesting(false)

            } else {
                Button("Record Meeting") {
                    Task { await recorder.startRecording() }
                }
                .globalKeyboardShortcut(.toggleRecording)

                // Capture a long-term idea: same recording flow, but processed
                // idea-shaped (no to-do hunting). Surfaces under the Someday tab.
                Button("Record Idea") {
                    Task { await recorder.startRecording(mode: .idea) }
                }

                Button("Process Audio File...") {
                    recorder.pickAndProcessAudioFile()
                }
                .globalKeyboardShortcut(.quickProcess)

                if recorder.lastNoteFile != nil {
                    Button("Fix Last Note…") {
                        CorrectionWindowController.shared.show()
                    }
                }
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
    var progress: Double = -1   // 0…1 shows a real bar; -1 = indeterminate (icon only)

    private var showsBar: Bool { state == .active && progress >= 0 }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 0) {
                (stateIcon + Text("  \(label)")).font(.caption)
                if showsBar {
                    Spacer(minLength: 8)
                    Text("\(Int((progress * 100).rounded()))%")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            if showsBar {
                ProgressView(value: min(max(progress, 0), 1))
                    .progressViewStyle(.linear)
                    .controlSize(.small)
                    .padding(.leading, 16)
            }
        }
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
