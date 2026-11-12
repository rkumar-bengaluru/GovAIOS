const $ = (id) => document.getElementById(id);
const send = (m) => chrome.runtime.sendMessage(m);
const call = (method, path, body) => send({ call: [method, path, body] });
const show = (id, on) => { $(id).hidden = !on; };
let lost = false;   // the Teach run never showed up
let s = null;   // the last /ext/state

async function poll() {
  const r = await call("POST", "/ext/state");
  const paired = r.paired && r.status !== 401;
  show("pair", !paired);
  show("main", paired);
  if (!paired) { if (r.status === 0) $("note").textContent = r.json.note; return; }   // keep "That code did not work."
  s = r.json;
  const y = await send({ sync: true, recording: !!s.recording });
  if (y.timeout) lost = true;
  const rec = !!s.recording, open = !rec && !!s.lesson;
  $("note").textContent = !s.signed_in ? "Sign in to the panel (type your code on Home) to record." : lost ? "The Teach run did not start. Check Home." : y.starting ? "Starting…" : s.note || "";
  show("teach", !rec && !open); show("pause", rec && !s.paused); show("resume", rec && s.paused);
  show("done", rec); show("cancel", rec); show("discard", open);
  $("teach").disabled = !s.signed_in;
  if (open) { show("teach", true); $("teach").textContent = "Resume"; } else $("teach").textContent = "Teach";
  $("steps").replaceChildren(...(s.lines || []).map((l) => Object.assign(document.createElement("li"), { textContent: l })));
  $("yaml").textContent = s.yaml || "";
}

const act = (id, fn) => $(id).addEventListener("click", async () => {
  const r = await fn();
  if (r && r.json && r.json.note) $("note").textContent = r.json.note;
  poll();
});
const ev = (kind) => () => send({ event: { kind, t: Date.now() } });

act("connect", async () => {
  const r = await call("POST", "/ext/pair", { code: $("code").value.trim() });
  if (r.status === 200 && r.json.token) await chrome.storage.local.set({ token: r.json.token });
  else r.json.note = r.status === 0 ? "The panel is not reachable at 127.0.0.1:8765." : "That code did not work.";
  return r;
});
act("teach", () => { lost = false; return send({ teach: true }); });
act("pause", ev("pause"));
act("resume", ev("resume"));
act("cancel", ev("cancel"));
act("discard", () => call("POST", "/ext/discard"));
act("done", async () => { show("ask", true); $("appname").focus(); });
act("make", async () => {
  const name = $("appname").value.trim();
  if (!name) return { json: { note: "Type a name for the app." } };
  if (s && s.recording) {   // a retry after /ext/done refused: the run has already ended
    const d = await send({ event: { kind: "done", t: Date.now() } });
    if (d.status !== 200) return d;
  }
  for (let i = 0; i < 40; i++) {   // the recorder writes the lesson, then ends the run
    const st = await call("POST", "/ext/state");
    if (!st.json.recording) break;
    await new Promise((ok) => setTimeout(ok, 500));
  }
  const r = await call("POST", "/ext/done", { name });
  if (r.status === 200) { show("ask", false); chrome.tabs.create({ url: "http://127.0.0.1:8765" + r.json.lesson_url }); }
  return r;
});
for (const [t, other] of [["steps", "yaml"], ["yaml", "steps"]]) $("t-" + t).addEventListener("click", () => {
  show(t, true); show(other, false);
  $("t-" + t).setAttribute("aria-pressed", "true"); $("t-" + other).setAttribute("aria-pressed", "false");
});

poll();
setInterval(poll, 500);   // the panel is only alive while open
