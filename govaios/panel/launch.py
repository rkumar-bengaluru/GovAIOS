"""Python port of bin/gov-aios launch(): run, then deliver when the app asks."""
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path


class RunLaunch:
    def __init__(self, flow_path, ticket, app="/Applications/gov-aios.app", open_cmd="open"):
        self.flow, self.ticket, self.app, self.open_cmd = str(Path(flow_path).resolve()), ticket, app, open_cmd
        self.done = False
        self.code = None
        self.summary = None
        self.stopped_reason = None
        self._lines = []
        self._lock = threading.Lock()
        self._proc = None
        self._pidf = None
        self._termed = None

    def lines(self):
        with self._lock:
            return list(self._lines)

    def start(self):
        threading.Thread(target=self._main, daemon=True).start()

    def stop(self, reason):
        with self._lock:
            if self.done:   # finished: a late stop is not a stop
                return
            self.stopped_reason = reason
            active = self._proc is not None
            pidf = self._pidf
        if not active:
            return
        end = time.time() + 2   # a slower start is signalled by _launch's poll loop
        while time.time() < end:
            if self._signal(pidf) or self._proc is None:  # launch ended: pid file was truncated, nothing to signal
                return
            time.sleep(0.05)

    def _signal(self, pidf):
        """SIGTERM the pid the app wrote, once (a 2nd can cut its stop entry); False while it has not written one."""
        try:
            txt = Path(pidf).read_text().strip()
        except OSError:
            txt = ""
        if not txt.isdigit():
            return False
        with self._lock:
            if self._termed == txt:
                return True
            self._termed = txt
        try:
            os.kill(int(txt), signal.SIGTERM)
        except OSError:
            pass
        return True

    def _main(self):
        d = tempfile.mkdtemp(prefix="govaios-run-")
        try:
            os.chmod(d, 0o700)
            def mk():
                fd, path = tempfile.mkstemp(dir=d)
                os.close(fd)
                return path
            self._pidf = pidf = mk()
            nextf = mk()
            self._launch(d, mk, pidf, ["run", self.flow], nextf)
            with self._lock:   # done is set with the last exit code, so stop() never sees a finished run as live
                go = self.code == 0 and self.stopped_reason is None and Path(nextf).read_text() == "deliver"
                self.done = not go
            if go:
                self._launch(d, mk, pidf, ["deliver", self.flow], None)
        finally:
            with self._lock:
                self.done = True
            shutil.rmtree(d, ignore_errors=True)

    def _launch(self, d, mk, pidf, args, nextf):
        out, err, exitf = mk(), mk(), mk()
        Path(pidf).write_text("")
        cmd = [self.open_cmd, "-W", "-n", "-a", self.app, "--stdout", out, "--stderr", err,
               "--env", f"GOVAIOS_EXIT_FILE={exitf}", "--env", f"GOVAIOS_PID_FILE={pidf}"]
        if nextf:
            cmd += ["--env", f"GOVAIOS_NEXT_FILE={nextf}", "--env", f"GOVAIOS_RUN_TICKET={self.ticket}"]
        with self._lock:
            if self.stopped_reason is not None:
                return
            try:
                proc = self._proc = subprocess.Popen(cmd + ["--args", *args])
            except OSError as e:
                self._lines.append(f"launch failed: {type(e).__name__}")
                self.code = 70
                return
        offs = {out: 0, err: 0}
        killed = False
        while proc.poll() is None:
            self._pump(offs)
            if not killed and self.stopped_reason is not None:
                killed = self._signal(pidf)   # stopped before the app wrote its pid
            time.sleep(0.05)
        self._pump(offs)  # app has exited: one last pass is complete
        try:
            txt = Path(exitf).read_text().strip()
        except OSError:
            txt = ""
        Path(pidf).write_text("")  # a late signal must not hit a recycled pid
        with self._lock:
            self._proc = None
            self.code = int(txt) if txt.lstrip("-").isdigit() else 70
            self.done = self.done or nextf is None   # deliver is the last launch

    def _pump(self, offs):
        for f in offs:
            data = Path(f).read_bytes()[offs[f]:]
            offs[f] += len(data)
            # shortcut: assumes writes end on line boundaries, as the app's do
            for ln in data.decode(errors="replace").splitlines():
                with self._lock:
                    self._lines.append(ln)
                    if ln.startswith("deliver joblens:"):
                        self.summary = ln
