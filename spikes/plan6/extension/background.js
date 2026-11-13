chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
// Spike: forward the page's mouse reports to the spike script on this Mac only.
chrome.runtime.onMessage.addListener((m, sender) => {
  if (!sender.tab) return;
  fetch("http://127.0.0.1:8799/ev", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(m) }).catch(() => {});
});
