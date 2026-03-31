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

    private var recordProcess: Process?
    private var timer: Timer?
    private var processingTimer: Timer?

    let projectDir: String
    private let condaEnv = "chikki"

    private init() {
        projectDir = Self.resolveProjectDir()
        requestNotificationPermission()
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

        let fallback = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("codes/chikki").path
        if FileManager.default.fileExists(atPath: fallback + "/config.yaml") {
            return fallback
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

        sendNotification(title: "Chikki", body: "Recording started. Press Cmd+Shift+R to stop.")
        recordProcess = runCLI(args: ["record", "--duration", "0"], background: true)
    }

    func stopRecording() async {
        guard isRecording else { return }

        if let proc = recordProcess, proc.isRunning {
            proc.interrupt()
            proc.waitUntilExit()
        }
        recordProcess = nil

        timer?.invalidate()
        timer = nil
        isRecording = false

        sendNotification(title: "Chikki", body: "Recording stopped. Processing...")
        await processLatest()
    }

    func processLatest() async {
        isProcessing = true
        processingStage = ""
        processingDetail = ""
        processingElapsed = 0
        completedStages = []

        // Start processing timer
        processingTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.processingElapsed += 1
            }
        }

        // Run off main thread, streaming stderr for stage updates
        let result: String? = await Task.detached { [self] in
            return self.runProcessLatestWithProgress()
        }.value

        processingTimer?.invalidate()
        processingTimer = nil
        isProcessing = false

        if let result = result, !result.isEmpty {
            lastNote = result
            sendNotification(title: "Chikki: Note Saved", body: result)
        } else {
            sendNotification(title: "Chikki", body: "Processing failed. Try: python -m src.cli process-latest")
        }
    }

    /// Runs process-latest and streams stderr for stage markers
    nonisolated private func runProcessLatestWithProgress() -> String? {
        let condaBase = Self.findCondaBase()
        let python = "\(condaBase)/envs/granola/bin/python"
        let cmd = "cd \"\(projectDir)\" && \"\(python)\" -m src.cli process-latest"

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = ["-c", cmd]
        process.currentDirectoryURL = URL(fileURLWithPath: projectDir)

        var env = ProcessInfo.processInfo.environment
        if let dotenvVars = loadDotEnvSync() {
            env.merge(dotenvVars) { _, new in new }
        }
        process.environment = env

        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe

        // Read stderr line-by-line for stage markers
        errPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty,
                  let line = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !line.isEmpty else { return }

            // Try to parse JSON stage markers
            for part in line.components(separatedBy: .newlines) {
                guard let jsonData = part.data(using: .utf8),
                      let obj = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
                      let stage = obj["stage"] as? String else { continue }

                let detail = obj["detail"] as? String ?? ""
                Task { @MainActor [weak self] in
                    guard let self = self else { return }
                    // Mark previous stage as completed
                    let stageOrder = ["transcribing", "processing", "saving", "done"]
                    if let idx = stageOrder.firstIndex(of: stage), idx > 0 {
                        for i in 0..<idx {
                            self.completedStages.insert(stageOrder[i])
                        }
                    }
                    if stage == "done" {
                        self.completedStages.insert("saving")
                    }
                    self.processingStage = stage
                    self.processingDetail = detail
                }
            }
        }

        try? process.run()
        process.waitUntilExit()

        errPipe.fileHandleForReading.readabilityHandler = nil

        let data = outPipe.fileHandleForReading.readDataToEndOfFile()
        return String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
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

    nonisolated private func loadDotEnvSync() -> [String: String]? {
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
