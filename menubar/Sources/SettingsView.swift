import SwiftUI
import KeyboardShortcuts

struct SettingsView: View {
    var body: some View {
        Form {
            Section("Keyboard Shortcuts") {
                KeyboardShortcuts.Recorder("Toggle Recording:", name: .toggleRecording)
                    .padding(.vertical, 4)

                KeyboardShortcuts.Recorder("Quick Process:", name: .quickProcess)
                    .padding(.vertical, 4)
            }

            Section("About") {
                LabeledContent("Version", value: "1.0.0")
                LabeledContent("Engine", value: "Configurable in config.yaml")
                Text("Chikki records audio, transcribes with local AI models, and extracts structured meeting notes.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .frame(width: 400, height: 250)
    }
}
