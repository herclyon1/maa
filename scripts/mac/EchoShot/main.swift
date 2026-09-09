// EchoShot - one physical key, one screenshot, straight into a folder.
//
// Why it exists: scoring Wuthering Waves echoes means one screenshot per echo, dozens in a
// row, while a Moonlight stream is fullscreen. Cmd+Shift+3 is three keys and the user was
// explicit that this has to be one. macOS has no built-in single-key screenshot, and every
// third-party option (Karabiner, Hammerspoon, BetterTouchTool) is a much larger install than
// the twelve lines that actually do the work.
//
// The hotkey uses Carbon's RegisterEventHotKey, which needs no Accessibility or Input
// Monitoring grant and fires over a fullscreen game. Only the screenshot itself needs a
// permission: Screen Recording, granted once to this app.
//
// Default key is ` (the one left of 1, keycode 50) with no modifiers, which no Wuthering
// Waves default binding uses. Override it by writing a different keycode:
//     defaults write local.ark.echoshot keyCode -int 50
import AppKit
import Carbon.HIToolbox

let folder = ("~/Pictures/EchoShots" as NSString).expandingTildeInPath
let defaultKeyCode: UInt32 = 50  // kVK_ANSI_Grave

// The hotkey is grabbed globally, so the chosen key stops typing anywhere else on the Mac.
// That is the whole point for `, but it is also the reason the key is configurable.
let keyCode: UInt32 = {
    let stored = UserDefaults.standard.integer(forKey: "keyCode")
    return stored > 0 ? UInt32(stored) : defaultKeyCode
}()

func timestamp() -> String {
    let f = DateFormatter()
    f.dateFormat = "yyyyMMdd-HHmmss-SSS"
    return f.string(from: Date())
}

// A one-line log per press. Without it there is no way to tell "the key never reached the
// app" from "the key fired but Screen Recording is missing" - the user hears a thud either
// way, and the second one is the only one a permission dialog fixes.
func log(_ line: String) {
    let path = "\(folder)/echoshot.log"
    let stamp = "\(timestamp())  \(line)\n"
    if let h = FileHandle(forWritingAtPath: path) {
        h.seekToEndOfFile()
        h.write(stamp.data(using: .utf8)!)
        try? h.close()
    } else {
        try? stamp.write(toFile: path, atomically: true, encoding: .utf8)
    }
}

func shoot() {
    try? FileManager.default.createDirectory(atPath: folder,
                                             withIntermediateDirectories: true)
    let path = "\(folder)/echo-\(timestamp()).jpg"
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
    // -x is silent (screencapture's own shutter sound fires before the file exists, so the
    // sound below is what tells the user the file actually landed), -t jpg keeps a 2772x1280
    // screen under the scorer's 1 MB limit where PNG would be five times over it.
    p.arguments = ["-x", "-t", "jpg", path]
    do {
        try p.run()
        p.waitUntilExit()
    } catch {
        log("screencapture would not start: \(error)")
        NSSound(named: "Basso")?.play()
        return
    }
    // An empty or missing file means Screen Recording was never granted. Say so differently
    // from success, or the user presses the key forty times into a void.
    let attrs = try? FileManager.default.attributesOfItem(atPath: path)
    let size = (attrs?[.size] as? Int) ?? 0
    if p.terminationStatus == 0, size > 0 {
        log("ok \((path as NSString).lastPathComponent) \(size) bytes")
        NSSound(named: "Tink")?.play()
    } else {
        try? FileManager.default.removeItem(atPath: path)
        log("empty file, exit \(p.terminationStatus) - grant Screen Recording to EchoShot")
        NSSound(named: "Basso")?.play()
    }
}

var hotKeyRef: EventHotKeyRef?
var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                              eventKind: UInt32(kEventHotKeyPressed))

InstallEventHandler(GetApplicationEventTarget(), { _, _, _ in
    shoot()
    return noErr
}, 1, &eventType, nil, nil)

let hotKeyID = EventHotKeyID(signature: OSType(0x45434853), id: 1)  // 'ECHS'
let status = RegisterEventHotKey(keyCode, 0, hotKeyID,
                                 GetApplicationEventTarget(), 0, &hotKeyRef)
if status != noErr {
    FileHandle.standardError.write("RegisterEventHotKey failed: \(status)\n".data(using: .utf8)!)
    exit(1)
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
app.run()
