"""Row 23 probe: open a Chrome profile window via LaunchServices from inside the run sandbox.

Usage (admin, Chrome already running in another profile):
  python probe_chrome.py ["Profile 2"] [https://example.com]
Applies RUN_PROFILE (row 22) first (as `run` will), then `open -n -a "Google Chrome" --args ...`.
Prints only process counts, parent pids and exit codes; the admin confirms by eye that the window
opened in the same Chrome (one dock icon) and that the page loaded.
"""
import subprocess
import sys
import time

from probe_sandbox import RUN_PROFILE, sandbox_init


def chrome_mains():
    """(pid, ppid) of main Chrome processes (helpers have other names)."""
    out = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,comm="], capture_output=True, text=True).stdout
    return [tuple(map(int, line.split()[:2])) for line in out.splitlines()
            if line.rstrip().endswith("/Google Chrome.app/Contents/MacOS/Google Chrome")]


def main(argv):
    profile = argv[0] if argv else "Profile 2"
    url = argv[1] if len(argv) > 1 else "https://example.com"
    print(f"before: chrome main processes={chrome_mains()}")
    sandbox_init(RUN_PROFILE)
    print("sandbox_init applied (RUN_PROFILE, row 22)")
    r = subprocess.run(["/usr/bin/open", "-n", "-a", "Google Chrome", "--args",
                        f"--profile-directory={profile}", url], capture_output=True, text=True)
    print(f"open exit={r.returncode} stderr={r.stderr.strip()!r}")
    time.sleep(2)
    mains = chrome_mains()
    print(f"after 2 s: chrome main processes={mains}")
    time.sleep(8)
    mains = chrome_mains()
    print(f"after 10 s: chrome main processes={mains} (expect one, ppid 1 = launchd, not us)")
    return 0 if r.returncode == 0 and len(mains) == 1 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
