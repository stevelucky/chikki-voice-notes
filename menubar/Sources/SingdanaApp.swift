import SwiftUI
import KeyboardShortcuts

extension KeyboardShortcuts.Name {
    static let toggleRecording = Self("toggleRecording", default: .init(.r, modifiers: [.command, .shift]))
    static let quickProcess = Self("quickProcess", default: .init(.r, modifiers: [.command, .shift, .option]))
}

@main
struct ChikkiApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var recorder = RecordingManager.shared

    var body: some Scene {
        MenuBarExtra {
            MenuBarView()
                .environmentObject(recorder)
        } label: {
            Image(systemName: recorder.isRecording ? "record.circle.fill" : "mic.fill")
                .symbolRenderingMode(.palette)
                .foregroundStyle(recorder.isRecording ? .red : .primary)
        }

        Settings {
            SettingsView()
        }
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        KeyboardShortcuts.onKeyUp(for: .toggleRecording) {
            Task { await RecordingManager.shared.toggle() }
        }
    }
}
