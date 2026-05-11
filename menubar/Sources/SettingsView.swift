import SwiftUI
import KeyboardShortcuts
import ServiceManagement

struct SettingsView: View {
    @State private var selectedTab = "general"

    var body: some View {
        TabView(selection: $selectedTab) {
            GeneralTab()
                .tabItem { Label("General", systemImage: "gear") }
                .tag("general")

            TranscriptionTab()
                .tabItem { Label("Transcription", systemImage: "waveform") }
                .tag("transcription")

            NotesTab()
                .tabItem { Label("Notes & AI", systemImage: "sparkles") }
                .tag("notes")

            ShortcutsTab()
                .tabItem { Label("Shortcuts", systemImage: "keyboard") }
                .tag("shortcuts")
        }
        .frame(width: 460, height: 320)
    }
}

// MARK: - General Tab

struct GeneralTab: View {
    @AppStorage("projectDir") private var projectDir: String = ""
    @State private var launchAtLogin: Bool = (SMAppService.mainApp.status == .enabled)

    var body: some View {
        Form {
            Section("Startup") {
                Toggle("Open at Login", isOn: $launchAtLogin)
                    .onChange(of: launchAtLogin) { _, enabled in
                        do {
                            if enabled { try SMAppService.mainApp.register() }
                            else { try SMAppService.mainApp.unregister() }
                        } catch { launchAtLogin = !enabled }
                    }
            }

            Section("Project Folder") {
                LabeledContent("Location") {
                    HStack(spacing: 8) {
                        Text(projectDir.isEmpty ? "Not set" : (projectDir as NSString).abbreviatingWithTildeInPath)
                            .font(.caption)
                            .foregroundColor(isValidProject ? .primary : .red)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer()
                        Button("Change...") { pickFolder() }
                            .controlSize(.small)
                    }
                }
                if !isValidProject {
                    Label("config.yaml not found in this folder.", systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundColor(.red)
                }
            }
        }
        .formStyle(.grouped)
        .padding(.top, 4)
    }

    private var isValidProject: Bool {
        !projectDir.isEmpty && FileManager.default.fileExists(atPath: projectDir + "/config.yaml")
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

// MARK: - Transcription Tab

struct TranscriptionTab: View {
    @AppStorage("projectDir") private var projectDir: String = ""
    @AppStorage("diarizeEnabled") private var diarizeEnabled: Bool = false
    @State private var selectedEngine = ""
    @State private var engineModel = ""
    @State private var saveStatus = ""

    private let engines = [("parakeet", "Parakeet"), ("whisper", "Whisper"), ("indicwhisper", "IndicWhisper")]

    var body: some View {
        Form {
            Section("Engine") {
                Picker("Engine", selection: $selectedEngine) {
                    ForEach(engines, id: \.0) { id, label in Text(label).tag(id) }
                }
                LabeledContent("Model") {
                    TextField("e.g. mlx-community/parakeet-tdt-0.6b-v3", text: $engineModel)
                        .textFieldStyle(.roundedBorder)
                        .font(.caption)
                }
            }

            Section("Speaker Diarization") {
                Toggle("Enable Speaker Diarization", isOn: $diarizeEnabled)
                if diarizeEnabled {
                    Text("Requires pyannote.audio — install with:\npip install pyannote.audio\nSet HF_TOKEN in the Notes & AI tab.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .formStyle(.grouped)
        .padding(.top, 4)
        .safeAreaInset(edge: .bottom) { saveBar }
        .onAppear { load() }
    }

    private var saveBar: some View {
        HStack {
            Spacer()
            if !saveStatus.isEmpty {
                Text(saveStatus).font(.caption).foregroundStyle(.secondary)
            }
            Button("Save") { save() }.buttonStyle(.borderedProminent).controlSize(.small)
        }
        .padding(.horizontal, 16)
        .padding(.bottom, 12)
    }

    private func load() {
        let cfg = parseConfig(projectDir)
        selectedEngine = cfg.engine.isEmpty ? "parakeet" : cfg.engine
        engineModel = cfg.engineModel
    }

    private func save() {
        writeConfig(projectDir, engine: selectedEngine, engineModel: engineModel, provider: nil, llmModel: nil)
        RecordingManager.shared.saveProjectDir(projectDir)
        flash($saveStatus, "Saved!")
    }
}

// MARK: - Notes & AI Tab

struct NotesTab: View {
    @AppStorage("projectDir") private var projectDir: String = ""
    @State private var selectedProvider = ""
    @State private var llmModel = ""
    @State private var anthropicKey = ""
    @State private var openaiKey = ""
    @State private var geminiKey = ""
    @State private var hfToken = ""
    @State private var saveStatus = ""

    private let providers = [("anthropic", "Claude (Anthropic)"), ("openai", "OpenAI"), ("gemini", "Gemini"), ("ollama", "Ollama")]

    var body: some View {
        Form {
            Section("LLM Provider") {
                Picker("Provider", selection: $selectedProvider) {
                    ForEach(providers, id: \.0) { id, label in Text(label).tag(id) }
                }
                LabeledContent("Model") {
                    TextField("e.g. claude-sonnet-4-6", text: $llmModel)
                        .textFieldStyle(.roundedBorder)
                        .font(.caption)
                }
            }

            Section("API Keys") {
                LabeledContent("Anthropic") {
                    SecureField("sk-ant-...", text: $anthropicKey).textFieldStyle(.roundedBorder).font(.caption)
                }
                LabeledContent("OpenAI") {
                    SecureField("sk-...", text: $openaiKey).textFieldStyle(.roundedBorder).font(.caption)
                }
                LabeledContent("Gemini") {
                    SecureField("AIza...", text: $geminiKey).textFieldStyle(.roundedBorder).font(.caption)
                }
                LabeledContent("HuggingFace") {
                    SecureField("hf_...", text: $hfToken).textFieldStyle(.roundedBorder).font(.caption)
                }
                Text("Stored in .env in your project folder.")
                    .font(.caption2).foregroundStyle(.tertiary)
            }
        }
        .formStyle(.grouped)
        .padding(.top, 4)
        .safeAreaInset(edge: .bottom) { saveBar }
        .onAppear { load() }
    }

    private var saveBar: some View {
        HStack {
            Spacer()
            if !saveStatus.isEmpty {
                Text(saveStatus).font(.caption).foregroundStyle(.secondary)
            }
            Button("Save") { save() }.buttonStyle(.borderedProminent).controlSize(.small)
        }
        .padding(.horizontal, 16)
        .padding(.bottom, 12)
    }

    private func load() {
        let cfg = parseConfig(projectDir)
        selectedProvider = cfg.provider.isEmpty ? "anthropic" : cfg.provider
        llmModel = cfg.llmModel
        let env = parseDotEnv(projectDir) ?? [:]
        anthropicKey = env["ANTHROPIC_API_KEY"] ?? ""
        openaiKey    = env["OPENAI_API_KEY"] ?? ""
        geminiKey    = env["GOOGLE_API_KEY"] ?? env["GEMINI_API_KEY"] ?? ""
        hfToken      = env["HF_TOKEN"] ?? ""
    }

    private func save() {
        writeConfig(projectDir, engine: nil, engineModel: nil, provider: selectedProvider, llmModel: llmModel)
        saveDotEnv(projectDir, keys: [
            "ANTHROPIC_API_KEY": anthropicKey,
            "OPENAI_API_KEY": openaiKey,
            "GOOGLE_API_KEY": geminiKey,
            "HF_TOKEN": hfToken,
        ], remove: ["GEMINI_API_KEY"])
        RecordingManager.shared.saveProjectDir(projectDir)
        flash($saveStatus, "Saved!")
    }
}

// MARK: - Shortcuts Tab

struct ShortcutsTab: View {
    var body: some View {
        Form {
            Section("Recording") {
                KeyboardShortcuts.Recorder("Toggle Recording", name: .toggleRecording)
                    .padding(.vertical, 2)
                KeyboardShortcuts.Recorder("Quick Process", name: .quickProcess)
                    .padding(.vertical, 2)
            }
        }
        .formStyle(.grouped)
        .padding(.top, 4)
    }
}

// MARK: - Shared config helpers (file-level functions)

private func parseConfig(_ projectDir: String) -> (engine: String, engineModel: String, provider: String, llmModel: String) {
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
            section = trimmed.hasPrefix("transcription:") ? "transcription" : trimmed.hasPrefix("processing:") ? "processing" : ""
            inEngines = false; currentEngine = ""
            continue
        }
        if section == "transcription" {
            if indent == 2 {
                inEngines = trimmed.hasPrefix("engines:")
                if trimmed.hasPrefix("engine:") { engine = yamlVal(trimmed); targetEngine = engine }
            } else if inEngines && indent == 4 {
                currentEngine = trimmed.hasSuffix(":") ? String(trimmed.dropLast()) : trimmed
            } else if inEngines && indent == 6 && currentEngine == targetEngine {
                if trimmed.hasPrefix("model:") { engineModel = yamlVal(trimmed) }
            }
        } else if section == "processing" && indent == 2 {
            if trimmed.hasPrefix("provider:") { provider = yamlVal(trimmed) }
            else if trimmed.hasPrefix("model:") { llmModel = yamlVal(trimmed) }
        }
    }
    return (engine, engineModel, provider, llmModel)
}

private func yamlVal(_ line: String) -> String {
    guard let colon = line.firstIndex(of: ":") else { return "" }
    return String(line[line.index(after: colon)...])
        .trimmingCharacters(in: .whitespaces)
        .trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
}

private func writeConfig(_ projectDir: String, engine: String?, engineModel: String?, provider: String?, llmModel: String?) {
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
            section = trimmed.hasPrefix("transcription:") ? "transcription" : trimmed.hasPrefix("processing:") ? "processing" : ""
            inEngines = false; currentEngine = ""
            continue
        }
        if section == "transcription" {
            if indent == 2 {
                inEngines = trimmed.hasPrefix("engines:")
                if trimmed.hasPrefix("engine:"), let e = engine { lines[i] = "\(pad)engine: \(e)" }
            } else if inEngines && indent == 4 {
                currentEngine = trimmed.hasSuffix(":") ? String(trimmed.dropLast()) : trimmed
            } else if inEngines && indent == 6 && currentEngine == (engine ?? "") {
                if trimmed.hasPrefix("model:"), let m = engineModel, !m.isEmpty { lines[i] = "\(pad)model: \(m)" }
            }
        } else if section == "processing" && indent == 2 {
            if trimmed.hasPrefix("provider:"), let p = provider { lines[i] = "\(pad)provider: \(p)" }
            else if trimmed.hasPrefix("model:"), let m = llmModel, !m.isEmpty { lines[i] = "\(pad)model: \(m)" }
        }
    }
    try? lines.joined(separator: "\n").write(toFile: path, atomically: true, encoding: .utf8)
}

private func parseDotEnv(_ projectDir: String) -> [String: String]? {
    guard let contents = try? String(contentsOfFile: projectDir + "/.env", encoding: .utf8) else { return nil }
    var vars: [String: String] = [:]
    for line in contents.components(separatedBy: .newlines) {
        let t = line.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty, !t.hasPrefix("#"), t.contains("=") else { continue }
        let parts = t.split(separator: "=", maxSplits: 1)
        guard parts.count == 2 else { continue }
        let k = String(parts[0]).trimmingCharacters(in: .whitespaces)
        var v = String(parts[1]).trimmingCharacters(in: .whitespaces)
        if (v.hasPrefix("\"") && v.hasSuffix("\"")) || (v.hasPrefix("'") && v.hasSuffix("'")) { v = String(v.dropFirst().dropLast()) }
        vars[k] = v
    }
    return vars
}

private func saveDotEnv(_ projectDir: String, keys: [String: String], remove: [String] = []) {
    let path = projectDir + "/.env"
    var lines = (try? String(contentsOfFile: path, encoding: .utf8))?.components(separatedBy: "\n") ?? []
    for key in keys.keys + remove { lines = lines.filter { !$0.hasPrefix("\(key)=") } }
    for (key, value) in keys where !value.isEmpty { lines.append("\(key)=\(value)") }
    try? lines.joined(separator: "\n").write(toFile: path, atomically: true, encoding: .utf8)
}

private func flash(_ status: Binding<String>, _ message: String) {
    status.wrappedValue = message
    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { status.wrappedValue = "" }
}
