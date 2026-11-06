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

    def lines(self):
        with self._lock:
            return list(self._lines)

    def start(self):
        threading.Thread(target=self._main, daemon=True).start()

    def stop(self, reason):
        with self._lock:
            self.stopped_reason = reason
            active = self._proc is not None
            pidf = self._pidf
        if not active:
            return
        end = time.time() + 2
        while time.time() < end:
            try:
                txt = Path(pidf).read_text().strip()
            except OSError:
                txt = ""
            if txt.isdigit():
                try:
                    os.kill(int(txt), signal.SIGTERM)
                except OSError:
                    pass
                return
            if self._proc is None:  # launch ended: pid file was truncated, nothing to signal
                return
            time.sleep(0.05)

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
            with self._lock:
                go = self.code == 0 and self.stopped_reason is None
            if go and Path(nextf).read_text() == "deliver":
                self._launch(d, mk, pidf, ["deliver", self.flow], None)
        finally:
            shutil.rmtree(d, ignore_errors=True)
            self.done = True

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
        while proc.poll() is None:
            self._pump(offs)
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
