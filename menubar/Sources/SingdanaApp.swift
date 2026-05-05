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
            if recorder.isRecording {
                Image(nsImage: Self.recordingPillIcon)
            } else if recorder.isProcessing {
                Image(nsImage: Self.processingPillIcon)
            } else {
                Image(systemName: "mic.fill")
            }
        }
    }

    // Pre-rendered full-color pill icons — avoids template-mode color stripping in menu bar
    static let recordingPillIcon: NSImage = pillIcon(
        symbol: "mic.fill", background: .red
    )
    static let processingPillIcon: NSImage = pillIcon(
        symbol: "waveform", background: Color(red: 0.95, green: 0.75, blue: 0.0), foreground: .black
    )

    private static func pillIcon(symbol: String, background: Color, foreground: Color = .white) -> NSImage {
        let view = ZStack {
            Capsule().fill(background)
            Image(systemName: symbol)
                .font(.system(size: 12, weight: .semibold))
                .foregroundColor(foreground)
        }
        .frame(width: 36, height: 20)

        let renderer = ImageRenderer(content: view)
        renderer.scale = 2.0
        let img = renderer.nsImage ?? NSImage()
        img.isTemplate = false
        return img
    }
}

class SettingsWindowController {
    static let shared = SettingsWindowController()
    private var window: NSWindow?

    func show() {
        if window == nil {
            let controller = NSHostingController(rootView: SettingsView())
            let win = NSWindow(contentViewController: controller)
            win.title = "Chikki Settings"
            win.styleMask = [.titled, .closable, .miniaturizable]
            win.setContentSize(NSSize(width: 440, height: 420))
            win.center()
            win.isReleasedWhenClosed = false
            window = win
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        KeyboardShortcuts.onKeyUp(for: .toggleRecording) {
            Task { await RecordingManager.shared.toggle() }
        }
    }
}
