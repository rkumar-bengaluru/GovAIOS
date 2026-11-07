"""Launch helper: forked before the sandbox (a sandboxed process cannot `open -a` the app or `say`).
The child is the only unsandboxed part of the panel: no socket, no PyObjC, and it runs nothing but RunLaunch's
fixed argv, `say --`, ROOT_SCRIPT under macOS's administrator dialog and `open -a Terminal` on a coding agent's launch file, for requests it validates itself."""
import json
import os
import re
import shlex
import signal
import subprocess
import threading
import time

from govaios.panel.launch import RunLaunch

_HEX64 = re.compile(r"[0-9a-f]{64}")
SAY_MAX = 300
# agent id -> (folder, file name, staged copy under the data home) = agents.AGENTS[id] .managed / .staged
TARGETS = {"claude_code": ("/Library/Application Support/ClaudeCode", "managed-settings.json",
                           "executors/managed-settings.json"),
           "codex": ("/etc/codex", "requirements.toml", "executors/codex-requirements.toml")}
# Run as root by the macOS administrator dialog: fixed text, arguments only from the helper itself. The copy is
# checked against the digest the admin approved in the panel, so a file swapped after approval is never installed.
ROOT_SCRIPT = r"""set -eu
PATH=/usr/bin:/bin:/usr/sbin:/sbin
act=$1 src=$2 want=$3 dir=$4 own=$5 name=$6
dst="$dir/$name"
if [ "$act" = remove ]; then rm -f "$dst"; exit 0; fi
mkdir -p "$dir"
tmp=$(mktemp "$dir/.gov-aios.XXXXXX")
trap 'rm -f "$tmp"' EXIT
cat < "$src" > "$tmp"
[ "$(shasum -a 256 "$tmp" | cut -d' ' -f1)" = "$want" ] || exit 3
chown "$own" "$tmp"
chmod 0644 "$tmp"
mv -f "$tmp" "$dst"
trap - EXIT
"""
PROMPT = "GOV-AIOS wants to {} the {} settings that put it under GOV-AIOS checks."
TITLES = {"claude_code": "Claude Code", "codex": "OpenAI Codex"}


def start_helper(flows_dir, home, open_cmd="open", say_cmd="/usr/bin/say", elevate=None, ms_dir=None,
                 owner="root:wheel"):
    """Fork now: before the sandbox and before any thread. open_cmd/say_cmd/elevate/ms_dir/owner are test overrides
    (ms_dir: one folder for every agent's file)."""
    cmd_r, cmd_w = os.pipe()
    evt_r, evt_w = os.pipe()
    pid = os.fork()
    if pid == 0:
        code = 0
        try:
            os.close(cmd_w), os.close(evt_r)
            _child(cmd_r, evt_w, os.path.realpath(flows_dir), str(home), open_cmd, say_cmd,
                   (elevate or _osascript, ms_dir, owner))
        except BaseException:
            code = 70
        finally:
            os._exit(code)   # never return into the parent's code (or pytest)
    os.close(cmd_r), os.close(evt_w)
    return Helper(pid, cmd_w, evt_r)


def _child(cmd_r, evt_w, root, home, open_cmd, say_cmd, admin):
    # Ctrl-C reaches the group; the pipe is our only way to end. A no-op handler, not SIG_IGN: exec resets a
    # handler to default, but SIG_IGN would be inherited by `open` and what it runs.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: None)
    out, out_lock = os.fdopen(evt_w, "w"), threading.Lock()
    cur = {}   # "id", "run": the one run

    def send(ev):
        with out_lock:
            try:
                out.write(json.dumps(ev) + "\n")
                out.flush()
            except (OSError, ValueError):
                pass   # the parent is gone; the pipe close ends us

    def watch(n, run):
        sent = 0
        while True:
            done = run.done   # read before the lines: once done, the lines are complete
            ls = run.lines()
            for ln in ls[sent:]:
                send({"id": n, "line": ln})
            sent = len(ls)
            if done:
                send({"id": n, "done": True, "code": run.code, "summary": run.summary,
                      "stopped_reason": run.stopped_reason})
                return
            time.sleep(0.05)

    def allowed(flow, ticket):
        if not (isinstance(flow, str) and isinstance(ticket, str) and _HEX64.fullmatch(ticket)):
            return None
        real = os.path.realpath(flow)
        ok = (os.path.dirname(real) == root and real.endswith(".yaml") and os.path.isfile(real)
              and os.path.isfile(os.path.join(home, "tickets", ticket)))   # only a ticket the panel made
        return real if ok else None

    def live():
        return "run" in cur and not cur["run"].done

    def claude(n, act, digest, agent):
        elevate, ms_dir, owner = admin
        folder, name, staged = TARGETS[agent]
        argv = ["/bin/sh", "-c", ROOT_SCRIPT, "sh", act, os.path.join(home, staged), digest, ms_dir or folder, owner,
                name]
        try:
            code = elevate(argv, PROMPT.format(act, TITLES[agent]))
        except Exception:
            code = 1
        send({"id": n, "done": True, "code": code})

    busy = threading.Lock()   # one administrator dialog at a time

    def claude_start(n, folder, agent):
        """Terminal opens `folder` and runs the agent: only an existing folder inside its approved policy's."""
        from govaios import agents
        try:
            a = agents.AGENTS[agent]
            real = agents.inside(folder, agents.load(home, a)[0].get("project_roots", []))
            command = agents.found(a)
            if real is None or command is None:
                code = 70
            else:
                f = agents.launch_file(home, real, command, a)
                code = subprocess.run([open_cmd, "-a", "Terminal", str(f)], timeout=30).returncode
        except Exception:
            code = 1
        send({"id": n, "done": True, "code": code})

    try:
        for raw in os.fdopen(cmd_r, "r"):   # trusted channel (both ends ours): lines are not capped
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(m, dict):
                continue
            op, n = m.get("op"), m.get("id")
            if op == "say" and isinstance(m.get("text"), str):
                args = [say_cmd, "--", m["text"][:SAY_MAX]]
                threading.Thread(target=_quiet_run, args=(args,), daemon=True).start()   # say blocks; stops must not wait
            elif type(n) is not int:
                continue
            elif op == "run":
                real = allowed(m.get("flow"), m.get("ticket"))
                ins = m.get("inputs")
                if ins is not None and not (isinstance(ins, dict) and len(ins) <= 4 and all(
                        isinstance(k, str) and isinstance(v, str) and len(v) <= 500 for k, v in ins.items())):
                    real = None
                if real is None or live():
                    send({"id": n, "done": True, "code": 70, "error": "refused"})
                    continue
                run = RunLaunch(real, m["ticket"], open_cmd=open_cmd, inputs=ins)
                cur.update(id=n, run=run)
                run.start()
                threading.Thread(target=watch, args=(n, run), daemon=True).start()
            elif op in ("claude_start", "claude") and m.get("agent", "claude_code") not in TARGETS:
                send({"id": n, "done": True, "code": 70, "error": "refused"})
            elif op == "claude_start" and isinstance(m.get("folder"), str):
                threading.Thread(target=claude_start, args=(n, m["folder"], m.get("agent", "claude_code")),
                                 daemon=True).start()
            elif op == "claude":
                act, digest, agent = m.get("action"), m.get("digest", ""), m.get("agent", "claude_code")
                ok = act == "remove" or (act == "install" and isinstance(digest, str) and _HEX64.fullmatch(digest))
                if not ok or not busy.acquire(blocking=False):
                    send({"id": n, "done": True, "code": 70, "error": "refused"})
                    continue
                def go(n=n, act=act, digest=digest, agent=agent):
                    try:
                        claude(n, act, digest if act == "install" else "", agent)
                    finally:
                        busy.release()
                threading.Thread(target=go, daemon=True).start()
            elif op == "stop" and isinstance(m.get("reason"), str) and cur.get("id") == n and live():
                threading.Thread(target=cur["run"].stop, args=(m["reason"],), daemon=True).start()
    finally:
        if live():   # pipe closed, parent died, or we failed: end its run before os._exit
            run = cur["run"]
            run.stop("session ended")
            end = time.time() + 10
            while not run.done and time.time() < end:
                time.sleep(0.05)


def _osascript(argv, prompt):
    """macOS's own administrator dialog runs argv as root. 0 done, 2 cancelled by the admin, else failed."""
    cmd = " ".join(shlex.quote(a) for a in argv)
    script = ["-e", "on run a", "-e", "do shell script (item 1 of a) with prompt (item 2 of a) with administrator privileges",
              "-e", "end run"]
    try:
        r = subprocess.run(["/usr/bin/osascript", *script, cmd, prompt], capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return 1
    return 0 if r.returncode == 0 else 2 if "-128" in r.stderr else 1


def _quiet_run(args):
    try:
        subprocess.run(args, timeout=60)
    except Exception:
        pass   # a missing voice must not break the panel


class Helper:
    def __init__(self, pid, cmd_w, evt_r):
        self.pid, self.exited = pid, False
        self._w, self._lock, self._runs, self._n = os.fdopen(cmd_w, "w"), threading.Lock(), {}, 0
        threading.Thread(target=self._read, args=(evt_r,), daemon=True).start()

    def run(self, flow_path, ticket, inputs=None):
        with self._lock:
            self._n += 1
            r = self._runs[self._n] = HelperRun(self, self._n, flow_path, ticket, inputs)
        return r

    def say(self, text):
        self._send({"op": "say", "text": text})

    def claude_start(self, folder, agent="claude_code", wait_s=40):
        """Open Terminal in `folder` running the agent. 0 started, 70 refused, else failed."""
        return self._call({"op": "claude_start", "folder": folder, "agent": agent}, wait_s)

    def _call(self, msg, wait_s):
        with self._lock:
            self._n += 1
            r = self._runs[self._n] = HelperRun(self, self._n, "", "")
        self._send({**msg, "id": r._n})
        end = time.time() + wait_s
        while not r.done and time.time() < end:
            time.sleep(0.05)
        return r.code if r.done else 1

    def claude(self, action, digest="", agent="claude_code", wait_s=660):
        """Install or remove an agent's root-owned settings through the administrator dialog; blocks until done.
        0 done, 2 cancelled, else failed or refused."""
        return self._call({"op": "claude", "action": action, "digest": digest, "agent": agent}, wait_s)

    def close(self, wait_s=15):
        """Closing the pipe ends the child (it stops a live run first); waits for it, bounded."""
        with self._lock:
            try:
                self._w.close()
            except OSError:
                pass
        end = time.time() + wait_s
        while not self.exited and time.time() < end:
            try:
                self.exited = os.waitpid(self.pid, os.WNOHANG)[0] != 0
            except ChildProcessError:
                self.exited = True
            if not self.exited:
                time.sleep(0.05)

    def _send(self, msg):
        with self._lock:
            try:
                self._w.write(json.dumps(msg) + "\n")
                self._w.flush()
            except (OSError, ValueError):
                pass   # child gone: the reader marks its runs done

    def _read(self, evt_r):
        for raw in os.fdopen(evt_r, "r"):   # trusted channel (both ends ours): lines are not capped
            try:
                ev = json.loads(raw)
                r = self._runs.get(ev["id"])
            except (ValueError, KeyError, TypeError):
                continue
            if r is None:
                continue
            with r._lock:
                if "line" in ev:
                    r._lines.append(str(ev["line"]))
                elif ev.get("done"):
                    r.code, r.summary = ev.get("code"), ev.get("summary")
                    r.stopped_reason, r.error = ev.get("stopped_reason"), ev.get("error")
                    r.done = True
        for r in list(self._runs.values()):   # child exited: nothing will finish these
            with r._lock:
                if not r.done:
                    r.code, r.done = 70, True


class HelperRun:
    """What the panel uses of RunLaunch; state is filled by the Helper's reader thread."""

    def __init__(self, helper, n, flow_path, ticket, inputs=None):
        self._helper, self._n, self.flow, self.ticket, self.inputs = helper, n, str(flow_path), ticket, inputs
        self.done, self.code, self.summary, self.stopped_reason, self.error = False, None, None, None, None
        self._lines, self._lock = [], threading.Lock()

    def lines(self):
        with self._lock:
            return list(self._lines)

    def start(self):
        self._helper._send({"op": "run", "id": self._n, "flow": self.flow, "ticket": self.ticket, "inputs": self.inputs})

    def stop(self, reason):
        if not self.done:
            self._helper._send({"op": "stop", "id": self._n, "reason": reason})
