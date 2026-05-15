import SwiftUI
import KeyboardShortcuts

extension KeyboardShortcuts.Name {
    static let toggleRecording = Self("toggleRecording", default: .init(.r, modifiers: [.command, .shift]))
    static let quickProcess = Self("quickProcess", default: .init(.r, modifiers: [.command, .shift, .option]))
}

@main
struct ScribeApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var recorder = RecordingManager.shared

    var body: some Scene {
        MenuBarExtra {
            MenuBarView()
                .environmentObject(recorder)
        } label: {
            if recorder.isRecording {
                Image(nsImage: recorder.recordingBarIcon)
            } else if recorder.isProcessing {
                Image(nsImage: Self.processingPillIcon)
            } else {
                Image(nsImage: Self.idleMicIcon)
            }
        }
    }

    // Custom idle mic icon — loaded from bundle, template so it adapts to light/dark mode
    static let idleMicIcon: NSImage = {
        let img = NSImage(named: "mic_idle") ?? NSImage(systemSymbolName: "mic.fill", accessibilityDescription: nil) ?? NSImage()
        img.isTemplate = true
        return img
    }()

    // Pre-rendered full-color pill icons — avoids template-mode color stripping in menu bar
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
            win.title = "Scribe Settings"
            win.styleMask = [.titled, .closable, .miniaturizable]
            win.setContentSize(NSSize(width: 460, height: 360))
            win.center()
            win.isReleasedWhenClosed = false
            window = win
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}

class SpeakerWindowController {
    static let shared = SpeakerWindowController()
    private var window: NSWindow?

    func show() {
        if window == nil {
            let controller = NSHostingController(rootView: SpeakerProfilesView())
            let win = NSWindow(contentViewController: controller)
            win.title = "Manage Speakers"
            win.styleMask = [.titled, .closable]
            win.setContentSize(NSSize(width: 360, height: 320))
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

    func applicationWillTerminate(_ notification: Notification) {
        RecordingManager.shared.terminateSubprocesses()
    }
}
