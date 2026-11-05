// Dump the macOS accessibility tree of Chrome's front window web area.
// usage: swift axdump.swift [maxDepth]
import ApplicationServices
import AppKit

guard AXIsProcessTrusted() else {
    print("NOT TRUSTED: grant Accessibility to this terminal app in System Settings > Privacy & Security > Accessibility"); exit(2)
}
guard let chrome = NSRunningApplication.runningApplications(withBundleIdentifier: "com.google.Chrome").first else {
    print("Chrome not running"); exit(1)
}
let app = AXUIElementCreateApplication(chrome.processIdentifier)
// README §7 Chrome note: turn on renderer accessibility.
AXUIElementSetAttributeValue(app, "AXEnhancedUserInterface" as CFString, kCFBooleanTrue)
AXUIElementSetAttributeValue(app, "AXManualAccessibility" as CFString, kCFBooleanTrue)
Thread.sleep(forTimeInterval: 2)

func attr(_ e: AXUIElement, _ a: String) -> AnyObject? {
    var v: AnyObject?
    return AXUIElementCopyAttributeValue(e, a as CFString, &v) == .success ? v : nil
}
func str(_ e: AXUIElement, _ a: String) -> String? {
    guard let s = attr(e, a) as? String, !s.isEmpty else { return nil }
    return s.replacingOccurrences(of: "\n", with: " ")
}
func children(_ e: AXUIElement) -> [AXUIElement] { attr(e, "AXChildren") as? [AXUIElement] ?? [] }

let maxDepth = Int(CommandLine.arguments.dropFirst().first ?? "") ?? 80
var count = 0
func dump(_ e: AXUIElement, _ d: Int) {
    count += 1
    guard d <= maxDepth, count < 30000 else { return }
    let role = str(e, "AXRole") ?? "?"
    let sub = str(e, "AXSubrole").map { "/\($0)" } ?? ""
    var parts = ["\(String(repeating: "  ", count: d))\(role)\(sub)"]
    if let t = str(e, "AXTitle") { parts.append("title=\"\(t.prefix(100))\"") }
    if let t = str(e, "AXDescription") { parts.append("desc=\"\(t.prefix(100))\"") }
    if let t = str(e, "AXValue") { parts.append("value=\"\(t.prefix(100))\"") }
    if let t = str(e, "AXDOMIdentifier") { parts.append("#\(t)") }
    print(parts.joined(separator: " "))
    for c in children(e) { dump(c, d + 1) }
}
func findWebArea(_ e: AXUIElement, _ d: Int = 0) -> AXUIElement? {
    if str(e, "AXRole") == "AXWebArea" { return e }
    if d > 25 { return nil }
    for c in children(e) { if let w = findWebArea(c, d + 1) { return w } }
    return nil
}

guard let win = attr(app, "AXFocusedWindow").map({ $0 as! AXUIElement }) else { print("no focused window"); exit(1) }
print("WINDOW:", str(win, "AXTitle") ?? "?")
guard let web = findWebArea(win) else { print("no AXWebArea found (renderer accessibility off?)"); exit(1) }
dump(web, 0)
print("NODES:", count)
