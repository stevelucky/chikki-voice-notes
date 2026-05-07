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
                    Text("Recording: \(recorder.formattedTime)")
                        .monospacedDigit()
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)

                Button("Stop Recording") {
                    Task { await recorder.stopRecording() }
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])

            } else if recorder.isProcessing {
                // Multi-step progress
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("Processing")
                            .fontWeight(.semibold)
                        Spacer()
                        Text(recorder.formattedProcessingTime)
                            .monospacedDigit()
                            .foregroundStyle(.secondary)
                            .font(.caption)
                    }

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

                    if !recorder.processingDetail.isEmpty {
                        Text(recorder.processingDetail)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .lineLimit(1)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .frame(minWidth: 260)

            } else {
                Button("Start Recording") {
                    Task { await recorder.startRecording() }
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])

                Button("Process Audio File...") {
                    recorder.pickAndProcessAudioFile()
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
                Divider()
            }

            Button("Open Notes Folder") {
                recorder.openNotesFolder()
            }

            Button("Open Recordings Folder") {
                recorder.openRecordingsFolder()
            }

            Divider()

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
