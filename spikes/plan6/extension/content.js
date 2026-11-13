// Spike: report each mouse-down (and -up) on JobLens to the spike script, before the page reacts.
// Sends the clicked element's tag, role and visible name only: never a field's value.
const CLICKABLE = "a,button,[role=button],[role=tab],[role=link],summary";
const name = (el) => (el.getAttribute("aria-label") || el.innerText || "").trim().replace(/\s+/g, " ").slice(0, 100);
addEventListener("pointerdown", (e) => {
  const el = e.target instanceof Element ? e.target.closest(CLICKABLE) : null;
  chrome.runtime.sendMessage({ kind: "down", t: Date.now(), x: e.screenX, y: e.screenY,
    tag: el ? el.tagName.toLowerCase() : "", role: el ? el.getAttribute("role") || "" : "", name: el ? name(el) : "" });
}, true);
addEventListener("pointerup", () => chrome.runtime.sendMessage({ kind: "up", t: Date.now() }), true);
