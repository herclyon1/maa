// Fleet monitor for the tailnet: which machines are up, right now.
//
// Everything else in this project reports after the fact - a run finished, a
// script failed, the daily summary. None of it answers the question you
// actually have while standing there: is that machine even on?
//
// Two deliberate choices, both forced by measurement rather than taste:
//
// 1. Dock tile, not a menu-bar item. A status item was the obvious design and
//    it is what this file used to be, but on this macOS every menu-bar extra on
//    screen is owned by the Control Center process - the system hosts them now -
//    and it declines to adopt an ad-hoc-signed app. The item was created, the
//    button laid out, isVisible was true, and nothing was ever drawn. A plain
//    NSWindow from the same process renders fine, so the Dock badge carries the
//    glanceable summary and the window carries the detail. The status item is
//    still created below: it costs nothing and starts working the day this app
//    is signed with a real identity.
//
// 2. Event-driven, not polled. `tailscale debug watch-ipn` is a long-lived
//    subscription to tailscaled's own message bus; peer state arrives when it
//    changes instead of being asked for on a timer. The interval below is only
//    a backstop for a dead subscription, which is why it is minutes and not
//    seconds.
//
// Build:  swiftc -O main.swift -o FleetMonitor
// It shells out to the Tailscale CLI rather than linking anything, so it keeps
// working across Tailscale updates and needs no entitlements.

import AppKit
import Foundation
import UserNotifications

// MARK: - Model

struct Machine {
    let host: String
    let ip: String
    let os: String
    let online: Bool
    let lastSeen: Date?
    let isSelf: Bool
    /// nil when traffic is relayed rather than peer-to-peer.
    let directAddr: String?
    let relay: String
}

/// Append one line to a debug log. Silent on failure - a monitor that cannot
/// write its own log should still monitor.
func note(_ s: String) {
    let line = "\(Date()) \(s)\n"
    let url = URL(fileURLWithPath: "/tmp/fleetmonitor-debug.log")
    if let h = try? FileHandle(forWritingTo: url) {
        h.seekToEndOfFile(); h.write(Data(line.utf8)); try? h.close()
    } else {
        try? line.write(to: url, atomically: true, encoding: .utf8)
    }
}

enum Tailscale {
    /// Locations Tailscale may live in, most likely first.
    static let candidates = [
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
        "/usr/local/bin/tailscale",
        "/opt/homebrew/bin/tailscale",
    ]

    static var binary: String? {
        candidates.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    static func status() -> [Machine]? {
        guard let bin = binary else { return nil }
        let task = Process()
        task.executableURL = URL(fileURLWithPath: bin)
        task.arguments = ["status", "--json"]
        let pipe = Pipe()
        let errPipe = Pipe()
        task.standardOutput = pipe
        task.standardError = errPipe
        do { try task.run() } catch { note("run failed: \(error)"); return nil }

        // Read before waiting: a full pipe buffer would deadlock the child.
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let errData = errPipe.fileHandleForReading.readDataToEndOfFile()
        task.waitUntilExit()
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            // The CLI's own words are the only thing that explains a failure
            // that only happens when the app is launched at login.
            note("exit=\(task.terminationStatus) out=\(data.count)B "
                 + "[\(String(data: data, encoding: .utf8) ?? "<non-utf8>")] err="
                 + (String(data: errData, encoding: .utf8) ?? "").trimmingCharacters(in: .whitespacesAndNewlines))
            return nil
        }

        var out: [Machine] = []
        if let me = root["Self"] as? [String: Any] { out.append(parse(me, isSelf: true)) }
        if let peers = root["Peer"] as? [String: Any] {
            for (_, v) in peers {
                if let p = v as? [String: Any] { out.append(parse(p, isSelf: false)) }
            }
        }
        // Self first, then offline machines surfaced above online ones - the
        // ones that need attention should not be at the bottom of the list.
        return out.sorted {
            if $0.isSelf != $1.isSelf { return $0.isSelf }
            if $0.online != $1.online { return !$0.online }
            return $0.host.localizedCaseInsensitiveCompare($1.host) == .orderedAscending
        }
    }

    /// Subscribe to tailscaled's message bus and call `onChange` for every
    /// notification it pushes. Never returns; run it off the main thread.
    ///
    /// The callback deliberately carries no payload. Decoding the bus format is
    /// a moving target across Tailscale releases, whereas `status --json` is the
    /// documented surface - so the bus is used only as a doorbell, and the
    /// answer still comes from `status`.
    static func watch(onChange: @escaping () -> Void) {
        guard let bin = binary else { return }
        while true {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: bin)
            task.arguments = ["debug", "watch-ipn"]
            let pipe = Pipe()
            task.standardOutput = pipe
            task.standardError = Pipe()
            do { try task.run() } catch { Thread.sleep(forTimeInterval: 30); continue }

            let handle = pipe.fileHandleForReading
            while true {
                let chunk = handle.availableData
                if chunk.isEmpty { break }  // subscription died; fall through to restart
                onChange()
            }
            task.waitUntilExit()
            // tailscaled restarts (updates, sleep/wake) kill the subscription.
            // Reconnect, but never in a tight loop.
            Thread.sleep(forTimeInterval: 5)
        }
    }

    private static func parse(_ d: [String: Any], isSelf: Bool) -> Machine {
        let addr = (d["CurAddr"] as? String) ?? ""
        return Machine(
            host: (d["HostName"] as? String) ?? "?",
            ip: ((d["TailscaleIPs"] as? [String])?.first) ?? "",
            os: (d["OS"] as? String) ?? "",
            // Self has no Online key; if the CLI answered at all, we are up.
            online: isSelf ? true : ((d["Online"] as? Bool) ?? false),
            lastSeen: (d["LastSeen"] as? String).flatMap(parseDate),
            isSelf: isSelf,
            directAddr: addr.isEmpty ? nil : addr,
            relay: (d["Relay"] as? String) ?? ""
        )
    }

    private static func parseDate(_ s: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: s) ?? ISO8601DateFormatter().date(from: s)
    }
}

// MARK: - Formatting

func ago(_ date: Date?) -> String {
    guard let d = date, d.timeIntervalSince1970 > 0 else { return "从未" }
    let s = Int(Date().timeIntervalSince(d))
    if s < 60 { return "刚刚" }
    if s < 3600 { return "\(s / 60) 分钟前" }
    if s < 86400 { return "\(s / 3600) 小时前" }
    return "\(s / 86400) 天前"
}

func line(_ m: Machine) -> String {
    let dot = m.online ? "🟢" : "🔴"
    var s = "\(dot) \(m.host)"
    if m.isSelf { s += "（本机）" }
    s += "\n     \(m.ip)  \(m.os)"
    if !m.isSelf {
        s += m.online
            ? (m.directAddr != nil ? "  ·  直连" : "  ·  中继 \(m.relay)")
            : "  ·  最后在线 \(ago(m.lastSeen))"
    }
    return s
}

/// The Dock icon, drawn rather than shipped: green when the whole fleet is up,
/// red the moment one machine is not. The colour is what carries across a
/// glance at the Dock; the badge underneath it gives the count.
func tileIcon(up: Int, total: Int) -> NSImage {
    let size = NSSize(width: 128, height: 128)
    let img = NSImage(size: size)
    img.lockFocus()
    let allUp = up == total
    let bg = allUp ? NSColor.systemGreen : NSColor.systemRed
    let r = NSBezierPath(roundedRect: NSRect(x: 8, y: 8, width: 112, height: 112),
                         xRadius: 26, yRadius: 26)
    bg.setFill()
    r.fill()
    let text = "\(up)/\(total)" as NSString
    let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 40, weight: .bold),
        .foregroundColor: NSColor.white,
    ]
    let ts = text.size(withAttributes: attrs)
    text.draw(at: NSPoint(x: (size.width - ts.width) / 2,
                          y: (size.height - ts.height) / 2),
              withAttributes: attrs)
    img.unlockFocus()
    return img
}

// MARK: - App

final class Controller: NSObject, NSApplicationDelegate {
    private var window: NSWindow!
    private var body: NSTextField!
    private var footer: NSTextField!
    private var statusItem: NSStatusItem?
    private var lastOnline: [String: Bool] = [:]
    private var machines: [Machine] = []
    /// Backstop only - the bus subscription is what actually drives updates.
    private let heartbeatSeconds: TimeInterval = 300

    func applicationDidFinishLaunching(_ note: Notification) {
        buildWindow()
        // Harmless where the system refuses to host it; correct the day it does.
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }

        refresh()
        Timer.scheduledTimer(withTimeInterval: heartbeatSeconds, repeats: true) { [weak self] _ in
            self?.refresh()
        }
        // The doorbell. Coalesced, because one user action (a machine waking)
        // pushes a burst of notifications and each would otherwise fork a CLI.
        DispatchQueue.global(qos: .utility).async {
            Tailscale.watch { [weak self] in self?.scheduleRefresh() }
        }
    }

    /// Keep the app alive with no windows; clicking the Dock icon brings it back.
    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ s: NSApplication, hasVisibleWindows: Bool) -> Bool {
        // Ordering front only raises the window within this app; without the
        // activate it stays buried under whatever had focus, which looks
        // exactly like the app failing to open.
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        return true
    }

    private func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 380, height: 340),
                          styleMask: [.titled, .closable, .miniaturizable],
                          backing: .buffered, defer: false)
        window.title = "舰队监控"
        window.center()

        body = NSTextField(labelWithString: "读取中…")
        body.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        body.frame = NSRect(x: 18, y: 46, width: 344, height: 274)
        body.maximumNumberOfLines = 0
        window.contentView?.addSubview(body)

        footer = NSTextField(labelWithString: "")
        footer.font = .systemFont(ofSize: 10)
        footer.textColor = .secondaryLabelColor
        footer.frame = NSRect(x: 18, y: 16, width: 344, height: 20)
        window.contentView?.addSubview(footer)

        window.makeKeyAndOrderFront(nil)
    }

    private var pending = false

    /// Collapse a burst of bus notifications into one status read.
    private func scheduleRefresh() {
        DispatchQueue.main.async {
            guard !self.pending else { return }
            self.pending = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                self.pending = false
                self.refresh()
            }
        }
    }

    @objc private func refresh() {
        // Off the main thread: the CLI can block for seconds when the network
        // is unhappy, and a frozen UI is worse than a stale count.
        DispatchQueue.global(qos: .utility).async {
            let result = Tailscale.status()
            DispatchQueue.main.async { self.apply(result) }
        }
    }

    private func apply(_ result: [Machine]?) {
        guard let list = result else {
            NSApp.dockTile.badgeLabel = "!"
            body.stringValue = Tailscale.binary == nil
                ? "找不到 Tailscale" : "读不到 Tailscale 状态"
            return
        }
        machines = list
        let up = list.filter(\.online).count

        // The Dock badge is the whole point of the glanceable half: it is on
        // screen whenever the Dock is, without a window in the way. Setting
        // badgeLabel alone does not always repaint a tile whose icon the app
        // never supplied, so draw the tile ourselves and force it.
        NSApp.dockTile.badgeLabel = "\(up)/\(list.count)"
        NSApp.applicationIconImage = tileIcon(up: up, total: list.count)
        NSApp.dockTile.display()
        statusItem?.button?.title = (up == list.count ? "🟢" : "🔴") + " \(up)/\(list.count)"

        body.stringValue = list.map(line).joined(separator: "\n\n")
        let f = DateFormatter(); f.dateFormat = "HH:mm:ss"
        footer.stringValue = "\(f.string(from: Date())) 更新 · 事件驱动，非轮询"
        notifyChanges(list)
    }

    /// Only tell the user when something *changed*. A monitor that speaks on
    /// every update is a monitor people mute, and then it protects nothing.
    private func notifyChanges(_ list: [Machine]) {
        for m in list where !m.isSelf {
            if let was = lastOnline[m.host], was != m.online {
                let n = UNMutableNotificationContent()
                n.title = m.online ? "🟢 \(m.host) 上线" : "🔴 \(m.host) 掉线"
                n.body = m.online ? "刚刚恢复连接" : "最后在线：\(ago(m.lastSeen))"
                UNUserNotificationCenter.current().add(
                    UNNotificationRequest(identifier: UUID().uuidString,
                                          content: n, trigger: nil))
            }
            lastOnline[m.host] = m.online
        }
    }
}

let app = NSApplication.shared
let controller = Controller()
app.delegate = controller
app.setActivationPolicy(.regular)   // Dock tile carries the badge
app.run()
