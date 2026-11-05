# Plan 2 spike: admin runbook

Probes that need the admin: Touch ID, the lock screen, key presses, the
admin's Chrome, a TCC grant, or sudo. Run each from Terminal in the repo root
(`cd ~/Documents/2026/rkumar-bengaluru/GovAIOS`). Terminal has no
Accessibility or Screen Recording grant and must not get one.

**Paste back** only the probe's printed lines plus the one-line observations
asked for. The probes never print window titles, page content or user names;
do not add any.

One-time setup (already done on this Mac by the spike):
`.venv/bin/pip install pyobjc-framework-LocalAuthentication`.

## 1. Touch ID prompts (rows 4, 6): `probe_auth.py`

For each case below run the commands in order. `prompt` waits up to 120 s;
`abandon` takes about 70 s.

Cases:
- **A. Lid open, Touch ID available** (normal).
- **B. Lid closed, external display and keyboard** (no Touch ID reachable).
- **C. Biometric lockout**: in case A, run `prompt` and touch with a finger
  that is *not* enrolled until the sheet stops accepting it (5 tries), let it
  fail; then run the plain command again.

Commands per case:

1. `.venv/bin/python spikes/plan2/probe_auth.py`
   (no prompt; prints `canEvaluatePolicy` for both policies and the row-6 choice)
2. `.venv/bin/python spikes/plan2/probe_auth.py prompt`
   Admin: touch the sensor (case A), or enter the password / use Watch if a
   password sheet appears (cases B, C).
3. `.venv/bin/python spikes/plan2/probe_auth.py prompt` again, admin presses
   **Cancel**.
4. `.venv/bin/python spikes/plan2/probe_auth.py abandon`
   Admin: do **not** touch or click; leave the sheet for 60 s.

Paste back per case: all printed lines, plus one line each:
- which sheet appeared (Touch ID sheet / password sheet / Watch / none),
- the reason text exactly as shown on the sheet (expect it to contain
  `approve: test run`; say if it is truncated or prefixed),
- whether an "Enter Password" / fallback button was visible on the Touch ID
  sheet (row 6 hides it),
- for `abandon`: did the sheet close by itself after `invalidate()`, and the
  `after invalidate:` line (reply arrived with which error code, or NEVER).

## 2. Lock screen (row 8): `probe_lock.py`

`.venv/bin/python spikes/plan2/probe_lock.py 60`

While it runs (60 s): wait 5 s; lock the screen (ctrl+cmd+Q), wait 5 s,
unlock; wait 5 s; switch to another user via fast user switching (control
centre user menu or login window), wait 5 s, switch back. Skip the user switch
if there is no second account, and say so.

Paste back: all printed lines, plus when (seconds) you locked, unlocked,
switched away and back. Expect `locked=True` throughout each locked or
switched-away period, `locked=False` otherwise.

## 3. Emergency-stop hotkey (row 10): `probe_hotkey.py`

`.venv/bin/python spikes/plan2/probe_hotkey.py 120`

It must print `RegisterEventHotKey status=0`. Then, within 120 s, press
**ctrl+option+cmd+.** once in each situation:

1. Chrome frontmost (any window).
2. Terminal frontmost.
3. A password field has focus (secure input): e.g. the Terminal running
   `sudo -k; sudo true` at its `Password:` prompt (press the hotkey, then
   ctrl+C the sudo), or a password field in Chrome.

Paste back: all printed lines (`FIRED n at hh:mm:ss`, `done: fired=N`) and
which situation each press was. Expect 3 fires. Confirm no Accessibility or
Input Monitoring prompt appeared.

## 4. Sandbox with TCC powers (row 22): signed probe app

Build (already built by the spike; rebuild if `build/` was cleaned):
`spikes/plan2/build_probe_app.sh`

**Grant once** (admin): System Settings > Privacy & Security > Accessibility >
`+` > select `build/probe/dist/gov-aios-probe.app` > on. (Remove it again after
the spike.)

Have Chrome running with at least one window. Then:

```
rm -f /tmp/govaios-probe.txt
open -W --stdout /tmp/govaios-probe.txt --stderr /tmp/govaios-probe.txt \
  build/probe/dist/gov-aios-probe.app --args run --tcc --dnsfix
cat /tmp/govaios-probe.txt
```

During the run: Finder comes to the front (activation check); a dialog
"GOV-AIOS sandbox probe: click OK" appears, click **OK**; a password/Touch ID
sheet with reason `approve: sandbox probe` appears, authenticate. A left-shift
press/release is posted to Chrome (no visible effect).

Repeat without `--dnsfix` (row 22 verbatim) to show the fix changes nothing
else:
`... --args run --tcc` then `cat` again.

Then the UI profile with the real browser:

```
rm -f /tmp/govaios-probe.txt
open --stdout /tmp/govaios-probe.txt --stderr /tmp/govaios-probe.txt \
  build/probe/dist/gov-aios-probe.app --args ui --dnsfix
sleep 2; grep URL /tmp/govaios-probe.txt
```

Open that URL in Chrome within 30 s; the page should say `govaios-probe-ok`.
Then `sleep 5; cat /tmp/govaios-probe.txt`.

Paste back: the three outputs. Expect every line `PASS` (in the run without
`--dnsfix`, the two `dns` lines `FAIL`, which is the known finding), and
`AXIsProcessTrusted True`, `AX read Chrome window title ... title_len>0`.

## 5. Chrome profile via LaunchServices (row 23): `probe_chrome.py`

Chrome running in some profile other than `Profile 2`. If `Profile 2` is not
the profile directory meant for GOV-AIOS, use the right one (see
`~/Library/Application Support/Google/Chrome/`, directory names only).

`.venv/bin/python spikes/plan2/probe_chrome.py "Profile 2" https://example.com`

The script applies the run sandbox to itself, then runs
`open -n -a "Google Chrome" --args --profile-directory="Profile 2" https://example.com`.

Paste back: all printed lines, plus one line each:
- did a window for that profile open in the already-running Chrome
  (one Chrome icon in the Dock, not two),
- did example.com load in it (yes/no; no other page content).

Expect `open exit=0`, one main Chrome process with ppid 1, page loaded.

## 6. TCC grant after the root install (row 18)

```
sudo ditto dist/gov-aios.app /Applications/gov-aios.app
sudo chown -R root:wheel /Applications/gov-aios.app
rm -f /tmp/govaios-doctor.txt
open -W --stdout /tmp/govaios-doctor.txt --stderr /tmp/govaios-doctor.txt \
  /Applications/gov-aios.app --args doctor
cat /tmp/govaios-doctor.txt
```

Paste back: the doctor output (bundle id, frozen, accessibility,
screen_recording), whether System Settings already lists gov-aios as allowed
under Accessibility and Screen Recording, and whether any grant prompt
appeared. Then say whether to **keep** `/Applications/gov-aios.app` installed
for later tasks or remove it (`sudo rm -rf /Applications/gov-aios.app`).

## After the spike

Remove `gov-aios-probe` from Accessibility; `rm -rf build/probe`.
