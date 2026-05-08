import SwiftUI
import KeyboardShortcuts
import ServiceManagement

struct SettingsView: View {
    @AppStorage("projectDir") private var projectDir: String = ""
    @AppStorage("diarizeEnabled") private var diarizeEnabled: Bool = false
    @State private var launchAtLogin: Bool = (SMAppService.mainApp.status == .enabled)

    @State private var selectedEngine: String = ""
    @State private var engineModel: String = ""
    @State private var selectedProvider: String = ""
    @State private var llmModel: String = ""
    @State private var anthropicKey: String = ""
    @State private var openaiKey: String = ""
    @State private var geminiKey: String = ""
    @State private var saveStatus: String = ""

    private let engines = [("parakeet", "Parakeet"), ("whisper", "Whisper"), ("indicwhisper", "IndicWhisper")]
    private let providers = [("anthropic", "Claude (Anthropic)"), ("openai", "OpenAI"), ("gemini", "Gemini"), ("ollama", "Ollama")]

    var body: some View {
        Form {
            Section("General") {
                Toggle("Open at Login", isOn: $launchAtLogin)
                    .onChange(of: launchAtLogin) { _, enabled in
                        do {
                            if enabled { try SMAppService.mainApp.register() }
                            else { try SMAppService.mainApp.unregister() }
                        } catch { launchAtLogin = !enabled }
                    }
            }

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

            Section("Transcription") {
                Picker("Engine", selection: $selectedEngine) {
                    ForEach(engines, id: \.0) { id, label in
                        Text(label).tag(id)
                    }
                }
                LabeledContent("Model") {
                    TextField("e.g. mlx-community/parakeet-tdt-0.6b-v3", text: $engineModel)
                        .textFieldStyle(.plain)
                        .font(.caption)
                }
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
                Picker("Provider", selection: $selectedProvider) {
                    ForEach(providers, id: \.0) { id, label in
                        Text(label).tag(id)
                    }
                }
                LabeledContent("Model") {
                    TextField("e.g. claude-sonnet-4-6", text: $llmModel)
                        .textFieldStyle(.plain)
                        .font(.caption)
                }
            }

            Section("API Keys") {
                LabeledContent("Anthropic") {
                    SecureField("sk-ant-...", text: $anthropicKey)
                        .textFieldStyle(.plain)
                        .font(.caption)
                }
                LabeledContent("OpenAI") {
                    SecureField("sk-...", text: $openaiKey)
                        .textFieldStyle(.plain)
                        .font(.caption)
                }
                LabeledContent("Gemini") {
                    SecureField("AIza...", text: $geminiKey)
                        .textFieldStyle(.plain)
                        .font(.caption)
                }
                Text("Keys are stored in .env in your project folder.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }

            Section("Keyboard Shortcuts") {
                KeyboardShortcuts.Recorder("Toggle Recording:", name: .toggleRecording)
                    .padding(.vertical, 4)
                KeyboardShortcuts.Recorder("Quick Process:", name: .quickProcess)
                    .padding(.vertical, 4)
            }

            Section {
                HStack {
                    Button("Save Changes") { saveAll() }
                        .buttonStyle(.borderedProminent)
                    if !saveStatus.isEmpty {
                        Text(saveStatus)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 440, height: 640)
        .onAppear { loadAll() }
    }

    // MARK: - Load

    private func loadAll() {
        let cfg = parsedConfig
        selectedEngine = cfg.engine.isEmpty ? "parakeet" : cfg.engine
        engineModel = cfg.engineModel == "—" ? "" : cfg.engineModel
        selectedProvider = cfg.provider.isEmpty ? "anthropic" : cfg.provider
        llmModel = cfg.llmModel == "—" ? "" : cfg.llmModel
        let env = loadDotEnv() ?? [:]
        anthropicKey = env["ANTHROPIC_API_KEY"] ?? ""
        openaiKey = env["OPENAI_API_KEY"] ?? ""
        geminiKey = env["GOOGLE_API_KEY"] ?? env["GEMINI_API_KEY"] ?? ""
    }

    // MARK: - Save

    private func saveAll() {
        saveConfig()
        saveAPIKeys()
        Task { @MainActor in RecordingManager.shared.saveProjectDir(projectDir) }
        saveStatus = "Saved!"
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { saveStatus = "" }
    }

    private func saveConfig() {
        let path = projectDir + "/config.yaml"
        guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return }
        var lines = text.components(separatedBy: "\n")
        var section = "", inEngines = false, currentEngine = ""

        for i in 0..<lines.count {
            let line = lines[i]
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.hasPrefix("#") else { continue }
            let indent = line.prefix(while: { $0 == " " }).count
            let pad = String(repeating: " ", count: indent)

            if indent == 0 {
                section = trimmed.hasSuffix(":") ? String(trimmed.dropLast()) : ""
                inEngines = false; currentEngine = ""
                continue
            }

            if section == "transcription" {
                if indent == 2 {
                    inEngines = trimmed.hasPrefix("engines:")
                    if trimmed.hasPrefix("engine:") {
                        lines[i] = "\(pad)engine: \(selectedEngine)"
                    }
                } else if inEngines && indent == 4 {
                    currentEngine = trimmed.hasSuffix(":") ? String(trimmed.dropLast()) : trimmed
                } else if inEngines && indent == 6 && currentEngine == selectedEngine {
                    if trimmed.hasPrefix("model:") && !engineModel.isEmpty {
                        lines[i] = "\(pad)model: \(engineModel)"
                    }
                }
            } else if section == "processing" && indent == 2 {
                if trimmed.hasPrefix("provider:") {
                    lines[i] = "\(pad)provider: \(selectedProvider)"
                } else if trimmed.hasPrefix("model:") && !llmModel.isEmpty {
                    lines[i] = "\(pad)model: \(llmModel)"
                }
            }
        }

        try? lines.joined(separator: "\n").write(toFile: path, atomically: true, encoding: .utf8)
    }

    private func saveAPIKeys() {
        let path = projectDir + "/.env"
        var lines = (try? String(contentsOfFile: path, encoding: .utf8))?.components(separatedBy: "\n") ?? []

        func set(_ key: String, _ value: String) {
            lines = lines.filter { !$0.hasPrefix("\(key)=") }
            if !value.isEmpty { lines.append("\(key)=\(value)") }
        }

        set("ANTHROPIC_API_KEY", anthropicKey)
        set("OPENAI_API_KEY", openaiKey)
        set("GOOGLE_API_KEY", geminiKey)
        lines = lines.filter { !$0.hasPrefix("GEMINI_API_KEY=") }

        try? lines.joined(separator: "\n").write(toFile: path, atomically: true, encoding: .utf8)
    }

    // MARK: - Helpers

    private var isValidProject: Bool {
        !projectDir.isEmpty && FileManager.default.fileExists(atPath: projectDir + "/config.yaml")
    }

    private func loadDotEnv() -> [String: String]? {
        guard let contents = try? String(contentsOfFile: projectDir + "/.env", encoding: .utf8) else { return nil }
        var vars: [String: String] = [:]
        for line in contents.components(separatedBy: .newlines) {
            let t = line.trimmingCharacters(in: .whitespaces)
            guard !t.isEmpty, !t.hasPrefix("#"), t.contains("=") else { continue }
            let parts = t.split(separator: "=", maxSplits: 1)
            guard parts.count == 2 else { continue }
            let k = String(parts[0]).trimmingCharacters(in: .whitespaces)
            var v = String(parts[1]).trimmingCharacters(in: .whitespaces)
            if (v.hasPrefix("\"") && v.hasSuffix("\"")) || (v.hasPrefix("'") && v.hasSuffix("'")) {
                v = String(v.dropFirst().dropLast())
            }
            vars[k] = v
        }
        return vars
    }

    private var parsedConfig: (engine: String, engineModel: String, provider: String, llmModel: String) {
        guard let contents = try? String(contentsOfFile: projectDir + "/config.yaml", encoding: .utf8) else {
            return ("", "", "", "")
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
                    if trimmed.hasPrefix("engine:") { engine = yamlValue(trimmed); targetEngine = engine }
                } else if inEngines && indent == 4 {
                    currentEngine = trimmed.hasSuffix(":") ? String(trimmed.dropLast()) : trimmed
                } else if inEngines && indent == 6 && currentEngine == targetEngine {
                    if trimmed.hasPrefix("model:") { engineModel = yamlValue(trimmed) }
                }
            } else if section == "processing" && indent == 2 {
                if trimmed.hasPrefix("provider:") { provider = yamlValue(trimmed) }
                else if trimmed.hasPrefix("model:") { llmModel = yamlValue(trimmed) }
            }
        }

        return (engine, engineModel, provider, llmModel)
    }

    private func yamlValue(_ line: String) -> String {
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
            Task { @MainActor in RecordingManager.shared.saveProjectDir(url.path) }
        }
    }
}
