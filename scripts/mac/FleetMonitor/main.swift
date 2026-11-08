// Fleet monitor for the tailnet: which machines answer, right now. Dock tile = summary; the window,
// opened from the Dock, = detail. Driven by tailscaled's watch-ipn-bus, a 20 s timer as backstop.
// "Up" means it answered a disco ping, not that Tailscale lists it online (2026-09-03: the game PC
// read "Online" four hours after power-off). It opens no connection to any peer: the TCP link to
// port 22 it kept until 2026-11-09 marked the Redmi (no sshd) offline and piled unauthenticated
// sockets on the game PC's sshd. Only tailscaled's local HTTP API is used - from a login item the
// bundled CLI prints "GUI failed to start" and exits 0. Build: scripts/mac/build-fleetmonitor.sh

import AppKit
import Foundation
import Network

struct Probe {
    let answered, direct: Bool    // direct: the reply came peer-to-peer rather than via DERP
    let ms: Int
    static let none = Probe(answered: false, direct: false, ms: 0)
}

struct Machine {
    let host, ip, os, relay: String
    let online, isSelf: Bool
    let lastSeen: Date?
    let directAddr: String?   // nil when traffic is relayed
    let probe: Probe?
    let noReply: Bool         // Tailscale lists it as up, but it did not answer
    func with(_ p: Probe?) -> Machine {
        Machine(host: host, ip: ip, os: os, relay: relay, online: p != nil, isSelf: isSelf,
                lastSeen: lastSeen, directAddr: directAddr, probe: p, noReply: p == nil)
    }
}

/// Append a line to /tmp/fleetmonitor-debug.log; silent on failure.
func note(_ s: String) {
    let line = Data("\(Date()) \(s)\n".utf8), url = URL(fileURLWithPath: "/tmp/fleetmonitor-debug.log")
    if let h = try? FileHandle(forWritingTo: url) { h.seekToEndOfFile(); h.write(line); try? h.close() }
    else { try? line.write(to: url) }
}

enum Tailscale {
    private static let dir = "/Library/Tailscale"
    /// Port and password of the local API. `ipnport` is a symlink to the current port (what the CLI
    /// itself reads) and `sameuserproof-<port>` holds the password. Without the symlink take the newest
    /// proof file, so a stale one left by an older tailscaled cannot win.
    static func endpoint() -> (port: Int, token: String)? {
        let fm = FileManager.default
        let read = { (n: String) in (try? String(contentsOfFile: "\(dir)/\(n)", encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines) }
        if let p = try? fm.destinationOfSymbolicLink(atPath: "\(dir)/ipnport"), let port = Int(p),
           let t = read("sameuserproof-\(port)") { return (port, t) }
        let mtime = { (n: String) in ((try? fm.attributesOfItem(atPath: "\(dir)/\(n)"))?[.modificationDate] as? Date) ?? .distantPast }
        let proofs = ((try? fm.contentsOfDirectory(atPath: dir)) ?? []).filter { $0.hasPrefix("sameuserproof-") }
        for name in proofs.sorted(by: { mtime($0) > mtime($1) }) {
            // sameuserproof-<port> (password inside) or sameuserproof-<port>-<password>
            let parts = name.dropFirst("sameuserproof-".count).split(separator: "-", maxSplits: 1).map(String.init)
            if let port = Int(parts.first ?? ""), let t = parts.count > 1 ? parts[1] : read(name) { return (port, t) }
        }
        return nil
    }
    /// No URL cache: tailscaled sends no Cache-Control, and on 2026-09-07 a cached ping reply kept
    /// saying "114ms" for an hour after the game PC was off.
    static let session: URLSession = {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.urlCache = nil; cfg.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        return URLSession(configuration: cfg)
    }()
    static func request(_ path: String) -> URLRequest? {
        guard let e = endpoint(), let url = URL(string: "http://127.0.0.1:\(e.port)/localapi/v0/\(path)") else { return nil }
        var r = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalAndRemoteCacheData)
        r.setValue("Basic \(Data(":\(e.token)".utf8).base64EncodedString())", forHTTPHeaderField: "Authorization")
        return r
    }
    /// One synchronous JSON call; nil on timeout, error or a body that is not a JSON object.
    static func call(_ req: URLRequest, wait: TimeInterval) -> [String: Any]? {
        let lock = NSLock(), done = DispatchSemaphore(value: 0)
        var body: Data?
        let task = session.dataTask(with: req) { d, _, err in
            if let err = err, (err as? URLError)?.code != .timedOut { note("localapi: \(err.localizedDescription)") }
            lock.lock(); body = d; lock.unlock(); done.signal()
        }
        task.resume()
        _ = done.wait(timeout: .now() + wait)
        task.cancel()
        lock.lock(); defer { lock.unlock() }
        return body.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
    }
    /// A disco ping: answered by tailscaled itself, so Windows dropping ICMP cannot make a running
    /// machine look dead. A machine that is off never answers and the call runs into its timeout.
    static func probe(_ ip: String, timeout: TimeInterval = 4) -> Probe {
        guard !ip.isEmpty, var req = request("ping?ip=\(ip)&type=disco") else { return .none }
        req.httpMethod = "POST"; req.timeoutInterval = timeout
        // An error reply is not the peer answering (pinging our own IP says "is local Tailscale IP").
        guard let o = call(req, wait: timeout + 2), ((o["Err"] as? String) ?? "").isEmpty,
              let s = o["LatencySeconds"] as? Double, s > 0 else { return .none }
        return Probe(answered: true, direct: !((o["Endpoint"] as? String) ?? "").isEmpty, ms: Int((s * 1000).rounded()))
    }
    // Guarded by `lock`. Only answered pings are cached: a cached miss used to stand in for the
    // re-check, so one dropped packet turned a running machine red without a second real ping.
    // `recheck`: a machine went silent for the first time - read again in seconds, not at the heartbeat.
    private static let lock = NSLock()
    private static var cache: [String: (probe: Probe, at: Date)] = [:], misses: [String: Int] = [:], recheck = false
    private static let probeReuseSeconds: TimeInterval = 15   // a ping is traffic, and traffic rings the bus
    static func takeRecheck() -> Bool { lock.lock(); defer { recheck = false; lock.unlock() }; return recheck }
    static func status() -> [Machine]? {
        guard let req = request("status") else { note("no local API endpoint"); return nil }
        guard let root = call(req, wait: 8) else { note("localapi status unreadable"); return nil }
        var out = (root["Self"] as? [String: Any]).map { [parse($0, isSelf: true)] } ?? []
        for case let p as [String: Any] in (root["Peer"] as? [String: Any] ?? [:]).values { out.append(parse(p, isSelf: false)) }
        let group = DispatchGroup(), answersLock = NSLock()
        var answers: [String: Probe] = [:]
        for m in out where !m.isSelf && m.online {
            lock.lock(); let c = cache[m.ip]; lock.unlock()
            if let c = c, Date().timeIntervalSince(c.at) < probeReuseSeconds { answersLock.lock(); answers[m.ip] = c.probe; answersLock.unlock(); continue }
            DispatchQueue.global(qos: .utility).async(group: group) {
                var p = probe(m.ip)
                if !p.answered { p = probe(m.ip) }      // one dropped packet is not a verdict
                answersLock.lock(); answers[m.ip] = p; answersLock.unlock()
            }
        }
        _ = group.wait(timeout: .now() + 20)
        answersLock.lock(); let got = answers; answersLock.unlock()
        lock.lock()
        out = out.map { m in
            guard let p = got[m.ip] else { return m }
            if p.answered { cache[m.ip] = (p, Date()); misses[m.ip] = 0; return m.with(p) }
            cache.removeValue(forKey: m.ip)
            // Two silent reads in a row: a booting machine answers by the second one, an off one never.
            let n = misses[m.ip, default: 0] + 1; misses[m.ip] = n
            if n < 2 { recheck = true }
            return n >= 2 ? m.with(nil) : m
        }
        lock.unlock()
        return out.sorted {   // self first, then the machines needing attention
            $0.isSelf != $1.isSelf ? $0.isSelf : $0.online != $1.online ? !$0.online
                : $0.host.localizedCaseInsensitiveCompare($1.host) == .orderedAscending
        }
    }
    private static func parse(_ d: [String: Any], isSelf: Bool) -> Machine {
        let addr = (d["CurAddr"] as? String) ?? "", f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let seen = (d["LastSeen"] as? String).flatMap { f.date(from: $0) ?? ISO8601DateFormatter().date(from: $0) }
        return Machine(host: (d["HostName"] as? String) ?? "?", ip: ((d["TailscaleIPs"] as? [String])?.first) ?? "",
                       os: (d["OS"] as? String) ?? "", relay: (d["Relay"] as? String) ?? "",
                       online: isSelf || ((d["Online"] as? Bool) ?? false), isSelf: isSelf, lastSeen: seen,
                       directAddr: addr.isEmpty ? nil : addr, probe: nil, noReply: false)
    }
}

/// Whether this Mac has a network path at all: without one every machine reads silent, which is not the fleet being off.
final class LocalNet {
    private let monitor = NWPathMonitor(), lock = NSLock()
    private var up = true
    var onChange: (() -> Void)?
    var isUp: Bool { lock.lock(); defer { lock.unlock() }; return up }
    func start() {
        monitor.pathUpdateHandler = { [weak self] path in
            guard let self = self else { return }
            self.lock.lock(); let changed = self.up != (path.status == .satisfied)
            self.up = path.status == .satisfied; self.lock.unlock()
            if changed { DispatchQueue.main.async { self.onChange?() } }
        }
        monitor.start(queue: DispatchQueue(label: "fleetmonitor.localnet"))
    }
}

/// Per-machine display name and hardware tooltip, read from disk because the PC is off most of the day.
enum Specs {
    static let order = ["role", "os", "cpu", "gpu", "ram", "disk", "model"]
    static let labels = ["role": "用途", "os": "系统", "cpu": "处理器", "gpu": "显卡", "ram": "内存", "disk": "存储", "model": "机型"]
    static func load() -> [String: [String: String]] {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/FleetMonitor/specs.json")
        return (try? Data(contentsOf: url)).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: [String: String]] } ?? [:]
    }
    static func name(_ host: String, _ all: [String: [String: String]]) -> String? { all[host]?["name"].flatMap { $0.isEmpty ? nil : $0 } }
    static func tooltip(_ host: String, _ all: [String: [String: String]]) -> String? {
        guard let spec = all[host] else { return nil }
        let rows = order.compactMap { k in spec[k].flatMap { $0.isEmpty ? nil : "\(labels[k] ?? k)　\($0)" } }
        return rows.isEmpty ? nil : ([host, ""] + rows).joined(separator: "\n")
    }
}

func ago(_ date: Date?) -> String {
    guard let d = date, d.timeIntervalSince1970 > 0 else { return "never" }
    let s = Int(Date().timeIntervalSince(d))
    return s < 60 ? "just now" : s < 3600 ? "\(s / 60)m ago" : s < 86400 ? "\(s / 3600)h ago" : "\(s / 86400)d ago"
}

func line(_ m: Machine, as name: String?, seen: Date?) -> String {
    let s = "\(m.online ? "🟢" : "🔴") \(name ?? m.host)\(m.isSelf ? "  (this Mac)" : "")\n     \(m.ip)  \(m.os)"
    if m.isSelf { return s }
    // Path from the ping itself: the ping is traffic, so `Active` would always say relay.
    if m.online, let p = m.probe { return s + (p.direct ? "  ·  direct" : "  ·  relay \(m.relay)") + "  ·  \(p.ms)ms" }
    if m.online { return s + (m.directAddr != nil ? "  ·  direct" : "  ·  idle (direct on use)") }
    if m.noReply { return s + "  ·  no reply — powered off" }
    // An offline peer often comes back with a zero LastSeen; fall back to when we last saw it up.
    let stamp = m.lastSeen.flatMap { $0.timeIntervalSince1970 > 0 ? $0 : nil } ?? seen
    return s + (stamp == nil ? "  ·  offline" : "  ·  offline, last seen \(ago(stamp))")
}

/// tailscaled's event bus, used only as a doorbell: the answer always comes from `status()`.
final class BusWatcher: NSObject, URLSessionDataDelegate {
    private let onChange: () -> Void
    private var session: URLSession!
    init(onChange: @escaping () -> Void) {
        self.onChange = onChange
        super.init()
        let cfg = URLSessionConfiguration.default      // the stream is meant never to complete
        cfg.timeoutIntervalForRequest = .infinity; cfg.timeoutIntervalForResource = .infinity
        session = URLSession(configuration: cfg, delegate: self, delegateQueue: nil)
    }
    func start() {
        guard var req = Tailscale.request("watch-ipn-bus?mask=1") else {
            DispatchQueue.global().asyncAfter(deadline: .now() + 15) { self.start() }   // Tailscale still starting
            return
        }
        req.timeoutInterval = .infinity
        session.dataTask(with: req).resume()
    }
    func urlSession(_ s: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) { onChange() }
    func urlSession(_ s: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        DispatchQueue.global().asyncAfter(deadline: .now() + 5) { self.start() }      // tailscaled restarted
    }
}

/// Green from two machines up (the user, 2026-09-12: the game PC is off most of the day, 2/3 is normal).
func tileIcon(up: Int, total: Int) -> NSImage {
    let size = NSSize(width: 128, height: 128), img = NSImage(size: size)
    img.lockFocus()
    (up >= 2 || up == total ? NSColor.systemGreen : NSColor.systemRed).setFill()
    NSBezierPath(roundedRect: NSRect(x: 8, y: 8, width: 112, height: 112), xRadius: 26, yRadius: 26).fill()
    let text = "\(up)/\(total)" as NSString
    let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 40, weight: .bold), .foregroundColor: NSColor.white]
    let ts = text.size(withAttributes: attrs)
    text.draw(at: NSPoint(x: (size.width - ts.width) / 2, y: (size.height - ts.height) / 2), withAttributes: attrs)
    img.unlockFocus()
    return img
}

final class Controller: NSObject, NSApplicationDelegate {
    private var window: NSWindow!, rows: NSStackView!, footer: NSTextField!
    private var watcher: BusWatcher?, napBlocker: NSObjectProtocol?
    private let localNet = LocalNet()
    private var seenOnlineAt: [String: Date] = [:]   // Tailscale's own LastSeen is unreliable after power loss
    private var machines: [Machine] = [], lastGood: Date?, lastNoted = ""
    // 20 s backstop (two silent reads turn a machine red); 20 s floor between bus-triggered reads
    // (the read's own ping rings the bus).
    private let heartbeatSeconds: TimeInterval = 20, minReadGap: TimeInterval = 20
    private var pending = false, reading = false, lastReadStarted = Date.distantPast
    func applicationDidFinishLaunching(_ n: Notification) {
        // Hold off App Nap (it stretched the timer to minutes) but still let the Mac sleep.
        napBlocker = ProcessInfo.processInfo.beginActivity(options: [.userInitiatedAllowingIdleSystemSleep],
                                                           reason: "watching whether the machines answer")
        localNet.onChange = { [weak self] in if let self = self { self.apply(self.machines) } }
        localNet.start()
        buildWindow()
        refresh()
        Timer.scheduledTimer(withTimeInterval: heartbeatSeconds, repeats: true) { [weak self] _ in self?.refresh() }
        watcher = BusWatcher { [weak self] in self?.scheduleRefresh() }
        watcher?.start()
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { false }
    /// The window comes up only when he clicks the Dock icon, never on launch.
    func applicationShouldHandleReopen(_ s: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if window == nil { buildWindow() }
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        refresh()
        return true
    }
    private func label(_ text: String, size: CGFloat) -> NSTextField {
        let l = NSTextField(labelWithString: text)
        l.font = size == 12 ? .monospacedSystemFont(ofSize: 12, weight: .regular) : .systemFont(ofSize: size)
        l.maximumNumberOfLines = 0
        return l
    }
    private func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 470, height: 340),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false      // the app outlives its window; a freed one crashed the next Dock click
        window.title = "Fleet Monitor"; window.center()
        rows = NSStackView(frame: NSRect(x: 18, y: 46, width: 434, height: 274))
        rows.orientation = .vertical; rows.alignment = .leading; rows.spacing = 14
        rows.addArrangedSubview(label("Loading…", size: 12))
        footer = label("", size: 10)
        footer.textColor = .secondaryLabelColor; footer.frame = NSRect(x: 18, y: 16, width: 434, height: 20)
        window.contentView?.addSubview(rows); window.contentView?.addSubview(footer)
    }
    /// Collapse a burst of bus notifications into one read.
    private func scheduleRefresh() {
        DispatchQueue.main.async {
            guard !self.pending else { return }
            self.pending = true
            let wait = max(1.5, self.minReadGap - Date().timeIntervalSince(self.lastReadStarted))
            DispatchQueue.main.asyncAfter(deadline: .now() + wait) { self.pending = false; self.refresh() }
        }
    }
    /// One read at a time, off the main thread: overlapping reads queue pings into their timeouts.
    private func refresh() {
        DispatchQueue.main.async {
            guard !self.reading else { return }
            self.reading = true; self.lastReadStarted = Date()
            DispatchQueue.global(qos: .utility).async {
                let result = Tailscale.status()
                DispatchQueue.main.async { self.reading = false; self.apply(result) }
            }
        }
    }
    private func apply(_ result: [Machine]?) {
        guard let list = result else {
            // A failed read is not news about the fleet: keep the last answer and say how old it is.
            if machines.isEmpty { NSApp.dockTile.badgeLabel = "?"; (rows.arrangedSubviews.first as? NSTextField)?.stringValue = "Connecting to Tailscale…" }
            footer.stringValue = lastGood.map { "Read failed — showing state from \(ago($0))" } ?? "Read failed — retrying…"
            DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self] in self?.refresh() }
            return
        }
        machines = list; lastGood = Date()
        if Tailscale.takeRecheck() { DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in self?.refresh() } }
        for m in list where m.online { seenOnlineAt[m.host] = Date() }
        let up = list.filter(\.online).count
        let state = "\(up)/\(list.count) " + list.map { "\($0.host):\($0.online ? "up" : $0.noReply ? "silent" : "off")" }
            .joined(separator: " ") + (localNet.isUp ? "" : " (no local network)")
        if state != lastNoted { lastNoted = state; note(state) }
        // Draw the tile ourselves: badgeLabel alone does not always repaint an app without an icon.
        NSApp.dockTile.badgeLabel = "\(up)/\(list.count)"
        NSApp.applicationIconImage = tileIcon(up: up, total: list.count)
        NSApp.dockTile.display()
        // Update rows in place when the count is unchanged, so an open tooltip survives.
        let specs = Specs.load()
        var labels = rows.arrangedSubviews.compactMap { $0 as? NSTextField }
        if labels.count != list.count {
            rows.arrangedSubviews.forEach { $0.removeFromSuperview() }
            labels = list.map { _ in label("", size: 12) }
            labels.forEach { rows.addArrangedSubview($0) }
        }
        for (l, m) in zip(labels, list) {
            let text = line(m, as: Specs.name(m.host, specs), seen: seenOnlineAt[m.host])
            if l.stringValue != text { l.stringValue = text }
            let tip = Specs.tooltip(m.host, specs)
            if l.toolTip != tip { l.toolTip = tip }
        }
        let f = DateFormatter(); f.dateFormat = "HH:mm:ss"
        footer.stringValue = "Updated \(f.string(from: Date())) · " + (localNet.isUp ? "pushed on change · replies verified"
            : "THIS MAC has no network — the machines below may well be up; nothing here is verified")
    }
    // No up/down popups on purpose: scheduled boots and shutdowns made them daily noise (the user, 2026-09-03: 很烦).
}

let app = NSApplication.shared, controller = Controller()
app.delegate = controller; app.setActivationPolicy(.regular)   // .regular: the Dock tile carries the badge
app.run()
