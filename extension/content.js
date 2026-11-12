// Watches presses on this one tab. It reads only aria-label, innerText, tagName and role; it never clicks, types or submits.
if (!window.__govaiosTeach) {
  const onDown = (e) => {
    if (!e.isTrusted) return;   // a page's dispatchEvent cannot forge a press
    const t = e.target instanceof Element ? e.target : null;
    // the same climb the recorder makes, so the names match exactly
    const el = t && t.closest("a,button,[role=button],[role=tab],[role=link],[role=radio],summary");
    if (!el) return;
    const name = (el.getAttribute("aria-label") || el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 200);
    chrome.runtime.sendMessage({
      kind: "down", x: e.screenX, y: e.screenY, name, role: el.getAttribute("role") || "",
      tag: el.tagName.toLowerCase(), url: location.origin + location.pathname, t: Date.now(),
    });
  };
  const host = document.createElement("div");
  const shadow = host.attachShadow({ mode: "closed" });   // the page cannot reach into it
  const sign = document.createElement("div");
  sign.textContent = "● Recording";
  sign.style.cssText = "position:fixed;top:8px;right:8px;z-index:2147483647;background:#c00;color:#fff;" +
    "font:bold 13px system-ui,sans-serif;padding:4px 10px;border-radius:4px;pointer-events:none";
  shadow.append(sign);
  document.documentElement.append(host);
  document.addEventListener("pointerdown", onDown, true);
  window.__govaiosTeach = true;
  chrome.runtime.onMessage.addListener((m) => {
    if (!m.stop) return;
    document.removeEventListener("pointerdown", onDown, true);
    host.remove();
    window.__govaiosTeach = false;
  });
}
