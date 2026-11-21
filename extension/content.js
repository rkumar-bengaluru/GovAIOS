// Watches presses, typing, dropdown changes and checkbox ticks on this one tab. It reads only aria-label, innerText,
// placeholder, tagName, type, multiple and role; it never reads what was typed or chosen (GOV-AIOS reads that from the
// accessibility tree), and never clicks, types or submits.
if (!window.__govaiosTeach) {
  const SKIP = ["password", "hidden"];   // never reported, not even by name
  const TEXT = ["text", "search", "email", "tel", "url", "number"];
  const dirty = new Set();   // fields typed in since the last press
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim().slice(0, 200);
  const onInput = (e) => {
    if (!e.isTrusted) return;
    const el = e.target;
    if (el instanceof HTMLTextAreaElement || (el instanceof HTMLInputElement && TEXT.includes(el.type) && !SKIP.includes(el.type)) ||
        (el instanceof HTMLSelectElement && !el.multiple) || (el instanceof HTMLInputElement && el.type === "checkbox")) dirty.add(el);
  };
  // the press name rule: aria-label, else its label's text, else placeholder
  const fieldName = (el) => clean(el.getAttribute("aria-label") || (el.labels && el.labels[0] && el.labels[0].innerText) ||
    el.getAttribute("placeholder"));
  const onDown = (e) => {
    if (!e.isTrusted) return;   // a page's dispatchEvent cannot forge a press
    if (e.button !== 0) return;   // a right or middle press is not a click
    const t = e.target instanceof Element ? e.target : null;
    // the same climb the recorder makes, so the names match exactly
    const el = t && t.closest("a,button,[role=button],[role=tab],[role=link],[role=radio],summary");
    if (!el) return;
    const name = clean(el.getAttribute("aria-label") || el.innerText);
    // one message: a separate one could reach the panel after the press it came before
    const types = [...dirty].slice(0, 20).map(fieldName);
    dirty.clear();
    chrome.runtime.sendMessage({
      kind: "down", x: e.screenX, y: e.screenY, name, role: el.getAttribute("role") || "",
      tag: el.tagName.toLowerCase(), url: location.origin + location.pathname, t: Date.now(), types,
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
  document.addEventListener("input", onInput, true);
  window.__govaiosTeach = true;
  chrome.runtime.onMessage.addListener((m) => {
    if (!m.stop) return;
    document.removeEventListener("pointerdown", onDown, true);
    document.removeEventListener("input", onInput, true);
    host.remove();
    window.__govaiosTeach = false;
  });
}
