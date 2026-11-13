const PANEL = "http://127.0.0.1:8765";
chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });   // keeps the token from content scripts
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

const get = (k) => chrome.storage.local.get(k).then((o) => o[k]);
const inject = (tabId) => chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] }).catch(() => {});

async function api(method, path, body) {
  const token = await get("token");
  const headers = { "Content-Type": "application/json" };
  if (token) headers["X-GovAIOS-Token"] = token;
  try {
    const r = await fetch(PANEL + path, { method, headers, body: method === "POST" ? JSON.stringify(body || {}) : undefined });
    if (r.status === 401) await chrome.storage.local.remove("token");   // Disconnected in Studio; a locked screen's 403 keeps it
    return { status: r.status, json: await r.json().catch(() => ({})), paired: !!(await get("token")) };
  } catch (e) {
    return { status: 0, json: { note: "Cannot reach the panel at 127.0.0.1:8765." }, paired: !!token };
  }
}

async function stop() {
  const tabId = await get("tab");
  await chrome.storage.local.remove(["tab", "paused", "seen", "started"]);
  if (tabId != null) chrome.tabs.sendMessage(tabId, { stop: true }).catch(() => {});
}

// The side panel's requests: {call: [method, path, body]}, {teach: true}, {event: body}
chrome.runtime.onMessage.addListener((m, sender, reply) => {
  if (sender.tab) {   // a page's content.js: only its press reports, only from the teach tab, never while paused
    const u = new URL(sender.url);
    if (["localhost", "127.0.0.1"].includes(u.hostname) && u.port === "8765") return;   // never the panel's own pages
    if (m.kind === "down") Promise.all([get("tab"), get("paused")]).then(([tab, paused]) => {
      if (sender.tab.id === tab && !paused) api("POST", "/ext/event", m);
    });
    return;
  }
  (async () => {
    if (m.sync) {   // each poll's recording flag; the run takes seconds to start, so stop only once it was seen live
      if (await get("tab") == null) return {};
      if (m.recording) {   // the run is live: only now show the sign and send presses
        if (!(await get("seen"))) { await chrome.storage.local.set({ seen: true }); await inject(await get("tab")); }
        return {};
      }
      if (await get("seen")) { await stop(); return {}; }
      if (Date.now() - (await get("started")) > 30000) { await stop(); return { timeout: true }; }
      return { starting: true };
    }
    if (m.teach) {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab) return { status: 0, json: { note: "No tab to teach on." } };
      const r = await api("POST", "/ext/teach", { tab_url: tab.url || "" });
      if (r.status === 200) await chrome.storage.local.set({ tab: tab.id, paused: false, seen: false, started: Date.now() });
      return r;
    }
    if (m.event) {
      const r = await api("POST", "/ext/event", m.event);
      if (r.status === 200 && ["pause", "resume"].includes(m.event.kind)) await chrome.storage.local.set({ paused: m.event.kind === "pause" });
      if (r.status === 200 && ["done", "cancel"].includes(m.event.kind)) await stop();
      return r;
    }
    return api(m.call[0], m.call[1], m.call[2]);
  })().then(reply);
  return true;
});

chrome.tabs.onUpdated.addListener(async (tabId, info) => {
  if (info.status === "complete" && tabId === (await get("tab")) && (await get("seen"))) inject(tabId);
});
