import SwiftUI
import KeyboardShortcuts
import ServiceManagement

struct SettingsView: View {
    @AppStorage("projectDir") private var projectDir: String = ""
    @AppStorage("diarizeEnabled") private var diarizeEnabled: Bool = false
    @State private var launchAtLogin: Bool = (SMAppService.mainApp.status == .enabled)

    var body: some View {
        let cfg = configValues
        Form {
            Section("Project Folder") {
                LabeledContent("Path") {
                    HStack {
                        Text(projectDir.isEmpty ? "Not set" : projectDir)
                            .font(.caption)
                            .foregroundStyle(isValidProject ? Color.primary : Color.red)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer()
                        Button("Change...") { pickFolder() }
                    }
                }
                if !isValidProject {
                    Text("config.yaml not found — notes and recordings will not work.")
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }

            Section("General") {
                Toggle("Open at Login", isOn: $launchAtLogin)
                    .onChange(of: launchAtLogin) { _, enabled in
                        do {
                            if enabled {
                                try SMAppService.mainApp.register()
                            } else {
                                try SMAppService.mainApp.unregister()
                            }
                        } catch {
                            launchAtLogin = !enabled
                        }
                    }
            }

            Section("Transcription") {
                LabeledContent("Engine", value: cfg.engine)
                LabeledContent("Model", value: cfg.engineModel)
                    .foregroundStyle(.secondary)
                Toggle("Speaker Diarization", isOn: $diarizeEnabled)
                if diarizeEnabled {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Requires pyannote.audio and HF_TOKEN in .env:")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text("pip install pyannote.audio")
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                    }
                    .padding(.top, 2)
                }
            }

            Section("Notes Processing") {
                LabeledContent("Provider", value: cfg.provider)
                LabeledContent("Model", value: cfg.llmModel)
                    .foregroundStyle(.secondary)
            }

            Section("Keyboard Shortcuts") {
                KeyboardShortcuts.Recorder("Toggle Recording:", name: .toggleRecording)
                    .padding(.vertical, 4)
                KeyboardShortcuts.Recorder("Quick Process:", name: .quickProcess)
                    .padding(.vertical, 4)
            }

            Section {
                Text("Edit config.yaml to change engines or providers.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .frame(width: 440, height: 500)
    }

    private var isValidProject: Bool {
        !projectDir.isEmpty && FileManager.default.fileExists(atPath: projectDir + "/config.yaml")
    }

    private var configValues: (engine: String, engineModel: String, provider: String, llmModel: String) {
        guard let contents = try? String(contentsOfFile: projectDir + "/config.yaml", encoding: .utf8) else {
            return ("—", "—", "—", "—")
        }

        var engine = "", engineModel = "", provider = "", llmModel = ""
        var section = "", inEngines = false, currentEngine = "", targetEngine = ""

        for line in contents.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty, !trimmed.hasPrefix("#") else { continue }
            let indent = line.prefix(while: { $0 == " " }).count

            if indent == 0 {
                if trimmed.hasPrefix("transcription:") { section = "transcription" }
                else if trimmed.hasPrefix("processing:") { section = "processing" }
                else { section = "" }
                inEngines = false; currentEngine = ""
                continue
            }

            if section == "transcription" {
                if indent == 2 {
                    inEngines = trimmed.hasPrefix("engines:")
                    if trimmed.hasPrefix("engine:") {
                        engine = value(of: trimmed)
                        targetEngine = engine
                    }
                } else if inEngines && indent == 4 {
                    currentEngine = trimmed.hasSuffix(":") ? String(trimmed.dropLast()) : trimmed
                } else if inEngines && indent == 6 && currentEngine == targetEngine {
                    if trimmed.hasPrefix("model:") { engineModel = value(of: trimmed) }
                }
            } else if section == "processing" && indent == 2 {
                if trimmed.hasPrefix("provider:") { provider = value(of: trimmed) }
                else if trimmed.hasPrefix("model:") { llmModel = value(of: trimmed) }
            }
        }

        return (
            engine.isEmpty ? "—" : engine,
            engineModel.isEmpty ? "—" : engineModel,
            provider.isEmpty ? "—" : provider,
            llmModel.isEmpty ? "—" : llmModel
        )
    }

    private func value(of line: String) -> String {
        guard let colon = line.firstIndex(of: ":") else { return "" }
        return String(line[line.index(after: colon)...])
            .trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
    }

    private func pickFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "Select"
        panel.begin { response in
            guard response == .OK, let url = panel.url else { return }
            projectDir = url.path
            Task { @MainActor in
                RecordingManager.shared.saveProjectDir(url.path)
            }
        }
    }
}
