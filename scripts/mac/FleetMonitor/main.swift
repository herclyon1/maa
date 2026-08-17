// Fleet monitor for the tailnet: which machines are up, right now.
//
// Everything else in this project reports after the fact - a run finished, a
// script failed, the daily summary. None of it answers the question you
// actually have while standing there: is that machine even on?
//
// Two deliberate choices, both forced by measurement rather than taste:
//
// 1. Dock tile, not a menu-bar item. This file used to carry a status item
//    too. It turned out to render fine - the earlier "nothing was ever drawn"
//    diagnosis was wrong; the menu bar was simply overflowing on a crowded
//    screen, which also kept a debug leftover ("TEST") invisible for two days.
//    But rendered, it duplicated the Dock badge exactly, on the most
//    contested pixels of the screen. One glanceable surface, deliberately:
//    the Dock badge carries the summary, the window carries the detail.
//
// 2. Event-driven, not polled. `watch-ipn-bus` is a long-lived subscription to
//    tailscaled's own message bus; peer state arrives when it changes instead
//    of being asked for on a timer. The interval below is only a backstop for a
//    dead subscription, which is why it is minutes and not seconds.
//
// Both endpoints are read straight off tailscaled's local HTTP API rather than
// through the bundled `Tailscale` CLI. That CLI is not a plain client: it tries
// to start the GUI app, and from a context that cannot do that it prints "The
// Tailscale GUI failed to start" and exits 0, which is indistinguishable from
// success unless the output is parsed. The monitor kept coming up empty at
// login for exactly that reason.
//
// Build:  swiftc -O main.swift -o FleetMonitor
// No linked libraries and no entitlements; it keeps working across Tailscale
// updates because the local API is the same surface the CLI itself uses.

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
    /// Whether a connection is carrying traffic right now.
    let active: Bool
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
    /// Where tailscaled advertises its local HTTP API: a file whose name ends
    /// in the port and whose contents are the password.
    ///
    /// This replaces shelling out to the bundled `Tailscale` CLI, which is not
    /// a plain client - it tries to start the GUI app, and from any context
    /// that cannot do that it answers "The Tailscale GUI failed to start
    /// (CLIError error 3)" with exit status 0. That is why the monitor kept
    /// coming up empty at login while the same command worked in a terminal.
    /// The local API has no such dependency and no subprocess.
    private static let proofDir = "/Library/Tailscale"

    static func endpoint() -> (port: Int, token: String)? {
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: proofDir)
        else { return nil }
        for name in names where name.hasPrefix("sameuserproof-") {
            let port = Int(name.dropFirst("sameuserproof-".count)) ?? 0
            guard port > 0,
                  let token = try? String(contentsOfFile: "\(proofDir)/\(name)", encoding: .utf8)
            else { continue }
            return (port, token.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        return nil
    }

    static func request(_ path: String) -> URLRequest? {
        guard let e = endpoint(),
              let url = URL(string: "http://127.0.0.1:\(e.port)/localapi/v0/\(path)")
        else { return nil }
        var r = URLRequest(url: url)
        // Username is empty; the proof file is the password.
        let auth = Data(":\(e.token)".utf8).base64EncodedString()
        r.setValue("Basic \(auth)", forHTTPHeaderField: "Authorization")
        return r
    }

    static func status() -> [Machine]? {
        guard let req = request("status") else { note("no local API endpoint"); return nil }

        // Synchronous by design: the caller is already on a background queue,
        // and a status read that has not finished is not a status.
        var payload: Data?
        let done = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: req) { d, _, err in
            if let err = err { note("localapi: \(err.localizedDescription)") }
            payload = d
            done.signal()
        }.resume()
        _ = done.wait(timeout: .now() + 8)

        guard let data = payload,
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            note("localapi returned \(payload?.count ?? -1)B, unparseable")
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
            relay: (d["Relay"] as? String) ?? "",
            active: (d["Active"] as? Bool) ?? false
        )
    }

    private static func parseDate(_ s: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: s) ?? ISO8601DateFormatter().date(from: s)
    }
}

/// Per-machine hardware notes, shown on hover rather than on screen.
///
/// The window answers one question - is it up - and every extra line spent on
/// specs is a line competing with that answer. A tooltip costs nothing until
/// someone actually wants it.
///
/// Read from disk rather than probed: the peer is powered off most of the day,
/// which is exactly when you would want to look up what it is.
enum Specs {
    static let path = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/FleetMonitor/specs.json")

    static func load() -> [String: [String: String]] {
        guard let data = try? Data(contentsOf: path),
              let root = try? JSONSerialization.jsonObject(with: data)
                as? [String: [String: String]]
        else { return [:] }
        return root
    }

    /// Order matters: the first two lines are what someone glances at.
    static let order = ["role", "os", "cpu", "gpu", "ram", "disk", "model"]
    static let labels = ["role": "用途", "os": "系统", "cpu": "处理器", "gpu": "显卡",
                         "ram": "内存", "disk": "存储", "model": "机型"]

    /// Optional per-machine display name (the "name" key). The hostname is
    /// whatever the OS installer left behind, and renaming the machine itself
    /// would ripple through every script and document that addresses it - the
    /// window is the one place a friendly name costs nothing.
    static func displayName(for host: String, _ all: [String: [String: String]]) -> String? {
        guard let n = all[host]?["name"], !n.isEmpty else { return nil }
        return n
    }

    static func tooltip(for host: String, _ all: [String: [String: String]]) -> String? {
        guard let spec = all[host] else { return nil }
        let rows = order.compactMap { key -> String? in
            guard let v = spec[key], !v.isEmpty else { return nil }
            return "\(labels[key] ?? key)　\(v)"
        }
        return rows.isEmpty ? nil : ([host, ""] + rows).joined(separator: "\n")
    }
}

// MARK: - Formatting

// The host OS here runs in English, so the app does too - a lone Chinese window
// among English ones reads as something that wandered in from another machine.

func ago(_ date: Date?) -> String {
    guard let d = date, d.timeIntervalSince1970 > 0 else { return "never" }
    let s = Int(Date().timeIntervalSince(d))
    if s < 60 { return "just now" }
    if s < 3600 { return "\(s / 60)m ago" }
    if s < 86400 { return "\(s / 3600)h ago" }
    return "\(s / 86400)d ago"
}

func line(_ m: Machine, as name: String? = nil) -> String {
    let dot = m.online ? "🟢" : "🔴"
    var s = "\(dot) \(name ?? m.host)"
    if m.isSelf { s += "  (this Mac)" }
    s += "\n     \(m.ip)  \(m.os)"
    if !m.isSelf {
        // An idle peer sits on the relay by design and switches to a direct
        // path as soon as traffic starts, so a bare "relay" here reads as a
        // fault when nothing is wrong. Say which it is.
        s += m.online
            ? (m.directAddr != nil ? "  ·  direct"
               : m.active ? "  ·  relay \(m.relay)"
                          : "  ·  idle (direct on use)")
            : "  ·  last seen \(ago(m.lastSeen))"
    }
    return s
}

/// A live subscription to tailscaled's event bus.
///
/// The callback deliberately carries no payload. Decoding the bus format is a
/// moving target across Tailscale releases, whereas the status endpoint is the
/// stable surface - so the bus is only ever used as a doorbell, and the answer
/// still comes from `Tailscale.status()`.
final class BusWatcher: NSObject, URLSessionDataDelegate {
    private let onChange: () -> Void
    private var session: URLSession!
    private var task: URLSessionDataTask?

    init(onChange: @escaping () -> Void) {
        self.onChange = onChange
        super.init()
        let cfg = URLSessionConfiguration.default
        // The whole point is a connection that never completes; without this
        // the stream is torn down after the default timeout and the monitor
        // silently degrades to the backstop timer.
        cfg.timeoutIntervalForRequest = .infinity
        cfg.timeoutIntervalForResource = .infinity
        session = URLSession(configuration: cfg, delegate: self, delegateQueue: nil)
    }

    func start() {
        guard var req = Tailscale.request("watch-ipn-bus?mask=1") else {
            // No endpoint yet - Tailscale may still be starting at login.
            DispatchQueue.global().asyncAfter(deadline: .now() + 15) { self.start() }
            return
        }
        req.timeoutInterval = Double.infinity
        task = session.dataTask(with: req)
        task?.resume()
    }

    func urlSession(_ s: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        onChange()
    }

    func urlSession(_ s: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        // tailscaled restarts (updates, sleep/wake) end the stream. Reconnect,
        // but never in a tight loop.
        DispatchQueue.global().asyncAfter(deadline: .now() + 5) { self.start() }
    }
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
    private var rows: NSStackView!
    private var footer: NSTextField!
    private var watcher: BusWatcher?
    private var lastOnline: [String: Bool] = [:]
    private var machines: [Machine] = []
    private var lastGood: Date?
    /// Backstop only - the bus subscription is what actually drives updates.
    private let heartbeatSeconds: TimeInterval = 300

    func applicationDidFinishLaunching(_ note: Notification) {
        buildWindow()
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }

        refresh()
        Timer.scheduledTimer(withTimeInterval: heartbeatSeconds, repeats: true) { [weak self] _ in
            self?.refresh()
        }
        // The doorbell. Coalesced, because one machine waking pushes a burst of
        // notifications and each would otherwise trigger its own status read.
        watcher = BusWatcher { [weak self] in self?.scheduleRefresh() }
        watcher?.start()
    }

    /// Keep the app alive with no windows; clicking the Dock icon brings it back.
    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ s: NSApplication, hasVisibleWindows: Bool) -> Bool {
        // Belt and braces alongside isReleasedWhenClosed: whatever the reason
        // the window is gone, build a new one rather than message a dead
        // pointer. This is the path that crashed the app on every Dock click
        // after the window had been closed.
        if window == nil { buildWindow() }
        // Ordering front only raises the window within this app; without the
        // activate it stays buried under whatever had focus, which looks
        // exactly like the app failing to open.
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        refresh()
        return true
    }

    private func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 470, height: 340),
                          styleMask: [.titled, .closable, .miniaturizable],
                          backing: .buffered, defer: false)
        // An NSWindow deallocates itself on close by default. This app outlives
        // its window on purpose - closing it is how you dismiss the detail and
        // keep the Dock badge - so the next Dock click was messaging freed
        // memory and taking the process with it.
        window.isReleasedWhenClosed = false
        window.title = "Fleet Monitor"
        window.center()

        rows = NSStackView()
        rows.orientation = .vertical
        rows.alignment = .leading
        rows.spacing = 14
        rows.frame = NSRect(x: 18, y: 46, width: 434, height: 274)
        window.contentView?.addSubview(rows)

        body = NSTextField(labelWithString: "Loading…")
        body.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        body.maximumNumberOfLines = 0
        rows.addArrangedSubview(body)

        footer = NSTextField(labelWithString: "")
        footer.font = .systemFont(ofSize: 10)
        footer.textColor = .secondaryLabelColor
        footer.frame = NSRect(x: 18, y: 16, width: 434, height: 20)
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
            // A failed read is not news about the fleet, so do not throw away
            // what was last known true - blanking the window to an error made
            // a five-second hiccup look like everything had gone dark. Keep the
            // last good answer on screen, say how old it is, and try again soon
            // rather than waiting out the backstop.
            if machines.isEmpty {
                NSApp.dockTile.badgeLabel = "?"
                body.stringValue = "Connecting to Tailscale…"
            }
            footer.stringValue = lastGood.map { "Read failed — showing state from \(ago($0))" }
                ?? "Read failed — retrying…"
            DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self] in
                self?.refresh()
            }
            return
        }
        machines = list
        lastGood = Date()
        let up = list.filter(\.online).count

        // The Dock badge is the whole point of the glanceable half: it is on
        // screen whenever the Dock is, without a window in the way. Setting
        // badgeLabel alone does not always repaint a tile whose icon the app
        // never supplied, so draw the tile ourselves and force it.
        NSApp.dockTile.badgeLabel = "\(up)/\(list.count)"
        NSApp.applicationIconImage = tileIcon(up: up, total: list.count)
        NSApp.dockTile.display()

        // One view per machine, because a tooltip belongs to a view and the
        // specs are per machine. Updated in place when the machine count is
        // unchanged: the bus delivers updates every few seconds while traffic
        // flows, and tearing the rows down destroys whichever one the cursor
        // is on - an open specs tooltip never survived long enough to read.
        let specs = Specs.load()
        let labels = rows.arrangedSubviews.compactMap { $0 as? NSTextField }
        if labels.count == list.count {
            for (label, m) in zip(labels, list) {
                let text = line(m, as: Specs.displayName(for: m.host, specs))
                if label.stringValue != text { label.stringValue = text }
                let tip = Specs.tooltip(for: m.host, specs)
                if label.toolTip != tip { label.toolTip = tip }
            }
        } else {
            rows.arrangedSubviews.forEach { $0.removeFromSuperview() }
            for m in list {
                let label = NSTextField(labelWithString: line(m, as: Specs.displayName(for: m.host, specs)))
                label.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
                label.maximumNumberOfLines = 0
                label.toolTip = Specs.tooltip(for: m.host, specs)
                rows.addArrangedSubview(label)
            }
        }
        let f = DateFormatter(); f.dateFormat = "HH:mm:ss"
        footer.stringValue = "Updated \(f.string(from: Date())) · pushed on change"
        notifyChanges(list)
    }

    /// Only tell the user when something *changed*. A monitor that speaks on
    /// every update is a monitor people mute, and then it protects nothing.
    private func notifyChanges(_ list: [Machine]) {
        let specs = Specs.load()
        for m in list where !m.isSelf {
            if let was = lastOnline[m.host], was != m.online {
                let name = Specs.displayName(for: m.host, specs) ?? m.host
                let n = UNMutableNotificationContent()
                n.title = m.online ? "🟢 \(name) is up" : "🔴 \(name) went offline"
                n.body = m.online ? "Reconnected just now" : "Last seen \(ago(m.lastSeen))"
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
