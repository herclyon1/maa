// Export SF Symbols from the Mac system font as 4x PNG masks for web/app.js TAB_ICONS.
//   swiftc -O scripts/mac/sf-symbols-export.swift -o /tmp/sfx && (cd /tmp && ./sfx)
// Apple licenses SF Symbols for use on Apple platforms; this page is used only on the
// user's own iPhone (his call, 2026-09-14).
import AppKit
let names = ["gauge.with.dots.needle.67percent", "shield", "mountain.2", "waveform", "iphone"]
for n in names {
    guard let img = NSImage(systemSymbolName: n, accessibilityDescription: nil) else { print("MISSING", n); continue }
    let cfg = NSImage.SymbolConfiguration(pointSize: 22, weight: .regular, scale: .medium)
    guard let sym = img.withSymbolConfiguration(cfg) else { continue }
    let scale: CGFloat = 4
    let w = Int(ceil(sym.size.width * scale)), h = Int(ceil(sym.size.height * scale))
    guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { continue }
    rep.size = sym.size
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSColor.black.set()
    sym.draw(in: NSRect(origin: .zero, size: sym.size), from: .zero, operation: .sourceOver, fraction: 1.0)
    NSGraphicsContext.restoreGraphicsState()
    let png = rep.representation(using: .png, properties: [:])!
    try! png.write(to: URL(fileURLWithPath: "\(n).png"))
    print("OK", n, Int(sym.size.width), Int(sym.size.height), w, h)
}
