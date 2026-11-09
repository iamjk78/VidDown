// Převede design/build/*.html (1440x960) do jednoho PDF pomocí WebKitu z macOS.
// Použití: swift design/render_pdf.swift <složka s html> <výstup.pdf> [složka pro PNG náhledy]
import AppKit
import PDFKit
import WebKit

let args = CommandLine.arguments
guard args.count >= 3 else { print("usage: render_pdf.swift <dir> <out.pdf> [pngdir]"); exit(2) }
let dir = URL(fileURLWithPath: args[1])
let out = URL(fileURLWithPath: args[2])
let pngDir: URL? = args.count > 3 ? URL(fileURLWithPath: args[3]) : nil
let files = try! FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)
    .filter { $0.pathExtension == "html" }.sorted { $0.lastPathComponent < $1.lastPathComponent }

let W: CGFloat = 1440, H: CGFloat = 960
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)

final class Renderer: NSObject, WKNavigationDelegate {
    let web = WKWebView(frame: NSRect(x: 0, y: 0, width: W, height: H))
    var queue: [URL]
    let doc = PDFDocument()
    init(_ q: [URL]) { queue = q; super.init(); web.navigationDelegate = self }
    func next() {
        guard !queue.isEmpty else { finish(); return }
        let f = queue.removeFirst()
        web.loadFileURL(f, allowingReadAccessTo: f.deletingLastPathComponent())
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            let cfg = WKPDFConfiguration(); cfg.rect = CGRect(x: 0, y: 0, width: W, height: H)
            webView.createPDF(configuration: cfg) { result in
                if case .success(let data) = result, let p = PDFDocument(data: data), let page = p.page(at: 0) {
                    self.doc.insert(page, at: self.doc.pageCount)
                } else { print("chyba renderu:", result) }
                self.next()
            }
        }
    }
    func finish() {
        doc.write(to: out)
        if let pngDir = pngDir {
            try? FileManager.default.createDirectory(at: pngDir, withIntermediateDirectories: true)
            for i in 0..<doc.pageCount {
                let img = doc.page(at: i)!.thumbnail(of: NSSize(width: 1440, height: 960), for: .mediaBox)
                if let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                   let png = rep.representation(using: .png, properties: [:]) {
                    try? png.write(to: pngDir.appendingPathComponent(String(format: "page_%02d.png", i + 1)))
                }
            }
        }
        print("PDF: \(out.path) (\(doc.pageCount) stran)")
        exit(0)
    }
}

let r = Renderer(files)
r.next()
app.run()
