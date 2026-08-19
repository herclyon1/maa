// 优盘体检 —— 扫描维护U盘上的可更新工具，对比官方最新版本与发布时间。
// 只显示「可更新」的工具；ToDesk / 向日葵 为特殊关注项（装后自升级，安装器新旧不影响使用）。
// 只读不写：本程序不下载不替换，红了找 Claude 更新。
import SwiftUI

// MARK: - 数据模型

enum Checker {
    case github(repo: String)                                    // GitHub releases/latest
    case page(url: String, vRe: String, dRe: String?, pickMax: Bool)
    case redirectName(url: String, vRe: String, dRe: String?)    // 302 Location 文件名里带版本/日期
    case lastMod(url: String)                                    // 无版本号源：拿 Last-Modified 当日期
    case officeAPI
    case chromeDash
    case firefoxJSON
    case anydeskLog
    case todesk                                                  // Nuxt payload 里的 version/release_date 对
    case sunlogin                                                // 扫全部 JS bundle 找 SunloginClient_x.y.z
}

struct ToolSpec: Identifiable {
    let id: String
    let name: String
    let group: String
    var special = false          // ToDesk/向日葵：特殊标注
    var usbRel: String?          // 盘内相对路径（用于读文件日期）
    let localVer: String
    var localDate: String?       // 已知的本地版本发布日；nil 则显示盘内文件日期
    let homepage: String
    let checker: Checker
}

enum Status { case fresh, outdated, unknown, checking }

struct CheckResult {
    var latestVer: String?
    var latestDate: String?
    var status: Status = .checking
    var note: String?
}

// MARK: - 清单（2026-08-19 全盘更新后的基线）

let TOOLS: [ToolSpec] = [
    // —— 特殊关注 ——
    ToolSpec(id: "todesk", name: "ToDesk", group: "特殊关注（装后自升级）", special: true,
             usbRel: "其他的专业软件/远程控制类/ToDesk_4.7.6.3（备用远控）.exe",
             localVer: "4.7.6.3", localDate: nil,
             homepage: "https://www.todesk.com/download.html", checker: .todesk),
    ToolSpec(id: "sunlogin", name: "向日葵", group: "特殊关注（装后自升级）", special: true,
             usbRel: "其他的专业软件/远程控制类/向日葵_15.8.2（广泛使用）.exe",
             localVer: "15.8.2", localDate: nil,
             homepage: "https://sunlogin.oray.com/download", checker: .sunlogin),
    // —— 顶层 ——
    ToolSpec(id: "huorong", name: "火绒安全", group: "常用",
             usbRel: "火绒（推荐杀毒软件）.exe", localVer: "6.0.11.2", localDate: "2026-08-18",
             homepage: "https://www.huorong.cn/person",
             checker: .redirectName(url: "https://www.huorong.cn/product/downloadHr60.php?pro=hr60",
                                    vRe: "sysdiag-all-x86-([0-9.]+)-", dRe: "-([0-9]{4}\\.[0-9]{2}\\.[0-9]{2})")),
    ToolSpec(id: "7zip", name: "7-Zip", group: "常用",
             usbRel: "解压软件7-Zip 26.02（官方版）.exe", localVer: "26.02", localDate: nil,
             homepage: "https://www.7-zip.org", checker: .github(repo: "ip7z/7zip")),
    ToolSpec(id: "chrome", name: "谷歌浏览器", group: "常用",
             usbRel: "谷歌浏览器（官方离线版）.exe", localVer: "2026-08-19 入盘·当日最新", localDate: "2026-08-19",
             homepage: "https://www.google.com/chrome/", checker: .chromeDash),
    ToolSpec(id: "firefox", name: "火狐浏览器", group: "常用",
             usbRel: "火狐浏览器国际版（无广告）.exe", localVer: "2026-08-19 入盘·当日最新", localDate: "2026-08-19",
             homepage: "https://www.mozilla.org/firefox/", checker: .firefoxJSON),
    ToolSpec(id: "360cse", name: "360极速浏览器X", group: "常用",
             usbRel: "360极速浏览器X（国内使用）.exe", localVer: "23.0.1253.0", localDate: "2026-08-19",
             homepage: "https://browser.360.cn/ee/",
             checker: .page(url: "https://browser.360.cn/ee/", vRe: "360cse_([0-9.]+)\\.exe", dRe: nil, pickMax: true)),
    ToolSpec(id: "sogou", name: "搜狗输入法", group: "常用",
             usbRel: "搜狗输入法（官方版16.7）.exe", localVer: "16.7b", localDate: "2026-08-19",
             homepage: "https://shurufa.sogou.com/",
             checker: .page(url: "https://shurufa.sogou.com/", vRe: "pinyin_guanwang_([0-9.]+[a-z]?)\\.exe", dRe: nil, pickMax: false)),
    ToolSpec(id: "office", name: "Office 离线包", group: "常用",
             usbRel: "Office离线安装包（免联网安装Word Excel PPT）/setup.exe",
             localVer: "16.0.20326.20100", localDate: "2026-08-19",
             homepage: "https://www.office.com", checker: .officeAPI),
    // —— 小软件 ——
    ToolSpec(id: "everything", name: "Everything", group: "小软件",
             usbRel: "其他小软件/Everything-1.4.1.1032（文件搜索）.exe", localVer: "1.4.1.1032", localDate: nil,
             homepage: "https://www.voidtools.com",
             checker: .page(url: "https://www.voidtools.com/downloads/", vRe: "Everything-([0-9.]+)\\.x64-Setup\\.exe", dRe: nil, pickMax: false)),
    ToolSpec(id: "npp", name: "Notepad++", group: "小软件",
             usbRel: "其他小软件/Notepad++（文本类处理）.exe", localVer: "8.9.7", localDate: nil,
             homepage: "https://notepad-plus-plus.org", checker: .github(repo: "notepad-plus-plus/notepad-plus-plus")),
    ToolSpec(id: "potplayer", name: "PotPlayer", group: "小软件",
             usbRel: "其他小软件/PotPlayer官方最新版（专业视频播放器）.exe",
             localVer: "2026-08-19 入盘·当日最新", localDate: "2026-08-19",
             homepage: "https://potplayer.daum.net",
             checker: .lastMod(url: "https://t1.daumcdn.net/potplayer/PotPlayer/Version/Latest/PotPlayerSetup64.exe")),
    ToolSpec(id: "idm", name: "IDM", group: "小软件",
             usbRel: "其他小软件/IDM 6.43官方版（多线程下载·付费软件30天试用）.exe", localVer: "6.43 Build 9", localDate: "2026-08-19",
             homepage: "https://www.internetdownloadmanager.com",
             checker: .page(url: "https://www.internetdownloadmanager.com/download.html",
                            vRe: "idman([0-9]+)build([0-9]+)\\.exe", dRe: nil, pickMax: false)),
    ToolSpec(id: "memreduct", name: "Mem Reduct", group: "小软件",
             usbRel: "其他小软件/Mem Reduct（内存定时清理）.zip", localVer: "盘内旧版(zip)", localDate: nil,
             homepage: "https://github.com/henrypp/memreduct", checker: .github(repo: "henrypp/memreduct")),
    ToolSpec(id: "twinkle", name: "Twinkle Tray", group: "小软件",
             usbRel: "其他小软件/Twinkle.Tray.v1.16.6（显示器亮度调节）.exe", localVer: "1.16.6", localDate: nil,
             homepage: "https://twinkletray.com", checker: .github(repo: "xanderfrangos/twinkle-tray")),
    ToolSpec(id: "honeyview", name: "HoneyView", group: "小软件",
             usbRel: "其他小软件/HoneyView（图片查看器）.exe", localVer: "盘内旧版", localDate: nil,
             homepage: "https://www.bandisoft.com/honeyview/",
             checker: .page(url: "https://www.bandisoft.com/honeyview/", vRe: "HoneyView ?v?([0-9.]+)", dRe: nil, pickMax: false)),
    ToolSpec(id: "rammap", name: "RamMap", group: "小软件",
             usbRel: "其他小软件/RamMap（清理内存）.exe", localVer: "盘内旧版", localDate: nil,
             homepage: "https://learn.microsoft.com/sysinternals/downloads/rammap",
             checker: .page(url: "https://learn.microsoft.com/en-us/sysinternals/downloads/rammap",
                            vRe: "RAMMap v([0-9.]+)", dRe: nil, pickMax: false)),
    // —— 专业软件 ——
    ToolSpec(id: "cpuz", name: "CPU-Z", group: "专业软件",
             usbRel: "其他的专业软件/CPU-Z（CPU信息）.exe", localVer: "2.21", localDate: nil,
             homepage: "https://www.cpuid.com/softwares/cpu-z.html",
             checker: .page(url: "https://www.cpuid.com/softwares/cpu-z.html", vRe: "cpu-z_([0-9.]+)-en\\.exe", dRe: nil, pickMax: true)),
    ToolSpec(id: "gpuz", name: "GPU-Z", group: "专业软件",
             usbRel: "其他的专业软件/GPU-Z（显卡信息).exe", localVer: "2.70.0", localDate: nil,
             homepage: "https://www.techpowerup.com/download/techpowerup-gpu-z/",
             checker: .page(url: "https://www.techpowerup.com/download/techpowerup-gpu-z/", vRe: "v(2\\.[0-9.]+)", dRe: nil, pickMax: true)),
    ToolSpec(id: "clash", name: "Clash Verge", group: "专业软件",
             usbRel: "其他的专业软件/Clash.Verge_2.5.2（翻墙工具）.exe", localVer: "2.5.2", localDate: nil,
             homepage: "https://github.com/clash-verge-rev/clash-verge-rev", checker: .github(repo: "clash-verge-rev/clash-verge-rev")),
    ToolSpec(id: "diskgenius", name: "DiskGenius", group: "专业软件",
             usbRel: "其他的专业软件/DiskGenius专业版6.2 x64（分区工具·解压后用）.zip", localVer: "6.2.0.1829", localDate: "2026-05-20",
             homepage: "https://www.diskgenius.cn",
             checker: .page(url: "https://www.diskgenius.cn/download.php", vRe: "DG([0-9]{7})_x64\\.zip", dRe: nil, pickMax: false)),
    ToolSpec(id: "geek", name: "Geek Uninstaller", group: "专业软件",
             usbRel: "其他的专业软件/强力卸载软件（Geek官方版）.exe", localVer: "1.5.3.170", localDate: "2025-11-24",
             homepage: "https://geekuninstaller.com",
             checker: .page(url: "https://geekuninstaller.com/download", vRe: "([0-9]\\.[0-9]\\.[0-9]+)", dRe: nil, pickMax: false)),
    ToolSpec(id: "revo", name: "Revo Uninstaller", group: "专业软件",
             usbRel: "其他的专业软件/软件卸载Revo_Uninstaller（官方免费版）.exe", localVer: "2026-08-19 入盘·当日最新", localDate: "2026-08-19",
             homepage: "https://www.revouninstaller.com",
             checker: .lastMod(url: "https://download.revouninstaller.com/download/revosetup.exe")),
    ToolSpec(id: "anydesk", name: "AnyDesk", group: "专业软件",
             usbRel: "其他的专业软件/远程控制类/AnyDesk（内网远程）.exe", localVer: "2026-08-19 入盘·当日最新", localDate: "2026-08-19",
             homepage: "https://anydesk.com", checker: .anydeskLog),
    ToolSpec(id: "tbtool", name: "图吧工具箱", group: "专业软件",
             usbRel: "其他的专业软件/【工具大全】图吧工具箱2026年08月.exe", localVer: "2026-08", localDate: "2026-08-19",
             homepage: "https://www.tbtool.cn",
             checker: .page(url: "https://www.tbtool.cn/", vRe: "(20[2-9][0-9]0?[0-9])", dRe: nil, pickMax: true)),
    // —— 驱动 & 运行库 ——
    ToolSpec(id: "360drv", name: "360驱动大师·网卡版", group: "驱动与运行库",
             usbRel: "各种驱动工具/360驱动大师·网卡版（小白推荐）.exe", localVer: "2026-08-19 入盘·当日最新", localDate: "2026-08-19",
             homepage: "https://dd.360.cn",
             checker: .lastMod(url: "https://dl.360safe.com/drvmgr/360DrvMgrInstaller_net.exe")),
    ToolSpec(id: "drvceo", name: "驱动总裁·离线网卡版", group: "驱动与运行库",
             usbRel: "各种驱动工具/驱动总裁·离线网卡版（专业驱动）.exe", localVer: "盘内2025-02版", localDate: nil,
             homepage: "https://www.drvceo.com",
             checker: .page(url: "https://www.drvceo.com/", vRe: "([0-9]+\\.[0-9]+\\.[0-9]+\\.?[0-9]*)", dRe: nil, pickMax: false)),
    ToolSpec(id: "vcredist", name: "VisualCppRedist 运行库", group: "驱动与运行库",
             usbRel: "插件或补丁（软件打不开试试打这个）/VisualCppRedist(运行库合集) v0.105.exe", localVer: "0.105.0", localDate: nil,
             homepage: "https://github.com/abbodi1406/vcredist", checker: .github(repo: "abbodi1406/vcredist")),
    ToolSpec(id: "java21", name: "Java 21", group: "驱动与运行库",
             usbRel: "插件或补丁（软件打不开试试打这个）/Java21 64位（Oracle官方最新）.exe", localVer: "2026-08-19 入盘·当日最新", localDate: "2026-08-19",
             homepage: "https://www.oracle.com/java/technologies/downloads/",
             checker: .lastMod(url: "https://download.oracle.com/java/21/latest/jdk-21_windows-x64_bin.exe")),
]

// MARK: - 网络与解析

let UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

func fetch(_ url: String, method: String = "GET", follow: Bool = true) async -> (String?, [String: String]) {
    guard let u = URL(string: url) else { return (nil, [:]) }
    var rq = URLRequest(url: u, timeoutInterval: 20)
    rq.httpMethod = method
    rq.setValue(UA, forHTTPHeaderField: "User-Agent")
    let cfg = URLSessionConfiguration.ephemeral
    let sess = follow ? URLSession(configuration: cfg)
                      : URLSession(configuration: cfg, delegate: NoRedirect(), delegateQueue: nil)
    do {
        let (data, resp) = try await sess.data(for: rq)
        var headers: [String: String] = [:]
        if let h = resp as? HTTPURLResponse {
            for (k, v) in h.allHeaderFields { headers[String(describing: k).lowercased()] = String(describing: v) }
        }
        return (String(data: data, encoding: .utf8) ?? "", headers)
    } catch { return (nil, [:]) }
}

final class NoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ s: URLSession, task: URLSessionTask, willPerformHTTPRedirection r: HTTPURLResponse,
                    newRequest req: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

func matches(_ text: String, _ pattern: String) -> [[String]] {
    guard let re = try? NSRegularExpression(pattern: pattern) else { return [] }
    let ns = text as NSString
    return re.matches(in: text, range: NSRange(location: 0, length: ns.length)).map { m in
        (0..<m.numberOfRanges).map { m.range(at: $0).location == NSNotFound ? "" : ns.substring(with: m.range(at: $0)) }
    }
}

func verKey(_ v: String) -> [Int] {
    v.split(whereSeparator: { !$0.isNumber }).compactMap { Int($0) }
}

func newer(_ a: String, _ b: String) -> Bool {  // a > b
    let x = verKey(a), y = verKey(b)
    for i in 0..<max(x.count, y.count) {
        let p = i < x.count ? x[i] : 0, q = i < y.count ? y[i] : 0
        if p != q { return p > q }
    }
    return false
}

func normDate(_ s: String) -> String {
    var t = s.replacingOccurrences(of: ".", with: "-").replacingOccurrences(of: "/", with: "-")
    if t.count > 10 { t = String(t.prefix(10)) }
    return t
}

func runChecker(_ spec: ToolSpec) async -> CheckResult {
    var r = CheckResult()
    switch spec.checker {
    case .github(let repo):
        let (body, _) = await fetch("https://api.github.com/repos/\(repo)/releases/latest")
        guard let body, let data = body.data(using: .utf8),
              let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { break }
        var tag = (j["tag_name"] as? String) ?? ""
        if tag.hasPrefix("v") { tag.removeFirst() }
        r.latestVer = tag
        if let d = j["published_at"] as? String { r.latestDate = String(d.prefix(10)) }
    case .page(let url, let vRe, let dRe, let pickMax):
        let (body, _) = await fetch(url)
        guard let body else { break }
        let ms = matches(body, vRe)
        if !ms.isEmpty {
            if spec.id == "idm", ms[0].count >= 3 {   // idman643build9 → 6.43 Build 9
                let raw = ms[0][1]
                let major = String(raw.prefix(1)), minor = String(raw.dropFirst())
                r.latestVer = "\(major).\(minor) Build \(ms[0][2])"
            } else if spec.id == "diskgenius", ms[0].count >= 2 {  // DG6201829 → 6.2.0.1829
                let d = ms[0][1]
                r.latestVer = "\(d.prefix(1)).\(d.dropFirst(1).prefix(1)).\(d.dropFirst(2).prefix(1)).\(d.suffix(4))"
            } else {
                var vs = ms.map { $0.count > 1 ? $0[1] : $0[0] }
                if pickMax { vs.sort { newer($0, $1) } }
                r.latestVer = vs.first
            }
            if let dRe, let dm = matches(body, dRe).first, dm.count > 1 { r.latestDate = normDate(dm[1]) }
        }
    case .redirectName(let url, let vRe, let dRe):
        let (_, headers) = await fetch(url, method: "HEAD", follow: false)
        let loc = headers["location"] ?? ""
        if let m = matches(loc, vRe).first, m.count > 1 { r.latestVer = m[1] }
        if let dRe, let m = matches(loc, dRe).first, m.count > 1 { r.latestDate = normDate(m[1]) }
    case .lastMod(let url):
        let (_, headers) = await fetch(url, method: "HEAD")
        if let lm = headers["last-modified"] {
            let f = DateFormatter(); f.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"; f.locale = Locale(identifier: "en_US_POSIX")
            if let d = f.date(from: lm) {
                let o = DateFormatter(); o.dateFormat = "yyyy-MM-dd"
                r.latestDate = o.string(from: d)
                r.latestVer = "官方最新（源无版本号）"
            }
        }
    case .officeAPI:
        let (body, _) = await fetch("https://clients.config.office.net/releases/v1.0/OfficeReleases")
        guard let body, let data = body.data(using: .utf8),
              let arr = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]], let first = arr.first else { break }
        r.latestVer = first["latestVersion"] as? String
        if let ovs = first["officeVersions"] as? [[String: Any]], let d = ovs.first?["availabilityDate"] as? String {
            r.latestDate = String(d.prefix(10))
        }
    case .chromeDash:
        let (body, _) = await fetch("https://chromiumdash.appspot.com/fetch_releases?channel=Stable&platform=Windows&num=1")
        guard let body, let data = body.data(using: .utf8),
              let arr = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]], let f = arr.first else { break }
        r.latestVer = f["version"] as? String
        if let t = f["time"] as? Double {
            let o = DateFormatter(); o.dateFormat = "yyyy-MM-dd"
            r.latestDate = o.string(from: Date(timeIntervalSince1970: t / 1000))
        }
    case .firefoxJSON:
        let (body, _) = await fetch("https://product-details.mozilla.org/1.0/firefox_versions.json")
        guard let body, let data = body.data(using: .utf8),
              let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { break }
        r.latestVer = j["LATEST_FIREFOX_VERSION"] as? String
    case .anydeskLog:
        let (body, _) = await fetch("https://download.anydesk.com/changelog.txt")
        guard let body else { break }
        if let m = matches(body, "([0-9]{2})\\.([0-9]{2})\\.([0-9]{4}) - ([0-9.]+) \\(Windows\\)").first, m.count > 4 {
            r.latestVer = m[4]
            r.latestDate = "\(m[3])-\(m[2])-\(m[1])"
        }
    case .todesk:
        let (body, _) = await fetch("https://www.todesk.com/download.html")
        guard let body else { break }
        let pairs = matches(body, "version:\"([0-9][0-9.]+)\",[a-z_]*release_date:\"([0-9.]+)\"")
        var best: (String, String)?
        for p in pairs where p.count > 2 {
            if best == nil || newer(p[1], best!.0) { best = (p[1], p[2]) }
        }
        // 兜底：页面上出现过的最大版本号
        let loose = matches(body, "\"?([4-9]\\.[0-9]+\\.[0-9]+(\\.[0-9]+)?)\"?").map { $0[1] }
        if let mx = loose.max(by: { newer($1, $0) }), best == nil || newer(mx, best!.0) {
            best = (mx, best?.1 ?? "")
        }
        if let b = best { r.latestVer = b.0; r.latestDate = b.1.isEmpty ? nil : normDate(b.1) }
    case .sunlogin:
        let (page, _) = await fetch("https://sunlogin.oray.com/download")
        guard let page else { break }
        let bundles = matches(page, "(//res1\\.orayimg\\.com/sunlogin/[^\"' ]*\\.js)").map { "https:" + $0[1] }
        for b in bundles.prefix(8) {
            let (js, _) = await fetch(b)
            if let js, let m = matches(js, "SunloginClient_([0-9][0-9.]+)\\.exe").first, m.count > 1 {
                r.latestVer = m[1]; break
            }
        }
        if r.latestVer == nil, let m = matches(page, "(1[5-9]\\.[0-9]+\\.[0-9]+(\\.[0-9]+)?)").first, m.count > 1 {
            r.latestVer = m[1]
        }
        if r.latestVer == nil { r.note = "官网全动态渲染，抓不到，请点官网按钮" }
    }

    // 状态判定
    if let lv = r.latestVer {
        if spec.localVer.contains("入盘") || spec.localVer.contains("盘内") {
            r.status = spec.localVer.contains("入盘") ? .fresh : .outdated   // 入盘=当日官方最新；盘内旧版=默认过时
            if spec.localVer.contains("入盘"), let ld = r.latestDate, let sd = spec.localDate, ld > sd {
                r.status = .outdated   // 入盘之后官方又发了新的
            }
        } else if newer(lv, spec.localVer) {
            r.status = .outdated
        } else {
            r.status = .fresh
            if r.latestDate != nil { }   // 本地=最新 → 本地发布日即最新发布日
        }
    } else {
        r.status = .unknown
    }
    return r
}

// MARK: - 状态仓库

@MainActor
final class Store: ObservableObject {
    @Published var results: [String: CheckResult] = [:]
    @Published var usbPath: String?
    @Published var fileDates: [String: String] = [:]
    @Published var lastRun: String = "—"
    @Published var running = false

    func findUSB() {
        let fm = FileManager.default
        usbPath = (try? fm.contentsOfDirectory(atPath: "/Volumes"))?
            .map { "/Volumes/\($0)/新装电脑常用" }
            .first { fm.fileExists(atPath: $0) }
    }

    func loadFileDates() {
        guard let base = usbPath else { return }
        let fm = FileManager.default
        let o = DateFormatter(); o.dateFormat = "yyyy-MM-dd"
        for t in TOOLS {
            guard let rel = t.usbRel else { continue }
            if let attrs = try? fm.attributesOfItem(atPath: "\(base)/\(rel)"),
               let d = attrs[.modificationDate] as? Date {
                fileDates[t.id] = o.string(from: d)
            }
        }
    }

    func refresh() {
        running = true
        findUSB(); loadFileDates()
        for t in TOOLS { results[t.id] = CheckResult() }
        Task {
            await withTaskGroup(of: (String, CheckResult).self) { group in
                for t in TOOLS { group.addTask { (t.id, await runChecker(t)) } }
                for await (id, res) in group { await MainActor.run { self.results[id] = res } }
            }
            await MainActor.run {
                self.running = false
                let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm"
                self.lastRun = f.string(from: Date())
            }
        }
    }
}

// MARK: - 界面

struct RowView: View {
    let spec: ToolSpec
    let res: CheckResult
    let fileDate: String?

    var statusChip: some View {
        Group {
            switch res.status {
            case .checking: Text("⏳ 查询中").foregroundColor(.secondary)
            case .fresh:    Text("🟢 已是最新").foregroundColor(.green)
            case .outdated: Text("🔴 有新版").foregroundColor(.red).bold()
            case .unknown:  Text("⚪ 查不到").foregroundColor(.secondary)
            }
        }.font(.system(size: 12))
    }

    var localDateText: String {
        if res.status == .fresh, let d = res.latestDate, !spec.localVer.contains("盘内") { return d + " 发布" }
        if let d = spec.localDate { return d + (spec.localVer.contains("入盘") ? " 入盘" : " 发布") }
        if let f = fileDate { return f + " 盘内文件" }
        return "日期未知"
    }

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(spec.name).font(.system(size: 13, weight: .semibold))
                    if spec.special {
                        Text("特殊关注").font(.system(size: 9)).padding(.horizontal, 5).padding(.vertical, 1)
                            .background(Color.purple.opacity(0.2)).foregroundColor(.purple).cornerRadius(4)
                    }
                }
                if let n = res.note { Text(n).font(.system(size: 10)).foregroundColor(.orange) }
            }
            .frame(width: 170, alignment: .leading)
            VStack(alignment: .leading, spacing: 1) {
                Text(spec.localVer).font(.system(size: 12))
                Text(localDateText).font(.system(size: 10)).foregroundColor(.secondary)
            }
            .frame(width: 190, alignment: .leading)
            Image(systemName: "arrow.right").font(.system(size: 9)).foregroundColor(.secondary)
            VStack(alignment: .leading, spacing: 1) {
                Text(res.latestVer ?? "—").font(.system(size: 12))
                    .foregroundColor(res.status == .outdated ? .red : .primary)
                Text(res.latestDate.map { $0 + " 发布" } ?? "日期未知").font(.system(size: 10)).foregroundColor(.secondary)
            }
            .frame(width: 190, alignment: .leading)
            statusChip.frame(width: 90, alignment: .leading)
            Button("官网") {
                if let u = URL(string: spec.homepage) { NSWorkspace.shared.open(u) }
            }.font(.system(size: 11))
        }
        .padding(.vertical, 3)
    }
}

struct ContentView: View {
    @StateObject var store = Store()

    var outdatedCount: Int { store.results.values.filter { $0.status == .outdated }.count }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("优盘体检").font(.title2.bold())
                Text(store.usbPath == nil ? "⚠️ 未检测到维护优盘" : "盘已就位")
                    .font(.system(size: 11))
                    .foregroundColor(store.usbPath == nil ? .orange : .green)
                Spacer()
                if store.running { ProgressView().scaleEffect(0.5) }
                Text("🔴 \(outdatedCount) 项有新版").font(.system(size: 11)).foregroundColor(outdatedCount > 0 ? .red : .secondary)
                Button(store.running ? "查询中…" : "重新体检") { store.refresh() }.disabled(store.running)
            }
            .padding(10)
            Divider()
            List {
                ForEach(["特殊关注（装后自升级）", "常用", "小软件", "专业软件", "驱动与运行库"], id: \.self) { g in
                    Section(header: Text(g).font(.system(size: 11, weight: .bold))) {
                        ForEach(TOOLS.filter { $0.group == g }) { t in
                            RowView(spec: t, res: store.results[t.id] ?? CheckResult(), fileDate: store.fileDates[t.id])
                        }
                    }
                }
            }
            Divider()
            HStack {
                Text("上次体检：\(store.lastRun) ｜ 特殊关注两项装机后会自动升级，安装器新旧不影响使用 ｜ 本程序只读不写，红了找 Claude 更新")
                    .font(.system(size: 10)).foregroundColor(.secondary)
                Spacer()
            }.padding(8)
        }
        .frame(minWidth: 820, minHeight: 640)
        .onAppear { store.refresh() }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ n: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { true }
}

@main
struct UsbCheckApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}
