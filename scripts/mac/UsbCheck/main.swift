// 优盘体检 v2 —— 检测 + 半自动更新。
// · 每行：本地版本+发布时间；有新版才显示右列（新版本号+发布时间）并出现「更新」按钮
// · 顶栏「全部更新」批量处理所有可自动更新的红灯项
// · ToDesk / 向日葵 = 特殊关注：只标注不更新（装机后客户端会自动升级）
// · Office 离线包更新需要 Windows 环境重打包 → 标「需Claude」
// · 更新动作：官方直链下载 → 校验 PE/体积 → 删旧文件（按通配）→ 按命名模板放入U盘 → 记录到盘上日志
import SwiftUI

// MARK: - 模型

enum Checker {
    case github(repo: String, assetRe: String)
    case page(url: String, vRe: String, dlTemplate: String?, pickMax: Bool)
    case redirectName(url: String, vRe: String, dRe: String?)
    case lastMod(url: String, verLabel: String)     // 无版本号源：Last-Modified 当发布日，"官方{日期}版"当版本
    case officeAPI
    case chromeDash
    case firefoxJSON
    case anydeskLog
    case todesk
    case sunlogin
    case tbtool
}

struct ToolSpec: Identifiable {
    let id: String
    let name: String
    let group: String
    var special = false
    let localVer: String
    var localDate: String        // 真实发布日；空串则运行时用盘内文件日期
    var usbRel: String?          // 现文件（读盘内日期用）
    var glob: String?            // 更新时删除旧文件的通配（相对 新装电脑常用/）
    var nameTemplate: String?    // 新文件名模板，{V} 换成新版本号；nil = 不可自动更新
    var extraCopy: (glob: String, template: String)?   // 第二份拷贝（如 7-Zip 在解压软件夹）
    var zipMember: String?       // 下载物是 zip 时要抽出的成员名
    var claudeOnly = false       // 有新版但需 Claude 处理
    let homepage: String
    let checker: Checker
}

enum Status { case fresh, outdated, unknown, checking }
enum UpdState { case idle, downloading, done, fail(String) }

struct CheckResult {
    var latestVer: String?
    var latestDate: String?
    var downloadURL: String?
    var status: Status = .checking
    var note: String?
}

// MARK: - 清单（2026-08-19 基线，版本与日期均为真实发布数据）

let TOOLS: [ToolSpec] = [
    ToolSpec(id: "todesk", name: "ToDesk", group: "特殊关注（装后自升级）", special: true,
             localVer: "4.7.6.3", localDate: "",
             usbRel: "其他的专业软件/远程控制类/ToDesk_4.7.6.3（备用远控）.exe",
             homepage: "https://www.todesk.com/download.html", checker: .todesk),
    ToolSpec(id: "sunlogin", name: "向日葵", group: "特殊关注（装后自升级）", special: true,
             localVer: "15.8.2.19742", localDate: "",
             usbRel: "其他的专业软件/远程控制类/向日葵_15.8.2（广泛使用）.exe",
             homepage: "https://sunlogin.oray.com/download", checker: .sunlogin),

    ToolSpec(id: "huorong", name: "火绒安全", group: "常用", localVer: "6.0.11.2", localDate: "2026-08-18",
             usbRel: "火绒（推荐杀毒软件）.exe", glob: "火绒（推荐杀毒软件）.exe", nameTemplate: "火绒（推荐杀毒软件）.exe",
             homepage: "https://www.huorong.cn/person",
             checker: .redirectName(url: "https://www.huorong.cn/product/downloadHr60.php?pro=hr60",
                                    vRe: "sysdiag-all-x86-([0-9.]+)-", dRe: "-([0-9]{4}\\.[0-9]{2}\\.[0-9]{2})")),
    ToolSpec(id: "7zip", name: "7-Zip", group: "常用", localVer: "26.02", localDate: "2026-06-26",
             usbRel: "解压软件7-Zip 26.02（官方版）.exe", glob: "解压软件7-Zip*（官方版）.exe",
             nameTemplate: "解压软件7-Zip {V}（官方版）.exe",
             extraCopy: (glob: "其他小软件/解压软件/7z*官方版.exe", template: "其他小软件/解压软件/7z {V}官方版.exe"),
             homepage: "https://www.7-zip.org", checker: .github(repo: "ip7z/7zip", assetRe: "^7z[0-9]+-x64\\.exe$")),
    ToolSpec(id: "chrome", name: "谷歌浏览器", group: "常用", localVer: "151.0.7922.170", localDate: "2026-08-19",
             usbRel: "谷歌浏览器（官方离线版）.exe", glob: "谷歌浏览器（官方离线版）.exe", nameTemplate: "谷歌浏览器（官方离线版）.exe",
             homepage: "https://www.google.com/chrome/", checker: .chromeDash),
    ToolSpec(id: "firefox", name: "火狐浏览器", group: "常用", localVer: "154.0", localDate: "2026-08-17",
             usbRel: "火狐浏览器国际版（无广告）.exe", glob: "火狐浏览器国际版（无广告）.exe", nameTemplate: "火狐浏览器国际版（无广告）.exe",
             homepage: "https://www.mozilla.org/firefox/", checker: .firefoxJSON),
    ToolSpec(id: "360cse", name: "360极速浏览器X", group: "常用", localVer: "23.0.1253.0", localDate: "2026-07-03",
             usbRel: "360极速浏览器X（国内使用）.exe", glob: "360极速浏览器X（国内使用）.exe", nameTemplate: "360极速浏览器X（国内使用）.exe",
             homepage: "https://browser.360.cn/ee/",
             checker: .page(url: "https://browser.360.cn/ee/", vRe: "360cse_([0-9.]+)\\.exe",
                            dlTemplate: "https://sedl.360tpcdn.com/cse/360cse_{V}.exe", pickMax: true)),
    ToolSpec(id: "sogou", name: "搜狗输入法", group: "常用", localVer: "16.7b", localDate: "",
             usbRel: "搜狗输入法（官方版16.7）.exe", glob: "搜狗输入法（官方版*）.exe", nameTemplate: "搜狗输入法（官方版{V}）.exe",
             homepage: "https://shurufa.sogou.com/",
             checker: .page(url: "https://shurufa.sogou.com/", vRe: "pinyin_guanwang_([0-9.]+[a-z]?)\\.exe",
                            dlTemplate: "http://ime.gtimg.com/pc/sogou_pinyin_guanwang_{V}.exe", pickMax: false)),
    ToolSpec(id: "office", name: "Office 离线包", group: "常用", localVer: "16.0.20326.20100", localDate: "2026-08-19",
             usbRel: "Office离线安装包（免联网安装Word Excel PPT）/setup.exe", claudeOnly: true,
             homepage: "https://www.office.com", checker: .officeAPI),

    ToolSpec(id: "everything", name: "Everything", group: "小软件", localVer: "1.4.1.1032", localDate: "2026-01-23",
             usbRel: "其他小软件/Everything-1.4.1.1032（文件搜索）.exe", glob: "其他小软件/Everything-*（文件搜索）.exe",
             nameTemplate: "其他小软件/Everything-{V}（文件搜索）.exe",
             homepage: "https://www.voidtools.com",
             checker: .page(url: "https://www.voidtools.com/downloads/", vRe: "Everything-([0-9.]+)\\.x64-Setup\\.exe",
                            dlTemplate: "https://www.voidtools.com/Everything-{V}.x64-Setup.exe", pickMax: false)),
    ToolSpec(id: "npp", name: "Notepad++", group: "小软件", localVer: "8.9.7", localDate: "2026-07-14",
             usbRel: "其他小软件/Notepad++（文本类处理）.exe", glob: "其他小软件/Notepad++（文本类处理）.exe",
             nameTemplate: "其他小软件/Notepad++（文本类处理）.exe",
             homepage: "https://notepad-plus-plus.org",
             checker: .github(repo: "notepad-plus-plus/notepad-plus-plus", assetRe: "Installer\\.x64\\.exe$")),
    ToolSpec(id: "potplayer", name: "PotPlayer", group: "小软件", localVer: "官方2026-08-19版", localDate: "2026-08-19",
             usbRel: "其他小软件/PotPlayer官方最新版（专业视频播放器）.exe", glob: "其他小软件/PotPlayer官方最新版（专业视频播放器）.exe",
             nameTemplate: "其他小软件/PotPlayer官方最新版（专业视频播放器）.exe",
             homepage: "https://potplayer.daum.net",
             checker: .lastMod(url: "https://t1.daumcdn.net/potplayer/PotPlayer/Version/Latest/PotPlayerSetup64.exe", verLabel: "官方{D}版")),
    ToolSpec(id: "idm", name: "IDM", group: "小软件", localVer: "6.43 Build 9", localDate: "2026-08-17",
             usbRel: "其他小软件/IDM 6.43官方版（多线程下载·付费软件30天试用）.exe", glob: "其他小软件/IDM *官方版（多线程下载·付费软件30天试用）.exe",
             nameTemplate: "其他小软件/IDM {V}官方版（多线程下载·付费软件30天试用）.exe",
             homepage: "https://www.internetdownloadmanager.com",
             checker: .page(url: "https://www.internetdownloadmanager.com/download.html", vRe: "idman([0-9]+build[0-9]+)\\.exe",
                            dlTemplate: "https://download.internetdownloadmanager.com/idman{RAW}.exe", pickMax: false)),
    ToolSpec(id: "memreduct", name: "Mem Reduct", group: "小软件", localVer: "3.4", localDate: "2023-02-11",
             usbRel: "其他小软件/Mem Reduct（内存定时清理）.zip", glob: "其他小软件/Mem Reduct（内存定时清理）.*",
             nameTemplate: "其他小软件/Mem Reduct {V}（内存定时清理）.exe",
             homepage: "https://github.com/henrypp/memreduct",
             checker: .github(repo: "henrypp/memreduct", assetRe: "-setup\\.exe$")),
    ToolSpec(id: "twinkle", name: "Twinkle Tray", group: "小软件", localVer: "1.16.6", localDate: "2025-01-10",
             usbRel: "其他小软件/Twinkle.Tray.v1.16.6（显示器亮度调节）.exe", glob: "其他小软件/Twinkle.Tray*（显示器亮度调节）.exe",
             nameTemplate: "其他小软件/Twinkle.Tray.v{V}（显示器亮度调节）.exe",
             homepage: "https://twinkletray.com",
             checker: .github(repo: "xanderfrangos/twinkle-tray", assetRe: "^Twinkle.*\\.exe$")),
    ToolSpec(id: "honeyview", name: "HoneyView", group: "小软件", localVer: "5.53", localDate: "2024-06-21",
             usbRel: "其他小软件/HoneyView（图片查看器）.exe", glob: "其他小软件/HoneyView（图片查看器）.exe",
             nameTemplate: "其他小软件/HoneyView（图片查看器）.exe",
             homepage: "https://www.bandisoft.com/honeyview/",
             checker: .page(url: "https://www.bandisoft.com/honeyview/", vRe: "HoneyView ?v?([0-9]+\\.[0-9.]+)",
                            dlTemplate: "https://dl.bandisoft.com/honeyview/HONEYVIEW-SETUP.EXE", pickMax: false)),
    ToolSpec(id: "rammap", name: "RamMap", group: "小软件", localVer: "1.51", localDate: "",
             usbRel: "其他小软件/RamMap（清理内存）.exe", glob: "其他小软件/RamMap（清理内存）.exe",
             nameTemplate: "其他小软件/RamMap（清理内存）.exe", zipMember: "RAMMap.exe",
             homepage: "https://learn.microsoft.com/sysinternals/downloads/rammap",
             checker: .page(url: "https://learn.microsoft.com/en-us/sysinternals/downloads/rammap", vRe: "RAMMap v([0-9.]+)",
                            dlTemplate: "https://download.sysinternals.com/files/RAMMap.zip", pickMax: false)),

    ToolSpec(id: "cpuz", name: "CPU-Z", group: "专业软件", localVer: "2.21", localDate: "2026-08-17",
             usbRel: "其他的专业软件/CPU-Z（CPU信息）.exe", glob: "其他的专业软件/CPU-Z（CPU信息）.exe",
             nameTemplate: "其他的专业软件/CPU-Z（CPU信息）.exe",
             homepage: "https://www.cpuid.com/softwares/cpu-z.html",
             checker: .page(url: "https://www.cpuid.com/softwares/cpu-z.html", vRe: "cpu-z_([0-9.]+)-en\\.exe",
                            dlTemplate: "https://download.cpuid.com/cpu-z/cpu-z_{V}-en.exe", pickMax: true)),
    ToolSpec(id: "gpuz", name: "GPU-Z", group: "专业软件", localVer: "2.70.0", localDate: "",
             usbRel: "其他的专业软件/GPU-Z（显卡信息).exe", glob: "其他的专业软件/GPU-Z（显卡信息).exe",
             nameTemplate: "其他的专业软件/GPU-Z（显卡信息).exe",
             homepage: "https://www.techpowerup.com/download/techpowerup-gpu-z/",
             checker: .page(url: "https://www.techpowerup.com/download/techpowerup-gpu-z/", vRe: "v(2\\.[0-9.]+)",
                            dlTemplate: "GPUZ_POST", pickMax: true)),
    ToolSpec(id: "clash", name: "Clash Verge", group: "专业软件", localVer: "2.5.2", localDate: "2026-07-19",
             usbRel: "其他的专业软件/Clash.Verge_2.5.2（翻墙工具）.exe", glob: "其他的专业软件/Clash.Verge_*（翻墙工具）.exe",
             nameTemplate: "其他的专业软件/Clash.Verge_{V}（翻墙工具）.exe",
             homepage: "https://github.com/clash-verge-rev/clash-verge-rev",
             checker: .github(repo: "clash-verge-rev/clash-verge-rev", assetRe: "x64-setup\\.exe$")),
    ToolSpec(id: "diskgenius", name: "DiskGenius", group: "专业软件", localVer: "6.2.0.1829", localDate: "2026-06-08",
             usbRel: "其他的专业软件/DiskGenius专业版6.2 x64（分区工具·解压后用）.zip", glob: "其他的专业软件/DiskGenius专业版* x64（分区工具·解压后用）.zip",
             nameTemplate: "其他的专业软件/DiskGenius专业版{V} x64（分区工具·解压后用）.zip",
             homepage: "https://www.diskgenius.cn",
             checker: .page(url: "https://www.diskgenius.cn/download.php", vRe: "DG([0-9]{7})_x64\\.zip",
                            dlTemplate: "https://download_cn.eassos.com/DG{RAW}_x64.zip", pickMax: false)),
    ToolSpec(id: "geek", name: "Geek Uninstaller", group: "专业软件", localVer: "1.5.3.170", localDate: "2025-11-24",
             usbRel: "其他的专业软件/强力卸载软件（Geek官方版）.exe", glob: "其他的专业软件/强力卸载软件（Geek官方版）.exe",
             nameTemplate: "其他的专业软件/强力卸载软件（Geek官方版）.exe", zipMember: "geek.exe",
             homepage: "https://geekuninstaller.com",
             checker: .page(url: "https://geekuninstaller.com/download", vRe: "([0-9]\\.[0-9]\\.[0-9]+)",
                            dlTemplate: "https://geekuninstaller.com/geek.zip", pickMax: false)),
    ToolSpec(id: "revo", name: "Revo Uninstaller", group: "专业软件", localVer: "官方2026-05-13版", localDate: "2026-05-13",
             usbRel: "其他的专业软件/软件卸载Revo_Uninstaller（官方免费版）.exe", glob: "其他的专业软件/软件卸载Revo_Uninstaller（官方免费版）.exe",
             nameTemplate: "其他的专业软件/软件卸载Revo_Uninstaller（官方免费版）.exe",
             homepage: "https://www.revouninstaller.com",
             checker: .lastMod(url: "https://download.revouninstaller.com/download/revosetup.exe", verLabel: "官方{D}版")),
    ToolSpec(id: "anydesk", name: "AnyDesk", group: "专业软件", localVer: "9.7.15", localDate: "2026-08-17",
             usbRel: "其他的专业软件/远程控制类/AnyDesk（内网远程）.exe", glob: "其他的专业软件/远程控制类/AnyDesk（内网远程）.exe",
             nameTemplate: "其他的专业软件/远程控制类/AnyDesk（内网远程）.exe",
             homepage: "https://anydesk.com", checker: .anydeskLog),
    ToolSpec(id: "tbtool", name: "图吧工具箱", group: "专业软件", localVer: "2026.08", localDate: "2026-08 月版",
             usbRel: "其他的专业软件/【工具大全】图吧工具箱2026年08月.exe",
             homepage: "https://www.tbtool.cn", checker: .tbtool),

    ToolSpec(id: "360drv", name: "360驱动大师·网卡版", group: "驱动与运行库", localVer: "官方2026-04-20版", localDate: "2026-04-20",
             usbRel: "各种驱动工具/360驱动大师·网卡版（小白推荐）.exe", glob: "各种驱动工具/360驱动大师·网卡版（小白推荐）.exe",
             nameTemplate: "各种驱动工具/360驱动大师·网卡版（小白推荐）.exe",
             homepage: "https://dd.360.cn",
             checker: .lastMod(url: "https://dl.360safe.com/drvmgr/360DrvMgrInstaller_net.exe", verLabel: "官方{D}版")),
    ToolSpec(id: "drvceo", name: "驱动总裁·离线网卡版", group: "驱动与运行库", localVer: "2.18.0.11", localDate: "",
             usbRel: "各种驱动工具/驱动总裁·离线网卡版（专业驱动）.exe",
             homepage: "https://www.sysceo.com/dc",
             checker: .page(url: "https://www.sysceo.com/dc/download.html", vRe: "(20[0-9]{2}/[0-9]{2}/[0-9]{2})", dlTemplate: nil, pickMax: true)),
    ToolSpec(id: "vcredist", name: "VisualCppRedist 运行库", group: "驱动与运行库", localVer: "0.105.0", localDate: "2026-06-06",
             usbRel: "插件或补丁（软件打不开试试打这个）/VisualCppRedist(运行库合集) v0.105.exe",
             glob: "插件或补丁（软件打不开试试打这个）/VisualCppRedist(运行库合集)*.exe",
             nameTemplate: "插件或补丁（软件打不开试试打这个）/VisualCppRedist(运行库合集) v{V}.exe",
             homepage: "https://github.com/abbodi1406/vcredist",
             checker: .github(repo: "abbodi1406/vcredist", assetRe: "AIO_x86_x64\\.exe$")),
    ToolSpec(id: "java21", name: "Java 21", group: "驱动与运行库", localVer: "21.0.12", localDate: "2026-07-15",
             usbRel: "插件或补丁（软件打不开试试打这个）/Java21 64位（Oracle官方最新）.exe",
             glob: "插件或补丁（软件打不开试试打这个）/Java21 64位（Oracle官方最新）.exe",
             nameTemplate: "插件或补丁（软件打不开试试打这个）/Java21 64位（Oracle官方最新）.exe",
             homepage: "https://www.oracle.com/java/technologies/downloads/",
             checker: .lastMod(url: "https://download.oracle.com/java/21/latest/jdk-21_windows-x64_bin.exe", verLabel: "官方{D}版")),
]

// MARK: - 网络工具

let UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

final class NoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ s: URLSession, task: URLSessionTask, willPerformHTTPRedirection r: HTTPURLResponse,
                    newRequest req: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}

func request(_ url: String, method: String = "GET", follow: Bool = true,
             referer: String? = nil, body: String? = nil) async -> (Data?, [String: String]) {
    guard let u = URL(string: url) else { return (nil, [:]) }
    var rq = URLRequest(url: u, timeoutInterval: 30)
    rq.httpMethod = method
    rq.setValue(UA, forHTTPHeaderField: "User-Agent")
    if let referer { rq.setValue(referer, forHTTPHeaderField: "Referer") }
    if let body {
        rq.httpBody = body.data(using: .utf8)
        rq.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
    }
    let cfg = URLSessionConfiguration.ephemeral
    cfg.timeoutIntervalForResource = 600
    let sess = follow ? URLSession(configuration: cfg)
                      : URLSession(configuration: cfg, delegate: NoRedirect(), delegateQueue: nil)
    do {
        let (data, resp) = try await sess.data(for: rq)
        var headers: [String: String] = [:]
        if let h = resp as? HTTPURLResponse {
            for (k, v) in h.allHeaderFields { headers[String(describing: k).lowercased()] = String(describing: v) }
        }
        return (data, headers)
    } catch { return (nil, [:]) }
}

func fetchText(_ url: String) async -> String? {
    let (d, _) = await request(url)
    return d.flatMap { String(data: $0, encoding: .utf8) }
}

func lastModified(_ url: String) async -> String? {
    let (_, h) = await request(url, method: "HEAD")
    guard let lm = h["last-modified"] else { return nil }
    let f = DateFormatter(); f.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"; f.locale = Locale(identifier: "en_US_POSIX")
    guard let d = f.date(from: lm) else { return nil }
    let o = DateFormatter(); o.dateFormat = "yyyy-MM-dd"
    return o.string(from: d)
}

func matches(_ text: String, _ pattern: String) -> [[String]] {
    guard let re = try? NSRegularExpression(pattern: pattern) else { return [] }
    let ns = text as NSString
    return re.matches(in: text, range: NSRange(location: 0, length: ns.length)).map { m in
        (0..<m.numberOfRanges).map { m.range(at: $0).location == NSNotFound ? "" : ns.substring(with: m.range(at: $0)) }
    }
}

func verKey(_ v: String) -> [Int] { v.split(whereSeparator: { !$0.isNumber }).compactMap { Int($0) } }
func newer(_ a: String, _ b: String) -> Bool {
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
    let parts = t.split(separator: "-")
    if parts.count == 3 {
        return String(format: "%04d-%02d-%02d", Int(parts[0]) ?? 0, Int(parts[1]) ?? 0, Int(parts[2]) ?? 0)
    }
    return t
}

// MARK: - 查询

func runChecker(_ spec: ToolSpec) async -> CheckResult {
    var r = CheckResult()
    switch spec.checker {
    case .github(let repo, let assetRe):
        guard let body = await fetchText("https://api.github.com/repos/\(repo)/releases/latest"),
              let data = body.data(using: .utf8),
              let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { break }
        var tag = (j["tag_name"] as? String) ?? ""
        if tag.hasPrefix("v") { tag.removeFirst() }
        r.latestVer = tag
        if let d = j["published_at"] as? String { r.latestDate = String(d.prefix(10)) }
        if let assets = j["assets"] as? [[String: Any]] {
            for a in assets {
                if let n = a["name"] as? String, !matches(n, assetRe).isEmpty {
                    r.downloadURL = a["browser_download_url"] as? String; break
                }
            }
        }
    case .page(let url, let vRe, let dlTemplate, let pickMax):
        guard let body = await fetchText(url) else { break }
        let ms = matches(body, vRe)
        guard !ms.isEmpty else { break }
        var raws = ms.map { $0.count > 1 ? $0[1] : $0[0] }
        if pickMax { raws.sort { newer($0, $1) } }
        let raw = raws[0]
        if spec.id == "idm" {           // 643build9 → 6.43 Build 9
            let p = raw.split(separator: "b", maxSplits: 1)
            let num = String(p[0]), bld = raw.contains("build") ? raw.components(separatedBy: "build")[1] : ""
            r.latestVer = "\(num.prefix(1)).\(num.dropFirst()) Build \(bld)"
        } else if spec.id == "diskgenius" {   // 6201829 → 6.2.0.1829
            r.latestVer = "\(raw.prefix(1)).\(raw.dropFirst(1).prefix(1)).\(raw.dropFirst(2).prefix(1)).\(raw.suffix(4))"
        } else if spec.id == "drvceo" {   // 官网只公布更新日期不公布版本号
            r.latestVer = "官方\(raw.replacingOccurrences(of: "/", with: "-"))更新"
            r.latestDate = raw.replacingOccurrences(of: "/", with: "-")
        } else {
            r.latestVer = raw
        }
        if var t = dlTemplate {
            if t == "GPUZ_POST" { r.downloadURL = "GPUZ_POST" }
            else {
                t = t.replacingOccurrences(of: "{V}", with: raw)
                t = t.replacingOccurrences(of: "{RAW}", with: raw)
                r.downloadURL = t
            }
        }
        if r.latestDate == nil, let dl = r.downloadURL, dl.hasPrefix("http") {
            r.latestDate = await lastModified(dl)
        }
    case .redirectName(let url, let vRe, let dRe):
        let (_, h) = await request(url, method: "HEAD", follow: false)
        let loc = h["location"] ?? ""
        if let m = matches(loc, vRe).first, m.count > 1 { r.latestVer = m[1] }
        if let dRe, let m = matches(loc, dRe).first, m.count > 1 { r.latestDate = normDate(m[1]) }
        if !loc.isEmpty { r.downloadURL = url }
    case .lastMod(let url, let verLabel):
        if let d = await lastModified(url) {
            r.latestDate = d
            r.latestVer = verLabel.replacingOccurrences(of: "{D}", with: d)
            r.downloadURL = url
        }
    case .officeAPI:
        guard let body = await fetchText("https://clients.config.office.net/releases/v1.0/OfficeReleases"),
              let data = body.data(using: .utf8),
              let arr = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]], let f = arr.first else { break }
        r.latestVer = f["latestVersion"] as? String
        if let ovs = f["officeVersions"] as? [[String: Any]], let d = ovs.first?["availabilityDate"] as? String {
            r.latestDate = String(d.prefix(10))
        }
    case .chromeDash:
        guard let body = await fetchText("https://chromiumdash.appspot.com/fetch_releases?channel=Stable&platform=Windows&num=1"),
              let data = body.data(using: .utf8),
              let arr = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]], let f = arr.first else { break }
        r.latestVer = f["version"] as? String
        if let t = f["time"] as? Double {
            let o = DateFormatter(); o.dateFormat = "yyyy-MM-dd"
            r.latestDate = o.string(from: Date(timeIntervalSince1970: t / 1000))
        }
        r.downloadURL = "https://dl.google.com/chrome/install/standalonesetup64.exe"
    case .firefoxJSON:
        guard let body = await fetchText("https://product-details.mozilla.org/1.0/firefox_versions.json"),
              let data = body.data(using: .utf8),
              let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { break }
        r.latestVer = j["LATEST_FIREFOX_VERSION"] as? String
        r.downloadURL = "https://download.mozilla.org/?product=firefox-latest-ssl&os=win64&lang=zh-CN"
        r.latestDate = await lastModified(r.downloadURL!)
    case .anydeskLog:
        guard let body = await fetchText("https://download.anydesk.com/changelog.txt") else { break }
        if let m = matches(body, "([0-9]{2})\\.([0-9]{2})\\.([0-9]{4}) - ([0-9.]+) \\(Windows\\)").first, m.count > 4 {
            r.latestVer = m[4]
            r.latestDate = "\(m[3])-\(m[2])-\(m[1])"
            r.downloadURL = "https://download.anydesk.com/AnyDesk.exe"
        }
    case .todesk:
        guard let body = await fetchText("https://www.todesk.com/download.html") else { break }
        let pairs = matches(body, "version:\"([0-9][0-9.]+)\",[a-z_]*release_date:\"([0-9.]+)\"")
        var best: (String, String)?
        for p in pairs where p.count > 2 {
            if best == nil || newer(p[1], best!.0) { best = (p[1], p[2]) }
        }
        if let b = best { r.latestVer = b.0; r.latestDate = normDate(b.1) }
    case .sunlogin:
        // 贝锐官方版本 API（向日葵X for Windows）
        if let body = await fetchText("https://client-webapi.oray.com/softwares/SUNLOGIN_X_WINDOWS?versiontype=stable"),
           let data = body.data(using: .utf8),
           let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            r.latestVer = j["versionno"] as? String
            if let c = j["createtime"] as? String { r.latestDate = String(c.prefix(10)) }
        }
        if r.latestVer == nil { r.note = "官方API未响应，点官网按钮看" }
    case .tbtool:
        guard let body = await fetchText("https://www.tbtool.cn/") else { break }
        if let m = matches(body, "(20[0-9]{2}\\.[0-9]{2})").first, m.count > 1 {
            r.latestVer = m[1]
            r.latestDate = m[1].replacingOccurrences(of: ".", with: "-") + " 月版"
        }
    }

    if let lv = r.latestVer {
        if spec.localVer.contains("盘内") { r.status = .outdated }
        else if newer(lv, spec.localVer) { r.status = .outdated }
        else { r.status = .fresh }
    } else {
        r.status = .unknown
    }
    return r
}

// MARK: - 更新引擎

func gpuzDownload() async -> Data? {
    let (d, _) = await request("https://www.techpowerup.com/download/techpowerup-gpu-z/",
                               method: "POST", referer: "https://www.techpowerup.com/download/techpowerup-gpu-z/",
                               body: "id=3180&server_id=15")
    return d
}

enum UpdateError: Error, LocalizedError {
    case msg(String)
    var errorDescription: String? { if case .msg(let m) = self { return m }; return nil }
}

func performUpdate(spec: ToolSpec, result: CheckResult, usbBase: String) async throws -> String {
    guard let dl = result.downloadURL, let template = spec.nameTemplate, let ver = result.latestVer else {
        throw UpdateError.msg("无直链")
    }
    var data: Data?
    if dl == "GPUZ_POST" { data = await gpuzDownload() }
    else { (data, _) = await request(dl) }
    guard var payload = data, payload.count > 200_000 else { throw UpdateError.msg("下载失败或文件过小") }

    let fm = FileManager.default
    let tmpDir = fm.temporaryDirectory.appendingPathComponent("usbcheck-\(spec.id)")
    try? fm.removeItem(at: tmpDir)
    try fm.createDirectory(at: tmpDir, withIntermediateDirectories: true)

    // zip 抽取
    let isZip = payload.prefix(2) == Data([0x50, 0x4B])
    if isZip, let member = spec.zipMember {
        let zipPath = tmpDir.appendingPathComponent("pkg.zip")
        try payload.write(to: zipPath)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        p.arguments = ["-x", "-k", zipPath.path, tmpDir.path]
        try p.run(); p.waitUntilExit()
        guard let found = (fm.enumerator(atPath: tmpDir.path)?.allObjects as? [String])?
                .first(where: { ($0 as NSString).lastPathComponent.lowercased() == member.lowercased() }) else {
            throw UpdateError.msg("zip里找不到 \(member)")
        }
        payload = try Data(contentsOf: tmpDir.appendingPathComponent(found))
    }
    // PE / zip 校验
    let magicOK = payload.prefix(2) == Data([0x4D, 0x5A]) || payload.prefix(2) == Data([0x50, 0x4B])
    guard magicOK else { throw UpdateError.msg("下载内容不是有效安装包（可能是网页）") }

    // 删旧 + 落新
    func place(glob: String, template: String) throws {
        let dir = (glob as NSString).deletingLastPathComponent
        let pattern = (glob as NSString).lastPathComponent
        let absDir = dir.isEmpty ? usbBase : "\(usbBase)/\(dir)"
        if let items = try? fm.contentsOfDirectory(atPath: absDir) {
            for it in items where matchGlob(pattern, it) {
                try? fm.removeItem(atPath: "\(absDir)/\(it)")
            }
        }
        let cleanVer = ver.replacingOccurrences(of: " Build ", with: "b").replacingOccurrences(of: "官方", with: "").replacingOccurrences(of: "版", with: "")
        let newRel = template.replacingOccurrences(of: "{V}", with: cleanVer)
        try payload.write(to: URL(fileURLWithPath: "\(usbBase)/\(newRel)"))
    }
    if let glob = spec.glob { try place(glob: glob, template: template) }
    if let extra = spec.extraCopy { try place(glob: extra.glob, template: extra.template) }

    // 盘上日志
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm"
    let line = "\n[\(f.string(from: Date()))] 优盘体检自动更新：\(spec.name) → \(ver)（\(result.latestDate ?? "日期未知")）"
    if let h = FileHandle(forWritingAtPath: "\(usbBase)/更新记录2026-08-19.txt") {
        h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); h.closeFile()
    }
    try? fm.removeItem(at: tmpDir)
    return ver
}

func matchGlob(_ pattern: String, _ name: String) -> Bool {
    let re = "^" + NSRegularExpression.escapedPattern(for: pattern)
        .replacingOccurrences(of: "\\*", with: ".*") + "$"
    return !matches(name, re).isEmpty
}

// MARK: - 状态仓库

@MainActor
final class Store: ObservableObject {
    @Published var results: [String: CheckResult] = [:]
    @Published var updStates: [String: UpdState] = [:]
    @Published var usbPath: String?
    @Published var fileDates: [String: String] = [:]
    @Published var lastRun = "—"
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
               let d = attrs[.modificationDate] as? Date { fileDates[t.id] = o.string(from: d) }
        }
    }

    func refresh() {
        running = true
        findUSB(); loadFileDates()
        for t in TOOLS { results[t.id] = CheckResult(); updStates[t.id] = .idle }
        Task {
            await withTaskGroup(of: (String, CheckResult).self) { g in
                for t in TOOLS { g.addTask { (t.id, await runChecker(t)) } }
                for await (id, res) in g { await MainActor.run { self.results[id] = res } }
            }
            await MainActor.run {
                self.running = false
                let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm"
                self.lastRun = f.string(from: Date())
            }
        }
    }

    func canAutoUpdate(_ t: ToolSpec) -> Bool {
        guard !t.special, !t.claudeOnly, t.nameTemplate != nil,
              let r = results[t.id], r.status == .outdated, r.downloadURL != nil else { return false }
        return true
    }

    func update(_ t: ToolSpec) {
        guard let base = usbPath, let r = results[t.id] else { return }
        updStates[t.id] = .downloading
        Task {
            do {
                let v = try await performUpdate(spec: t, result: r, usbBase: base)
                await MainActor.run {
                    self.updStates[t.id] = .done
                    var nr = r; nr.status = .fresh
                    self.results[t.id] = nr
                    _ = v
                }
            } catch {
                await MainActor.run { self.updStates[t.id] = .fail(error.localizedDescription) }
            }
        }
    }

    func updateAll() {
        for t in TOOLS where canAutoUpdate(t) { update(t) }
    }
}

// MARK: - 界面

struct RowView: View {
    let spec: ToolSpec
    @ObservedObject var store: Store

    var res: CheckResult { store.results[spec.id] ?? CheckResult() }
    var upd: UpdState { store.updStates[spec.id] ?? .idle }

    var localDateText: String {
        if spec.localDate.contains("月版") { return spec.localDate }
        if !spec.localDate.isEmpty { return spec.localDate + " 发布" }
        return "发布日待查"
    }

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(spec.name).font(.system(size: 13, weight: .semibold))
                    if spec.special {
                        Text("特殊关注").font(.system(size: 9)).padding(.horizontal, 5).padding(.vertical, 1)
                            .background(Color.purple.opacity(0.18)).foregroundColor(.purple).cornerRadius(4)
                    }
                }
                if let n = res.note { Text(n).font(.system(size: 10)).foregroundColor(.orange) }
                if case .fail(let m) = upd { Text("更新失败：\(m)").font(.system(size: 10)).foregroundColor(.red) }
            }
            .frame(width: 185, alignment: .leading)

            VStack(alignment: .leading, spacing: 1) {
                Text(spec.localVer).font(.system(size: 12))
                Text(localDateText).font(.system(size: 10)).foregroundColor(.secondary)
            }
            .frame(width: 180, alignment: .leading)

            Group {
                if res.status == .outdated {
                    Image(systemName: "arrow.right").font(.system(size: 9)).foregroundColor(.secondary)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(res.latestVer ?? "—").font(.system(size: 12)).foregroundColor(.red)
                        Text(res.latestDate.map { $0.contains("月版") ? $0 : $0 + " 发布" } ?? "日期未知")
                            .font(.system(size: 10)).foregroundColor(.secondary)
                    }
                    .frame(width: 167, alignment: .leading)
                } else {
                    Spacer().frame(width: 190)
                }
            }

            Group {
                switch res.status {
                case .checking: Text("⏳").font(.system(size: 12))
                case .fresh:    Text(upd.isDone ? "✅ 已更新" : "🟢 已是最新").font(.system(size: 12)).foregroundColor(.green)
                case .outdated: Text("🔴 有新版").font(.system(size: 12)).foregroundColor(.red).bold()
                case .unknown:  Text("⚪ 查不到").font(.system(size: 12)).foregroundColor(.secondary)
                }
            }
            .frame(width: 82, alignment: .leading)

            Group {
                if case .downloading = upd {
                    ProgressView().scaleEffect(0.45).frame(width: 66)
                } else if store.canAutoUpdate(spec), !upd.isDone {
                    Button("更新") { store.update(spec) }.font(.system(size: 11)).tint(.red)
                } else if spec.claudeOnly, res.status == .outdated {
                    Text("需Claude").font(.system(size: 10)).foregroundColor(.orange).frame(width: 66)
                } else {
                    Button("官网") { if let u = URL(string: spec.homepage) { NSWorkspace.shared.open(u) } }
                        .font(.system(size: 11))
                }
            }
            .frame(width: 76, alignment: .leading)
        }
        .padding(.vertical, 3)
    }
}

extension UpdState {
    var isDone: Bool { if case .done = self { return true }; return false }
}

struct ContentView: View {
    @StateObject var store = Store()

    var outdatedAuto: Int { TOOLS.filter { store.canAutoUpdate($0) }.count }
    var outdatedCount: Int { store.results.values.filter { $0.status == .outdated }.count }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Text("优盘体检").font(.title2.bold())
                Text(store.usbPath == nil ? "⚠️ 未检测到维护优盘" : "盘已就位")
                    .font(.system(size: 11)).foregroundColor(store.usbPath == nil ? .orange : .green)
                Spacer()
                if store.running { ProgressView().scaleEffect(0.5) }
                Text("🔴 \(outdatedCount)").font(.system(size: 11)).foregroundColor(outdatedCount > 0 ? .red : .secondary)
                if outdatedAuto > 0 {
                    Button("一键更新全部（\(outdatedAuto)项）") { store.updateAll() }
                        .font(.system(size: 11)).tint(.red)
                }
                Button(store.running ? "查询中…" : "重新体检") { store.refresh() }.disabled(store.running)
            }
            .padding(10)
            Divider()
            List {
                ForEach(["特殊关注（装后自升级）", "常用", "小软件", "专业软件", "驱动与运行库"], id: \.self) { g in
                    Section(header: Text(g).font(.system(size: 11, weight: .bold))) {
                        ForEach(TOOLS.filter { $0.group == g }) { t in
                            RowView(spec: t, store: store)
                        }
                    }
                }
            }
            Divider()
            Text("上次体检：\(store.lastRun) ｜ 特殊关注两项装机后自动升级，只标注不更新 ｜ 更新=官方直链下载+替换盘内旧文件，动作记入盘上更新记录")
                .font(.system(size: 10)).foregroundColor(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading).padding(8)
        }
        .frame(minWidth: 860, minHeight: 660)
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
