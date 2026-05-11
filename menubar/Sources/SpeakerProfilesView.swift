import SwiftUI

struct SpeakerProfile: Identifiable, Codable {
    var id: String { name }
    var name: String
    var role: String
    var notes: String
    var enrolled: Bool
}

struct SpeakerProfilesView: View {
    @AppStorage("projectDir") private var projectDir: String = ""
    @State private var profiles: [SpeakerProfile] = []
    @State private var showAddSheet = false
    @State private var enrollingName: String? = nil
    @State private var statusMessage: String = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if profiles.isEmpty {
                Text("No speakers enrolled yet.\nAdd a speaker to enable automatic identification.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 20)
            } else {
                List {
                    ForEach(profiles) { profile in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(profile.name).fontWeight(.medium)
                                if !profile.role.isEmpty {
                                    Text(profile.role).font(.caption).foregroundStyle(.secondary)
                                }
                                if !profile.notes.isEmpty {
                                    Text(profile.notes).font(.caption2).foregroundStyle(.tertiary)
                                }
                            }
                            Spacer()
                            if profile.enrolled {
                                Image(systemName: "checkmark.circle.fill")
                                    .foregroundStyle(.green)
                                    .help("Voice sample enrolled")
                            } else {
                                Image(systemName: "mic.badge.plus")
                                    .foregroundStyle(.orange)
                                    .help("No voice sample — click to enroll")
                            }
                        }
                        .contextMenu {
                            Button("Delete \(profile.name)", role: .destructive) {
                                deleteSpeaker(profile.name)
                            }
                        }
                    }
                }
                .listStyle(.plain)
            }

            if !statusMessage.isEmpty {
                Text(statusMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
                    .padding(.bottom, 4)
            }

            Divider()

            HStack {
                Button("Add Speaker...") { showAddSheet = true }
                    .buttonStyle(.borderedProminent)
                Spacer()
                Text("Right-click to delete")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            .padding(8)
        }
        .frame(width: 360, height: 300)
        .onAppear { loadProfiles() }
        .sheet(isPresented: $showAddSheet, onDismiss: loadProfiles) {
            AddSpeakerSheet(projectDir: projectDir)
        }
    }

    private func loadProfiles() {
        let path = "\(projectDir)/speakers/profiles.json"
        guard let data = FileManager.default.contents(atPath: path),
              let raw = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
            profiles = []
            return
        }
        profiles = raw.map { dict in
            SpeakerProfile(
                name: dict["name"] as? String ?? "",
                role: dict["role"] as? String ?? "",
                notes: dict["notes"] as? String ?? "",
                enrolled: dict["embedding"] != nil
            )
        }
    }

    private func deleteSpeaker(_ name: String) {
        let condaBase = RecordingManager.findCondaBase()
        let python = "\(condaBase)/envs/chikki/bin/python"
        let cmd = "cd \"\(projectDir)\" && \"\(python)\" -m src.cli delete-speaker \"\(name)\""
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = ["-c", cmd]
        try? process.run()
        process.waitUntilExit()
        loadProfiles()
    }
}

struct AddSpeakerSheet: View {
    let projectDir: String
    @Environment(\.dismiss) private var dismiss

    @State private var name = ""
    @State private var role = ""
    @State private var notes = ""
    @State private var recordingState: RecordingState = .idle
    @State private var recordProcess: Process?
    @State private var recordedFilePath: String = ""
    @State private var enrollStatus = ""
    @State private var isEnrolling = false

    enum RecordingState { case idle, recording, recorded }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Add Speaker").font(.headline)

            Form {
                TextField("Full Name *", text: $name)
                TextField("Role / Title", text: $role)
                TextField("Notes", text: $notes)
            }
            .formStyle(.grouped)
            .frame(height: 160)

            Divider()

            VStack(alignment: .leading, spacing: 8) {
                Text("Voice Sample").fontWeight(.medium)
                Text("Have the speaker read the following aloud:")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Text("""
                    "My name is \(name.isEmpty ? "[name]" : name). \
                    I work in \(role.isEmpty ? "[your field]" : role). \
                    The quick brown fox jumps over the lazy dog. \
                    In meetings, I often discuss project updates, priorities, and next steps. \
                    Clear communication helps our team move faster and stay aligned."
                    """)
                    .font(.caption)
                    .foregroundStyle(.primary)
                    .padding(8)
                    .background(Color.secondary.opacity(0.1))
                    .clipShape(RoundedRectangle(cornerRadius: 6))

                HStack(spacing: 12) {
                    switch recordingState {
                    case .idle:
                        Button("Start Recording") { startRecording() }
                            .buttonStyle(.bordered)
                            .disabled(name.isEmpty)
                    case .recording:
                        Button("Stop Recording") { stopRecording() }
                            .buttonStyle(.borderedProminent)
                            .tint(.red)
                    case .recorded:
                        Button("Re-record") { startRecording() }
                            .buttonStyle(.bordered)
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                        Text("Sample ready").font(.caption).foregroundStyle(.secondary)
                    }
                }

                if !enrollStatus.isEmpty {
                    Text(enrollStatus)
                        .font(.caption)
                        .foregroundStyle(enrollStatus.contains("✓") ? .green : .secondary)
                }
            }

            HStack {
                Button("Cancel") { dismiss() }
                Spacer()
                Button("Enroll Speaker") { enroll() }
                    .buttonStyle(.borderedProminent)
                    .disabled(name.isEmpty || recordingState != .recorded || isEnrolling)
            }
        }
        .padding(20)
        .frame(width: 400)
    }

    private func startRecording() {
        let tmpPath = NSTemporaryDirectory() + "scribe_sample_\(Int(Date().timeIntervalSince1970)).wav"
        recordedFilePath = tmpPath

        let condaBase = RecordingManager.findCondaBase()
        let python = "\(condaBase)/envs/chikki/bin/python"
        let cmd = "cd \"\(projectDir)\" && \"\(python)\" -m src.cli record --duration 0 --output \"\(tmpPath)\""

        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + (env["PATH"] ?? "/usr/bin:/bin")
        if let dotenv = RecordingManager.parseDotEnvStatic(at: "\(projectDir)/.env") {
            env.merge(dotenv) { _, new in new }
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = ["-c", cmd]
        process.environment = env
        try? process.run()
        recordProcess = process
        recordingState = .recording
    }

    private func stopRecording() {
        recordProcess?.interrupt()
        recordProcess = nil
        recordingState = .recorded
    }

    private func enroll() {
        guard !recordedFilePath.isEmpty else { return }
        isEnrolling = true
        enrollStatus = "Computing voice embedding..."

        Task.detached {
            let condaBase = RecordingManager.findCondaBase()
            let python = "\(condaBase)/envs/chikki/bin/python"
            let escapedName = name.replacingOccurrences(of: "\"", with: "\\\"")
            let escapedRole = role.replacingOccurrences(of: "\"", with: "\\\"")
            let escapedNotes = notes.replacingOccurrences(of: "\"", with: "\\\"")
            let escapedSample = recordedFilePath.replacingOccurrences(of: "\"", with: "\\\"")
            let cmd = """
                cd "\(projectDir)" && "\(python)" -m src.cli enroll-speaker "\(escapedSample)" \
                --name "\(escapedName)" --role "\(escapedRole)" --notes "\(escapedNotes)"
                """

            var env = ProcessInfo.processInfo.environment
            let extraPaths = ["/opt/homebrew/bin", "/usr/local/bin"]
            env["PATH"] = extraPaths.joined(separator: ":") + ":" + (env["PATH"] ?? "/usr/bin:/bin")
            if let dotenv = RecordingManager.parseDotEnvStatic(at: "\(projectDir)/.env") {
                env.merge(dotenv) { _, new in new }
            }

            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/zsh")
            process.arguments = ["-c", cmd]
            process.environment = env
            let errPipe = Pipe()
            process.standardError = errPipe

            do {
                try process.run()
                process.waitUntilExit()
            } catch {
                await MainActor.run {
                    self.enrollStatus = "Failed: \(error.localizedDescription)"
                    self.isEnrolling = false
                }
                return
            }

            let success = process.terminationStatus == 0
            await MainActor.run {
                self.isEnrolling = false
                if success {
                    self.enrollStatus = "✓ Enrolled successfully"
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { self.dismiss() }
                } else {
                    let errOutput = String(data: errPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                    let lastLine = errOutput.components(separatedBy: .newlines).filter { !$0.isEmpty }.last ?? "Unknown error"
                    self.enrollStatus = "Error: \(lastLine)"
                }
            }
        }
    }
}
