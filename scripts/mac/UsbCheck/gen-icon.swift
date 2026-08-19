import AppKit
let size: CGFloat = 1024
let img = NSImage(size: NSSize(width: size, height: size))
img.lockFocus()
let rect = NSRect(x: 40, y: 40, width: size-80, height: size-80)
let path = NSBezierPath(roundedRect: rect, xRadius: 180, yRadius: 180)
NSGradient(colors: [NSColor(calibratedRed: 0.13, green: 0.45, blue: 0.95, alpha: 1),
                    NSColor(calibratedRed: 0.05, green: 0.25, blue: 0.6, alpha: 1)])!
    .draw(in: path, angle: -90)
let str = "🩺" as NSString
let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 560)]
let ssize = str.size(withAttributes: attrs)
str.draw(at: NSPoint(x: (size-ssize.width)/2, y: (size-ssize.height)/2-20), withAttributes: attrs)
let sub = "USB" as NSString
let sattrs: [NSAttributedString.Key: Any] = [.font: NSFont.boldSystemFont(ofSize: 150), .foregroundColor: NSColor.white]
let subsize = sub.size(withAttributes: sattrs)
sub.draw(at: NSPoint(x: (size-subsize.width)/2, y: 90), withAttributes: sattrs)
img.unlockFocus()
let tiff = img.tiffRepresentation!
let png = NSBitmapImageRep(data: tiff)!.representation(using: .png, properties: [:])!
try! png.write(to: URL(fileURLWithPath: "icon-1024.png"))
print("icon png ok")
