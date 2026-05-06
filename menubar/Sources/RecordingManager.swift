import Foundation
import SwiftUI
import UserNotifications

@MainActor
class RecordingManager: ObservableObject {
    static let shared = RecordingManager()

    @Published var isRecording = false
    @Published var elapsedSeconds: Int = 0
    @Published var lastNote: String?
    @Published var isProcessing = false
    @Published var processingStage: String = ""  // raw stage key from Python
    @Published var processingDetail: String = ""
    @Published var processingElapsed: Int = 0
    @Published var completedStages: Set<String> = []
    @Published var projectDir: String
    @Published var llmProvider: String = "LLM"
    @Published var lastError: String?

    private var recordProcess: Process?
    private var timer: Timer?
    private var processingTimer: Timer?

    private let condaEnv = "chikki"
    private static let projectDirKey = "projectDir"

    private init() {
        if let saved = UserDefaults.standard.string(forKey: Self.projectDirKey),
           FileManager.default.fileExists(atPath: saved + "/config.yaml") {
            projectDir = saved
        } else {
            let resolved = Self.resolveProjectDir()
            projectDir = resolved
            UserDefaults.standard.set(resolved, forKey: Self.projectDirKey)
        }
        requestNotificationPermission()
        llmProvider = Self.readLLMProvider(from: projectDir)
    }

    func saveProjectDir(_ path: String) {
        UserDefaults.standard.set(path, forKey: Self.projectDirKey)
        projectDir = path
        llmProvider = Self.readLLMProvider(from: path)
    }

    private static func readLLMProvider(from dir: String) -> String {
        let configPath = "\(dir)/config.yaml"
        guard let contents = try? String(contentsOfFile: configPath, encoding: .utf8) else { return "LLM" }
        for line in contents.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("provider:") {
                let value = trimmed.replacingOccurrences(of: "provider:", with: "").trimmingCharacters(in: .whitespaces)
                switch value {
                case "anthropic": return "Claude"
                case "gemini":    return "Gemini"
                case "openai":    return "OpenAI"
                case "ollama":    return "Ollama"
                default:          return value
                }
            }
        }
        return "LLM"
    }

    private static func resolveProjectDir() -> String {
        let appDir = Bundle.main.bundlePath
        let appParent = URL(fileURLWithPath: appDir).deletingLastPathComponent().path

        var dir = URL(fileURLWithPath: appParent)
        for _ in 0..<5 {
            let candidate = dir.appendingPathComponent("config.yaml").path
            if FileManager.default.fileExists(atPath: candidate) {
                return dir.path
            }
            dir = dir.deletingLastPathComponent()
        }

        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let fallbacks = [
            "\(home)/scribe-notes",
            "\(home)/chikki",
            "\(home)/codes/chikki",
            "\(home)/Documents/chikki",
        ]
        for path in fallbacks {
            if FileManager.default.fileExists(atPath: path + "/config.yaml") {
                return path
            }
        }

        return appParent
    }

    func toggle() async {
        if isRecording {
            await stopRecording()
        } else {
            await startRecording()
        }
    }

    func startRecording() async {
        guard !isRecording else { return }

        isRecording = true
        elapsedSeconds = 0

        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.elapsedSeconds += 1
            }
        }

        sendNotification(title: "Scribe", body: "Recording started. Press Cmd+Shift+R to stop.")
        recordProcess = runCLI(args: ["record", "--duration", "0"], background: true)
    }

    func stopRecording() async {
        guard isRecording else { return }

        if let proc = recordProcess, proc.isRunning {
            proc.interrupt()
            // Wait off the main thread so we don't freeze the UI
            await Task.detached { proc.waitUntilExit() }.value
        }
        recordProcess = nil

        timer?.invalidate()
        timer = nil
        isRecording = false

        sendNotification(title: "Scribe", body: "Recording stopped. Processing...")
        await processLatest()
    }

    func processLatest() async {
        let capturedProjectDir = projectDir
        let capturedDiarize = UserDefaults.standard.bool(forKey: "diarizeEnabled")
        let condaBase = Self.findCondaBase()
        let python = "\(condaBase)/envs/\(condaEnv)/bin/python"
        let diarizeFlag = capturedDiarize ? "--diarize" : "--no-diarize"
        let cmd = "cd \"\(capturedProjectDir)\" && \"\(python)\" -m src.cli process-latest \(diarizeFlag)"
        await runPipeline(cmd: cmd, projectDir: capturedProjectDir)
    }

    func pickAndProcessAudioFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.audio, .wav, .mp3, .mpeg4Audio]
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.prompt = "Process"
        panel.message = "Select a recording to transcribe and process"
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url, let self else { return }
            Task { @MainActor in
                await self.processAudioFile(at: url.path)
            }
        }
    }

    func processAudioFile(at path: String) async {
        let capturedProjectDir = projectDir
        let capturedDiarize = UserDefaults.standard.bool(forKey: "diarizeEnabled")
        let condaBase = Self.findCondaBase()
        let python = "\(condaBase)/envs/\(condaEnv)/bin/python"
        let diarizeFlag = capturedDiarize ? "--diarize" : "--no-diarize"
        let escapedPath = path.replacingOccurrences(of: "\"", with: "\\\"")
        let cmd = "cd \"\(capturedProjectDir)\" && \"\(python)\" -m src.cli process \"\(escapedPath)\" \(diarizeFlag)"
        await runPipeline(cmd: cmd, projectDir: capturedProjectDir)
    }

    private func runPipeline(cmd: String, projectDir: String) async {
        isProcessing = true
        processingStage = ""
        processingDetail = ""
        processingElapsed = 0
        completedStages = []
        lastError = nil

        processingTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.processingElapsed += 1
            }
        }

        let capturedProjectDir = projectDir
        let (output, exitCode, stderrLog) = await Task.detached { [self] in
            return self.runSubprocessWithProgress(cmd: cmd, projectDir: capturedProjectDir)
        }.value

        processingTimer?.invalidate()
        processingTimer = nil
        isProcessing = false

        if exitCode == 0, let output, !output.isEmpty {
            lastError = nil
            lastNote = output
            sendNotification(title: "Scribe: Note Saved", body: output)
        } else {
            let errorLine = stderrLog
                .components(separatedBy: .newlines)
                .filter { !$0.hasPrefix("{") && !$0.isEmpty }
                .last ?? "Unknown error (exit \(exitCode))"
            lastError = errorLine
            sendNotification(title: "Scribe: Processing Failed", body: errorLine)
        }
    }

    /// Runs a pipeline command, streams stderr for stage markers, returns (stdout, exitCode, fullStderr).
    nonisolated private func runSubprocessWithProgress(cmd: String, projectDir: String) -> (String?, Int32, String) {

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = ["-c", cmd]
        process.currentDirectoryURL = URL(fileURLWithPath: projectDir)

        var env = ProcessInfo.processInfo.environment
        // Prepend Homebrew and conda bin dirs so tools like ffmpeg are found
        let extraPaths = ["/opt/homebrew/bin", "/usr/local/bin"]
        let existingPath = env["PATH"] ?? "/usr/bin:/bin"
        env["PATH"] = extraPaths.joined(separator: ":") + ":" + existingPath
        if let dotenvVars = loadDotEnvSync(projectDir: projectDir) {
            env.merge(dotenvVars) { _, new in new }
        }
        process.environment = env

        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe

        var stderrLines: [String] = []
        let stderrLock = NSLock()

        errPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty,
                  let chunk = String(data: data, encoding: .utf8) else { return }

            for line in chunk.components(separatedBy: .newlines) {
                let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !trimmed.isEmpty else { continue }

                stderrLock.lock()
                stderrLines.append(trimmed)
                stderrLock.unlock()

                // Parse JSON stage markers
                guard let jsonData = trimmed.data(using: .utf8),
                      let obj = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
                      let stage = obj["stage"] as? String else { continue }

                let detail = obj["detail"] as? String ?? ""
                Task { @MainActor [weak self] in
                    guard let self = self else { return }
                    let stageOrder = ["transcribing", "processing", "saving", "done"]
                    if let idx = stageOrder.firstIndex(of: stage), idx > 0 {
                        for i in 0..<idx { self.completedStages.insert(stageOrder[i]) }
                    }
                    if stage == "done" { self.completedStages.insert("saving") }
                    self.processingStage = stage
                    self.processingDetail = detail
                }
            }
        }

        do {
            try process.run()
        } catch {
            return (nil, -1, "Failed to launch process: \(error.localizedDescription)")
        }
        process.waitUntilExit()
        errPipe.fileHandleForReading.readabilityHandler = nil

        // Drain any remaining stderr
        let remaining = errPipe.fileHandleForReading.readDataToEndOfFile()
        if let s = String(data: remaining, encoding: .utf8), !s.isEmpty {
            stderrLock.lock()
            stderrLines.append(contentsOf: s.components(separatedBy: .newlines).filter { !$0.isEmpty })
            stderrLock.unlock()
        }

        let stdout = String(data: outPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let stderrLog = stderrLines.joined(separator: "\n")
        return (stdout, process.terminationStatus, stderrLog)
    }

    // MARK: - Folder Access

    func openNotesFolder() {
        let path = "\(projectDir)/notes"
        ensureDir(path)
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    func openRecordingsFolder() {
        let path = "\(projectDir)/recordings"
        ensureDir(path)
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    private func ensureDir(_ path: String) {
        try? FileManager.default.createDirectory(atPath: path, withIntermediateDirectories: true)
    }

    // MARK: - CLI Helpers

    private func shellCommand(args: [String]) -> String {
        let condaBase = Self.findCondaBase()
        let python = "\(condaBase)/envs/\(condaEnv)/bin/python"
        let cliArgs = args.map { "\"\($0)\"" }.joined(separator: " ")
        return "cd \"\(projectDir)\" && \"\(python)\" -m src.cli \(cliArgs)"
    }

    private func runCLI(args: [String], background: Bool = false) -> Process {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = ["-c", shellCommand(args: args)]
        process.currentDirectoryURL = URL(fileURLWithPath: projectDir)

        var env = ProcessInfo.processInfo.environment
        let extraPaths = ["/opt/homebrew/bin", "/usr/local/bin"]
        let existingPath = env["PATH"] ?? "/usr/bin:/bin"
        env["PATH"] = extraPaths.joined(separator: ":") + ":" + existingPath
        if let dotenvVars = loadDotEnv() {
            env.merge(dotenvVars) { _, new in new }
        }
        process.environment = env

        if !background {
            process.standardOutput = Pipe()
            process.standardError = Pipe()
        }

        try? process.run()
        return process
    }

    // MARK: - Helpers

    private func loadDotEnv() -> [String: String]? {
        return Self.parseDotEnv(at: "\(projectDir)/.env")
    }

    nonisolated private func loadDotEnvSync(projectDir: String) -> [String: String]? {
        return Self.parseDotEnv(at: "\(projectDir)/.env")
    }

    nonisolated private static func parseDotEnv(at path: String) -> [String: String]? {
        guard let contents = try? String(contentsOfFile: path, encoding: .utf8) else { return nil }
        var vars: [String: String] = [:]
        for line in contents.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty, !trimmed.hasPrefix("#"), trimmed.contains("=") else { continue }
            let parts = trimmed.split(separator: "=", maxSplits: 1)
            if parts.count == 2 {
                let key = String(parts[0]).trimmingCharacters(in: .whitespaces)
                var value = String(parts[1]).trimmingCharacters(in: .whitespaces)
                if (value.hasPrefix("\"") && value.hasSuffix("\"")) ||
                   (value.hasPrefix("'") && value.hasSuffix("'")) {
                    value = String(value.dropFirst().dropLast())
                }
                vars[key] = value
            }
        }
        return vars
    }

    nonisolated private static func findCondaBase() -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let candidates = [
            "\(home)/miniconda3",
            "\(home)/anaconda3",
            "\(home)/miniforge3",
            "/opt/homebrew/Caskroom/miniforge/base",
            "/opt/homebrew/Caskroom/miniconda/base",
        ]
        for path in candidates {
            if FileManager.default.fileExists(atPath: "\(path)/envs") {
                return path
            }
        }
        return "\(home)/miniconda3"
    }

    private func requestNotificationPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    private func sendNotification(title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    var formattedTime: String {
        let m = elapsedSeconds / 60
        let s = elapsedSeconds % 60
        return String(format: "%02d:%02d", m, s)
    }

    func stepState(for stage: String) -> StepState {
        if completedStages.contains(stage) { return .done }
        if processingStage == stage { return .active }
        return .pending
    }

    var formattedProcessingTime: String {
        let m = processingElapsed / 60
        let s = processingElapsed % 60
        return String(format: "%02d:%02d", m, s)
    }
}
