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
// 3. The window shows whether a machine answers, not whether Tailscale thinks
//    it is up. Those are different questions, and on 2026-09-03 they disagreed
//    for over four hours: the game PC had been shut down at 14:43 and the
//    status endpoint still said "Online" at 19:00, because a machine that loses
//    power never logs out and control had not yet timed it out. Every machine
//    the status claims is up is now asked directly before it is drawn green.
//
// Both endpoints are read straight off tailscaled's local HTTP API rather than
// through the bundled `Tailscale` CLI. That CLI is not a plain client: it tries
// to start the GUI app, and from a context that cannot do that it prints "The
// Tailscale GUI failed to start" and exits 0, which is indistinguishable from
// success unless the output is parsed. The monitor kept coming up empty at
// login for exactly that reason.
//
// Build:  swiftc -O main.swift -o FleetMonitor   （装进 ~/Applications/Fleet Monitor.app/Contents/MacOS/ 后 codesign -f -s - 整个 app）
// No linked libraries and no entitlements; it keeps working across Tailscale
// updates because the local API is the same surface the CLI itself uses.

import AppKit
import Foundation
import Network


// MARK: - Live link
//
// ToDesk 那种「掉线立刻变红」不是靠更勤地去问，是靠**一直连着**：连接断了本身就是信号。
// 用户 2026-09-08：「最坏 10 分钟我都不能接受，要跟 todesk 一样实时检测。」
//
// 所以对每台机器保持一条 TCP 连接（连它的 22 端口，Tailscale 内网可达）。
//   * 正常关机 → sshd 关闭，对端发 FIN/RST → **毫秒级**知道；
//   * 直接断电 → 没有 RST，靠 TCP keepalive：空闲 5 秒开始探，每 2 秒一次，3 次不应 → 约 11 秒；
//   * 机器回来 → 重连成功那一刻就绿。
// 两种情况都不需要定时轮询，和这个仓库「在线/离线不许靠轮询」的规矩一致。
//
// 原来的 disco ping 保留，但降级成「量延迟、看是不是直连」的细节来源，
// 不再承担「在不在」这个判断——它要 5 分钟一轮、两次不应才算数，最坏十分钟。
final class Link {
    private var conns: [String: NWConnection] = [:]
    private var up: [String: Bool] = [:]
    private let lock = NSLock()
    private let queue = DispatchQueue(label: "fleetmonitor.link")
    /// 状态一变就叫醒界面，不等任何定时器。
    var onChange: (() -> Void)?

    // 这条线只知道「连得上」和「连不上」，不知道是谁的错。本机 Wi-Fi 一抖、
    // tailscaled 一重启，每一台都连不上——而窗口会把它写成一句斩钉截铁的
    // 「no reply — powered off」，页脚还写着「replies verified」。那正是这个
    // 程序唯一存在理由的反面：他会以为 21:30 的队列死了，去断电或重开，
    // 而那一趟正在跑。所以要能说「不知道」。
    private let path = NWPathMonitor()
    private var pathOK = true
    private var lastUpAt = Date.distantPast

    /// 本机这一侧看起来是好的吗——不好的时候，全体「连不上」不是证据。
    var trustworthy: Bool {
        lock.lock(); defer { lock.unlock() }
        if !pathOK { return false }
        guard !up.isEmpty else { return true }
        // 全体同时掉线，几乎一定是这一端：真机器不会一起断电。
        // 刚才还有人在线，就更是。
        if up.values.allSatisfy({ !$0 }) && Date().timeIntervalSince(lastUpAt) < 60 {
            return false
        }
        return true
    }

    private var pathStarted = false

    func watchLocalPath() {
        lock.lock(); let already = pathStarted; pathStarted = true; lock.unlock()
        if already { return }          // refresh() 每轮都会叫它一次，只准真开一次
        path.pathUpdateHandler = { [weak self] p in
            guard let self = self else { return }
            self.lock.lock(); let changed = self.pathOK != (p.status == .satisfied)
            self.pathOK = (p.status == .satisfied); self.lock.unlock()
            if changed { DispatchQueue.main.async { self.onChange?() } }
        }
        path.start(queue: queue)
    }

    func track(_ ips: [String]) {
        lock.lock()
        let gone = Set(conns.keys).subtracting(ips)
        lock.unlock()
        for ip in gone { drop(ip) }
        for ip in ips where !ip.isEmpty { ensure(ip) }
    }

    func isUp(_ ip: String) -> Bool? {
        lock.lock(); defer { lock.unlock() }
        return up[ip]
    }

    private func drop(_ ip: String) {
        lock.lock(); let c = conns.removeValue(forKey: ip); up.removeValue(forKey: ip); lock.unlock()
        c?.cancel()
    }

    private func ensure(_ ip: String) {
        lock.lock(); let existing = conns[ip]; lock.unlock()
        if existing != nil { return }
        connect(ip)
    }

    private func connect(_ ip: String) {
        let tcp = NWProtocolTCP.Options()
        tcp.enableKeepalive = true
        tcp.keepaliveIdle = 5          // 空闲 5 秒就开始探
        tcp.keepaliveInterval = 2      // 每 2 秒一次
        tcp.keepaliveCount = 3         // 3 次不应就判死 → 断电约 11 秒被发现
        tcp.connectionTimeout = 6
        tcp.noDelay = true
        let params = NWParameters(tls: nil, tcp: tcp)
        guard let port = NWEndpoint.Port(rawValue: 22) else { return }
        let c = NWConnection(host: NWEndpoint.Host(ip), port: port, using: params)
        lock.lock(); conns[ip] = c; lock.unlock()

        c.stateUpdateHandler = { [weak self, weak c] state in
            guard let self = self else { return }
            switch state {
            case .ready:
                self.set(ip, true)
                // Hang up ourselves before sshd's LoginGraceTime (120 s) does it for
                // us. A connection that sits unauthenticated until sshd kills it
                // leaves `fatal: Timeout before authentication` in the machine's
                // sshd log every two minutes - the exact signature of a brute-force
                // scan, written by our own monitor, burying anything real. A client
                // close at 100 s is logged as an ordinary disconnect. The .cancelled
                // path then reconnects at once, so the green dot never blinks.
                self.queue.asyncAfter(deadline: .now() + 100) { [weak self, weak c] in
                    guard let self = self, let c = c else { return }
                    self.lock.lock(); let mine = self.conns[ip] === c; self.lock.unlock()
                    if mine { c.cancel() }
                }
                // **必须挂一个读**，否则对端发来的 FIN 只是躺在缓冲区里，
                // 状态机根本不动。2026-09-08 本地实测：只连不读，对端关闭之后
                // 隔了 60 秒才发现；挂上读之后是 19 毫秒。
                // 「一直连着」不等于「一直听着」，这一步是实时的全部关键。
                self.listen(ip, c)
            case .failed, .cancelled:
                // **断了不等于关机。** sshd 的 LoginGraceTime 会在 120 秒后主动踢掉
                // 没认证的连接，那和真关机一样是一个干净的 FIN——直接判离线的话，
                // 每两分钟闪一次红，这个红点就再也没人信了。
                // 所以断了立刻重连，**重连也失败才算离线**：
                //   * sshd 踢人 → 马上又连上 → 一直绿，用户什么都看不到；
                //   * 真关机   → 重连连不上 → 一两秒内变红。
                self.lock.lock(); let mine = self.conns[ip] === c; self.lock.unlock()
                if mine {
                    self.lock.lock(); self.conns[ip] = nil; self.lock.unlock()
                    self.queue.async { [weak self] in self?.connect(ip) }
                }
            case .waiting:
                // 连不上（机器关着、路由不通）——这才是「不在」。
                self.set(ip, false)
                // 一直重试，机器回来那一刻就绿。3 秒是重连节奏，不是判据。
                self.queue.asyncAfter(deadline: .now() + 3) { [weak self] in
                    guard let self = self else { return }
                    self.lock.lock(); let mine = self.conns[ip] === c; self.lock.unlock()
                    if mine {
                        c?.cancel()
                        self.lock.lock(); self.conns[ip] = nil; self.lock.unlock()
                        self.connect(ip)
                    }
                }
            default:
                break
            }
        }
        c.start(queue: queue)
    }

    /// 挂一个读，等对端说话或关闭。收到任何东西都不重要，重要的是**它还在**。
    private func listen(_ ip: String, _ c: NWConnection?) {
        guard let c = c else { return }
        c.receive(minimumIncompleteLength: 1, maximumLength: 4096) { [weak self, weak c] _, _, done, err in
            guard let self = self else { return }
            if done || err != nil {
                // 对端关了。可能是关机，也可能是 sshd 的 LoginGraceTime 踢人——
                // 分不出来，所以不在这里下结论，交给 .failed 那条路去重连再判。
                self.lock.lock(); let mine = self.conns[ip] === c; self.lock.unlock()
                if mine {
                    c?.cancel()          // 触发 .cancelled → 立刻重连 → 连不上才判离线
                }
                return
            }
            self.listen(ip, c)
        }
    }

    private func set(_ ip: String, _ value: Bool) {
        lock.lock()
        let changed = up[ip] != value
        up[ip] = value
        if value { lastUpAt = Date() }
        lock.unlock()
        if changed { DispatchQueue.main.async { self.onChange?() } }
    }
}

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
    /// What the last ping measured, when there was one.
    let probe: Probe?
    /// Tailscale still lists the machine as up, but it did not answer a ping.
    /// Rendered differently from a machine control has already given up on:
    /// "last seen never" is what that peer's timestamps say, and it reads as a
    /// bug rather than as a machine somebody switched off.
    let noReply: Bool

    /// The same machine, marked as not answering.
    func silent() -> Machine {
        Machine(host: host, ip: ip, os: os, online: false, lastSeen: lastSeen,
                isSelf: isSelf, directAddr: directAddr, relay: relay,
                active: active, probe: nil, noReply: true)
    }

    /// The same machine, carrying what the ping measured.
    func answering(_ p: Probe) -> Machine {
        Machine(host: host, ip: ip, os: os, online: true, lastSeen: lastSeen,
                isSelf: isSelf, directAddr: directAddr, relay: relay,
                active: active, probe: p, noReply: false)
    }
}

/// One round trip to a machine.
struct Probe {
    let answered: Bool
    let ms: Int
    /// Whether the reply came over a direct path rather than a relay.
    let direct: Bool
    static let none = Probe(answered: false, ms: 0, direct: false)
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

    /// One session with **no cache**. 2026-09-07: the game PC had been off for
    /// an hour and the window still said "114ms". URLSession had cached the
    /// last ping reply (tailscaled sends no Cache-Control) and answered every
    /// later probe from disk - the same "114ms" for ten minutes straight.
    /// A monitor whose one job is "is it on" cannot let the OS answer from
    /// memory, so this session has no cache at all and every request says so.
    static let session: URLSession = {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.urlCache = nil
        cfg.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        return URLSession(configuration: cfg)
    }()

    static func request(_ path: String) -> URLRequest? {
        guard let e = endpoint(),
              let url = URL(string: "http://127.0.0.1:\(e.port)/localapi/v0/\(path)")
        else { return nil }
        var r = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalAndRemoteCacheData)
        // Username is empty; the proof file is the password.
        let auth = Data(":\(e.token)".utf8).base64EncodedString()
        r.setValue("Basic \(auth)", forHTTPHeaderField: "Authorization")
        return r
    }

    /// Whether the machine answers right now.
    ///
    /// `Online` in tailscaled's status is the control plane's opinion, not
    /// reachability. A machine that loses power without logging out keeps that
    /// flag set until control times it out - on 2026-09-03 the game PC still
    /// read "online" four hours after it had been shut down, while neither ssh
    /// nor ping reached it. A monitor whose entire job is answering "is it on"
    /// cannot forward somebody else's stale opinion, so every machine the
    /// status claims is up gets asked directly.
    ///
    /// A disco ping rather than ICMP: it is answered by tailscaled itself, so a
    /// host firewall that drops pings - which Windows does by default - cannot
    /// make a running machine look dead. A machine that is off never answers,
    /// and the request simply hangs until the timeout below.
    /// Last answer per machine and when it was measured. See `status()`.
    private static var cache: [String: (probe: Probe, at: Date)] = [:]
    private static let cacheLock = NSLock()
    private static let probeReuseSeconds: TimeInterval = 30
    /// Consecutive silent reads per machine, for the hysteresis in `status()`.
    private static var misses: [String: Int] = [:]
    /// Set when a machine went silent once: the second read should come in
    /// seconds, not at the next five-minute heartbeat. Before this a machine
    /// that was switched off stayed green for up to ten minutes.
    static var recheckSoon = false

    static func probe(_ ip: String, timeout: TimeInterval = 4) -> Probe {
        guard !ip.isEmpty, var req = request("ping?ip=\(ip)&type=disco") else { return .none }
        req.httpMethod = "POST"
        req.timeoutInterval = timeout
        let lock = NSLock()
        var result = Probe.none
        let done = DispatchSemaphore(value: 0)
        let task = session.dataTask(with: req) { d, _, _ in
            defer { done.signal() }
            guard let d = d,
                  let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any]
            else { return }
            // A reply that carries an error is not a reply from the machine:
            // pinging our own address answers instantly with "is local
            // Tailscale IP", which must not count as the peer being up.
            let err = (o["Err"] as? String) ?? ""
            let latency = (o["LatencySeconds"] as? Double) ?? 0
            guard err.isEmpty, latency > 0 else { return }
            let endpoint = (o["Endpoint"] as? String) ?? ""
            lock.lock()
            result = Probe(answered: true, ms: Int((latency * 1000).rounded()),
                           direct: !endpoint.isEmpty)
            lock.unlock()
        }
        task.resume()
        _ = done.wait(timeout: .now() + timeout + 2)
        task.cancel()
        lock.lock(); defer { lock.unlock() }
        return result
    }

    static func status() -> [Machine]? {
        guard let req = request("status") else { note("no local API endpoint"); return nil }

        // Synchronous by design: the caller is already on a background queue,
        // and a status read that has not finished is not a status.
        var payload: Data?
        let done = DispatchSemaphore(value: 0)
        session.dataTask(with: req) { d, _, err in
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
        // Ask every machine the status claims is up whether it is actually
        // there. See `reachable` for why the claim alone is not good enough.
        let group = DispatchGroup()
        let queue = DispatchQueue(label: "fleetmonitor.probe", attributes: .concurrent)
        let lock = NSLock()
        var answers: [String: Probe] = [:]
        for m in out where !m.isSelf && m.online {
            // A fresh answer is reused for a while. The ping is itself traffic,
            // traffic rings the bus doorbell, and the doorbell used to trigger
            // another ping: a loop that pinged every couple of seconds. Under
            // that load pings queued behind each other, ran into their timeout,
            // and a running machine flickered offline/online - on 2026-09-03 it
            // did so a dozen times in a row while the game PC was booting.
            if let c = cache[m.ip], Date().timeIntervalSince(c.at) < probeReuseSeconds {
                answers[m.ip] = c.probe
                continue
            }
            group.enter()
            queue.async {
                // Two tries, so one dropped packet cannot evict a machine that
                // is running. Only a machine that is genuinely off pays for the
                // second attempt.
                var p = probe(m.ip)
                if !p.answered { p = probe(m.ip) }
                lock.lock(); answers[m.ip] = p; lock.unlock()
                group.leave()
            }
        }
        _ = group.wait(timeout: .now() + 20)
        cacheLock.lock()
        for (ip, p) in answers { cache[ip] = (p, Date()) }
        cacheLock.unlock()
        out = out.map { m in
            guard let p = answers[m.ip] else { return m }
            if p.answered {
                misses[m.ip] = 0
                return m.answering(p)
            }
            // Hysteresis: one silent read is not a verdict. A machine that is
            // booting answers on the second or third read; one that is off
            // never does, and two silent reads in a row is soon enough.
            misses[m.ip, default: 0] += 1
            if misses[m.ip]! < 2 { recheckSoon = true }
            return misses[m.ip]! >= 2 ? m.silent() : m
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
            active: (d["Active"] as? Bool) ?? false,
            probe: nil,
            noReply: false
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

/// How to describe a machine Tailscale itself reports as down.
///
/// `seen` is when this monitor itself last saw the machine up, used only when
/// Tailscale's own timestamp is missing. It usually is: an offline peer often
/// comes back with a zero `LastSeen`, and rendering that read "last seen
/// never" on a machine that had been up all evening - a line that looks like a
/// bug in the monitor rather than a machine somebody switched off.
func offlineNote(_ m: Machine, seen: Date?) -> String {
    let stamp = m.lastSeen.flatMap { $0.timeIntervalSince1970 > 0 ? $0 : nil } ?? seen
    return stamp == nil ? "  ·  offline" : "  ·  offline, last seen \(ago(stamp))"
}

func line(_ m: Machine, as name: String? = nil, seen: Date? = nil) -> String {
    let dot = m.online ? "🟢" : "🔴"
    var s = "\(dot) \(name ?? m.host)"
    if m.isSelf { s += "  (this Mac)" }
    s += "\n     \(m.ip)  \(m.os)"
    if !m.isSelf {
        // An idle peer sits on the relay by design and switches to a direct
        // path as soon as traffic starts, so a bare "relay" here reads as a
        // fault when nothing is wrong. Say which it is.
        // The path comes from the ping itself, not from `Active`: the ping is
        // traffic, so every machine we verify reads as active from then on and
        // the window would permanently say "relay" - the exact reading the
        // "idle (direct on use)" wording existed to prevent.
        if m.online, let p = m.probe {
            s += (p.direct ? "  ·  direct" : "  ·  relay \(m.relay)") + "  ·  \(p.ms)ms"
        } else {
            s += m.online
                ? (m.directAddr != nil ? "  ·  direct" : "  ·  idle (direct on use)")
                : m.noReply ? "  ·  no reply — powered off"
                            : offlineNote(m, seen: seen)
        }
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
    /// When this monitor last saw each machine up. Tailscale's own timestamp is
    /// unreliable for a machine that lost power, so keep our own.
    private var seenOnlineAt: [String: Date] = [:]
    private var machines: [Machine] = []
    private var lastGood: Date?
    /// 上一轮里，那条一直连着的线说的话算不算数（本机没网时不算）。
    private var linkTrusted = true
    /// Backstop only - the bus subscription is what actually drives updates.
    // 60 秒，不是 300。2026-09-08：机器关掉 17 分钟之后 Dock 上还是绿的 2/2。
    // 判离线要连续两次探测失败，300 秒一轮就意味着**最坏十分钟才变色**——
    // 而这个程序存在的唯一理由就是「一眼看出那台机器在不在」。
    // 探测本身只是两个 ping，便宜得很，没有理由省这一下。
    private let heartbeatSeconds: TimeInterval = 60

    // 不许被 App Nap 掐住。没有这一句时，系统会把后台应用的定时器拖到几十秒甚至
    // 几分钟才触发一次——上面那个 60 秒就成了摆设，而屏幕上那个绿点还是绿的。
    // 这正是 2026-09-08 那次的真因：逻辑是对的，定时器根本没按时跑。
    private var napBlocker: NSObjectProtocol?

    /// 一直连着的那条线。它说了算，见 Link 的说明。
    private let link = Link()

    func applicationDidFinishLaunching(_ note: Notification) {
        // Only App Nap has to be held off. `.userInitiated` on its own already
        // implies "no idle system sleep", so with it (plus the explicit flag that
        // was here) this Mac never slept again: `pmset -g assertions` showed
        // PreventUserIdleSystemSleep held by FleetMonitor for hours. The
        // variant that allows sleep is the one meant for exactly this.
        napBlocker = ProcessInfo.processInfo.beginActivity(
            options: [.userInitiatedAllowingIdleSystemSleep],
            reason: "watching whether the machines answer")
        // 连接状态一变就重画，不等任何定时器——这就是「实时」的那部分。
        link.onChange = { [weak self] in self?.apply(self?.machines) }
        buildWindow()
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
    private var reading = false
    private var lastReadStarted = Date.distantPast
    /// Floor between two bus-triggered reads. The bus fires on traffic, and
    /// the read's own ping is traffic, so without a floor the two chase each
    /// other for as long as a peer is up.
    private let minReadGap: TimeInterval = 20

    /// Collapse a burst of bus notifications into one status read.
    private func scheduleRefresh() {
        DispatchQueue.main.async {
            guard !self.pending else { return }
            self.pending = true
            let wait = max(1.5, self.minReadGap - Date().timeIntervalSince(self.lastReadStarted))
            DispatchQueue.main.asyncAfter(deadline: .now() + wait) {
                self.pending = false
                self.refresh()
            }
        }
    }

    @objc private func refresh() {
        // Off the main thread: the CLI can block for seconds when the network
        // is unhappy, and a frozen UI is worse than a stale count.
        // One read at a time: a read that overlaps another queues its pings
        // behind the first one's, and queued pings time out and read as a
        // machine that has gone silent.
        DispatchQueue.main.async {
            guard !self.reading else { return }
            self.reading = true
            self.lastReadStarted = Date()
            DispatchQueue.global(qos: .utility).async {
                let result = Tailscale.status()
                DispatchQueue.main.async {
                    self.reading = false
                    self.apply(result)
                }
            }
        }
    }

    private func apply(_ result: [Machine]?) {
        guard var list = result else {
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
        // 让 Link 盯住除本机以外的每一台。
        link.watchLocalPath()
        link.track(list.filter { !$0.isSelf }.map(\.ip))
        // **在不在，以那条一直连着的线为准。** Tailscale 的 online 只当参考：
        // 它对一台已经断电的机器能报 active 好几个小时（2026-09-03 实测四小时），
        // 而那条 TCP 连接在关机时毫秒级就断了。
        // 本机这一侧不对劲的时候，那条线说的「连不上」不是证据，这一步整个跳过：
        // 宁可用 Tailscale 那份旧一点的答案，也不要一个自信的错答案。
        let trust = self.link.trustworthy
        if trust {
            list = list.map { m in
                guard !m.isSelf, let alive = self.link.isUp(m.ip) else { return m }
                if alive { return m.online ? m : m.answering(Probe(answered: true, ms: 0, direct: false)) }
                return m.silent()
            }
        }
        self.linkTrusted = trust
        machines = list
        lastGood = Date()
        if Tailscale.recheckSoon {
            Tailscale.recheckSoon = false
            DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self] in self?.refresh() }
        }
        for m in list where m.online { seenOnlineAt[m.host] = Date() }
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
                let text = line(m, as: Specs.displayName(for: m.host, specs),
                                seen: seenOnlineAt[m.host])
                if label.stringValue != text { label.stringValue = text }
                let tip = Specs.tooltip(for: m.host, specs)
                if label.toolTip != tip { label.toolTip = tip }
            }
        } else {
            rows.arrangedSubviews.forEach { $0.removeFromSuperview() }
            for m in list {
                let label = NSTextField(labelWithString: line(
                    m, as: Specs.displayName(for: m.host, specs), seen: seenOnlineAt[m.host]))
                label.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
                label.maximumNumberOfLines = 0
                label.toolTip = Specs.tooltip(for: m.host, specs)
                rows.addArrangedSubview(label)
            }
        }
        let f = DateFormatter(); f.dateFormat = "HH:mm:ss"
        footer.stringValue = linkTrusted
            ? "Updated \(f.string(from: Date())) · pushed on change · replies verified"
            : "Updated \(f.string(from: Date())) · THIS MAC cannot reach the tailnet — "
              + "the machines below may well be up; nothing here is verified"
    }

    /// No up/down popups, on purpose.
    ///
    /// The fleet's normal day is a scheduled boot and a scheduled shutdown, so
    /// every single day this notified twice about something nobody needed
    /// telling - and at boot it fired repeatedly, because the machine is
    /// briefly reachable-but-not-answering while tailscaled starts. The user's
    /// word for it on 2026-09-03 was "很烦".
    ///
    /// The state is already on screen without one: the Dock tile is coloured
    /// and carries the count whenever the Dock is. And a machine being off is
    /// not the thing worth interrupting for - a queue that failed is, and that
    /// already arrives through the relay's own channel rather than a second
    /// notification stream competing with it.
}

let app = NSApplication.shared
let controller = Controller()
app.delegate = controller
app.setActivationPolicy(.regular)   // Dock tile carries the badge
app.run()
