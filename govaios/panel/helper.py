"""Launch helper: forked before the sandbox (a sandboxed process cannot `open -a` the app or `say`).
The child is the only unsandboxed part of the panel: no socket, no PyObjC, and it runs nothing but RunLaunch's
fixed argv and `say --`, for requests it validates itself."""
import json
import os
import re
import signal
import subprocess
import threading
import time

from govaios.panel.launch import RunLaunch

_HEX64 = re.compile(r"[0-9a-f]{64}")
SAY_MAX = 300


def start_helper(flows_dir, home, open_cmd="open", say_cmd="/usr/bin/say"):
    """Fork now: before the sandbox and before any thread. open_cmd/say_cmd are test overrides."""
    cmd_r, cmd_w = os.pipe()
    evt_r, evt_w = os.pipe()
    pid = os.fork()
    if pid == 0:
        code = 0
        try:
            os.close(cmd_w), os.close(evt_r)
            _child(cmd_r, evt_w, os.path.realpath(flows_dir), str(home), open_cmd, say_cmd)
        except BaseException:
            code = 70
        finally:
            os._exit(code)   # never return into the parent's code (or pytest)
    os.close(cmd_r), os.close(evt_w)
    return Helper(pid, cmd_w, evt_r)


def _child(cmd_r, evt_w, root, home, open_cmd, say_cmd):
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
                if real is None or live():
                    send({"id": n, "done": True, "code": 70, "error": "refused"})
                    continue
                run = RunLaunch(real, m["ticket"], open_cmd=open_cmd)
                cur.update(id=n, run=run)
                run.start()
                threading.Thread(target=watch, args=(n, run), daemon=True).start()
            elif op == "stop" and isinstance(m.get("reason"), str) and cur.get("id") == n and live():
                threading.Thread(target=cur["run"].stop, args=(m["reason"],), daemon=True).start()
    finally:
        if live():   # pipe closed, parent died, or we failed: end its run before os._exit
            run = cur["run"]
            run.stop("session ended")
            end = time.time() + 10
            while not run.done and time.time() < end:
                time.sleep(0.05)


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

    def run(self, flow_path, ticket):
        with self._lock:
            self._n += 1
            r = self._runs[self._n] = HelperRun(self, self._n, flow_path, ticket)
        return r

    def say(self, text):
        self._send({"op": "say", "text": text})

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

    def __init__(self, helper, n, flow_path, ticket):
        self._helper, self._n, self.flow, self.ticket = helper, n, str(flow_path), ticket
        self.done, self.code, self.summary, self.stopped_reason, self.error = False, None, None, None, None
        self._lines, self._lock = [], threading.Lock()

    def lines(self):
        with self._lock:
            return list(self._lines)

    def start(self):
        self._helper._send({"op": "run", "id": self._n, "flow": self.flow, "ticket": self.ticket})

    def stop(self, reason):
        if not self.done:
            self._helper._send({"op": "stop", "id": self._n, "reason": reason})
