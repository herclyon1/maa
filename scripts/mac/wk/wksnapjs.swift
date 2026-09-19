// wksnapjs <url> <out.png> <w> <h> <scale> <light|dark> <js-file> <delay-s> [<js2-file> <delay2>]: load, wait 2.5 s, eval js, wait delay, snapshot, then print the result of js2 (after delay2) if given
import Cocoa
import WebKit
let a = CommandLine.arguments
let url = URL(string: a[1])!, out = a[2], w = Double(a[3])!, h = Double(a[4])!, scale = Double(a[5])!, dark = a[6] == "dark"
let js = try! String(contentsOfFile: a[7], encoding: .utf8), delay = Double(a[8])!
let js2 = a.count > 9 ? try! String(contentsOfFile: a[9], encoding: .utf8) : "", delay2 = a.count > 10 ? Double(a[10])! : 0
let app = NSApplication.shared; app.setActivationPolicy(.prohibited)
let win = NSWindow(contentRect: NSRect(x: 0, y: 0, width: w, height: h), styleMask: [.borderless], backing: .buffered, defer: false)
win.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
let cfg = WKWebViewConfiguration(); cfg.websiteDataStore = .nonPersistent()
let web = WKWebView(frame: NSRect(x: 0, y: 0, width: w, height: h), configuration: cfg)
win.contentView = web
class D: NSObject, WKNavigationDelegate {
  func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
    DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
      webView.evaluateJavaScript(js) { v, e in if let e = e { print("js error", e) }
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
          let c = WKSnapshotConfiguration(); c.snapshotWidth = NSNumber(value: w * scale)
          webView.takeSnapshot(with: c) { img, err in
            if let img = img, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff), let png = rep.representation(using: .png, properties: [:]) {
              try! png.write(to: URL(fileURLWithPath: out)); print("wrote", out, rep.pixelsWide, rep.pixelsHigh)
            } else { print("snapshot failed", err as Any) }
            if js2.isEmpty { exit(0) }
            DispatchQueue.main.asyncAfter(deadline: .now() + delay2) { webView.evaluateJavaScript(js2) { v, e in if let e = e { print("js2 error", e) } else { print(v as Any) }; exit(0) } }
          }
        }
      }
    }
  }
  func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { print("nav failed", error); exit(1) }
}
let d = D(); web.navigationDelegate = d
web.load(URLRequest(url: url))
DispatchQueue.main.asyncAfter(deadline: .now() + 40) { print("timeout"); exit(2) }
app.run()
