# Packaging gov-aios

macOS gives Accessibility and Screen Recording to the *responsible
process*. If you start Python from Terminal, the permission belongs to
Terminal, and then every script Terminal runs can drive your desktop.
GOV-AIOS therefore ships as its own signed app, `com.govaios.cli`. The
admin grants the permissions to that app and to nothing else.

**Never grant Terminal, iTerm, or any Python these permissions for
GOV-AIOS.** `--dev` exists only for development, and it prints
`DEV MODE: insecure, not for real use`.

## Build

```bash
python3 -m venv .venv && .venv/bin/pip install pyinstaller pyobjc pyyaml cryptography
packaging/build.sh                 # builds and signs dist/gov-aios.app
bin/gov-aios doctor                # expects bundle_id: com.govaios.cli, frozen: True
```

`build.sh` runs PyInstaller with `packaging/gov-aios.spec`. It then
signs the bundle with the hardened runtime and checks the signature.

## Why `--onedir`, never `--onefile`

A `--onefile` build unpacks itself into a fresh temp directory on every
launch, and then runs from there. That breaks two things:

- the code macOS signed is no longer the code that runs;
- `sys._MEIPASS` (where `flows/`, `pages/` and `roles.yaml` are found)
  changes every time.

`--onedir` inside the `.app` keeps the signed files in place.

The spec also lists the pyobjc hidden imports (`objc`, `AppKit`,
`Foundation`, `ApplicationServices`, `Quartz`), together with `yaml` and
`cryptography`. PyInstaller's import scan misses them.

Nothing is ever written inside the bundle. The packaged app keeps all
data in `~/Library/Application Support/GOV-AIOS/` and ignores
`$GOVAIOS_HOME`, which only the unpackaged dev and test runs honour.

## Signing identity (`GOVAIOS_SIGN_ID`)

The default is `-`, which means ad hoc. Ad-hoc signing has a catch:
every rebuild gets a new code hash. macOS then treats the app as a new
app, so its Accessibility and Screen Recording grants stop applying, and
you must grant them again.

To keep the grants across rebuilds, sign with a stable self-signed
certificate:

1. Open Keychain Access and choose Certificate Assistant › Create a
   Certificate….
2. Set:
   - Name: `GOV-AIOS Dev`
   - Identity Type: Self Signed Root
   - Certificate Type: Code Signing
3. Choose Create.
4. Build with that certificate:
   `GOVAIOS_SIGN_ID="GOV-AIOS Dev" packaging/build.sh`.

The library-validation entitlement depends on the identity:

- **Ad-hoc and self-signed builds** have no Team ID. They therefore need
  `com.apple.security.cs.disable-library-validation` to load the bundled
  Python.framework. `build.sh` adds it and prints
  `WARNING: library validation off (dev signing)`.
- **A `Developer ID Application:` identity** gets no entitlements, and
  library validation stays on. The build fails if a Developer ID
  signature carries the entitlement.

The decision log (row 10) has the reasoning. A live release uses
Developer ID, notarization, and a Secure Enclave key (design §9.1).

## Granting permissions

Do these steps yourself. GOV-AIOS and its helpers never toggle them.

1. Open System Settings › Privacy & Security › Accessibility. Choose
   `+` and add `/Applications/gov-aios.app`.
2. Do the same under Screen Recording.
3. Run `bin/gov-aios doctor`. Expected lines: `bundle_id: com.govaios.cli`,
   `frozen: True`, `accessibility: True`, `screen_recording: True`,
   `guard: True`, `powers_review: <date>` (`missing` until you run
   `bin/gov-aios review-powers`) and `screen_locked: False`.
   `managed_settings` and `managed_settings_current` stay `False`, and
   the exit code stays 1, until Claude Code is governed (managed settings
   installed with `install.sh <managed-settings.json>`). After that every
   check passes and the exit code is 0.

With an ad-hoc build, repeat these steps after every rebuild. If an old
entry no longer applies, remove it and add the app again.

## The shim (`bin/gov-aios`)

The shim launches the installed app with `open -W -n -a /Applications/gov-aios.app`, so
macOS sees `com.govaios.cli` as the responsible process, not Terminal.

`open` does not pass stdio through. For each invocation, the shim:

1. creates its own `mktemp` files for stdout, stderr, the exit code and
   the app's pid, and passes them in with `open --env`;
2. streams the output files back to the terminal by byte offset, so
   parallel runs never share a file;
3. deletes the temp files on exit.

On Ctrl-C (or TERM), the shim stops the app through the pid file. File
arguments after the subcommand are made absolute, because `open` starts
the app with cwd `/`. Options are never rewritten.

## Install and uninstall (admin, with sudo)

```bash
packaging/build.sh
sudo packaging/install.sh --no-claude      # app + guard only; Claude Code not governed
sudo packaging/install.sh /path/ms.json    # also installs managed settings (from `gov-aios claude-settings`)
sudo packaging/uninstall.sh                # app, guard plist, managed settings; never the data home or audit log
```

`install.sh` copies `dist/gov-aios.app` to `/Applications/gov-aios.app`
(root:wheel, signer pinned to `GOV-AIOS Dev`), installs the guard LaunchAgent (written as the user) for the sudo user and loads
it. It changes no TCC setting: afterwards, grant Accessibility and
Screen Recording to `/Applications/gov-aios.app` in System Settings.
`bin/gov-aios` runs only the installed app.

Rebuild flow: `packaging/build.sh`, then `sudo packaging/install.sh --no-claude`
again (re-grant the permissions if the new build needs it).

## Control panel agent

`install.sh` also installs the `com.govaios.panel` LaunchAgent, which runs
`gov-aios panel --agent` at every login. The panel is at
`http://127.0.0.1:8765/`; sign in with Touch ID on the page. The agent
sets no stdout or stderr path (the panel writes its own `panel.log`).
If another program holds port 8765, install prints a warning.

Install seeds `~/Library/Application Support/GOV-AIOS/apps/{flows,pages}`
(0700) from the repo with `seed-apps.sh`. It never overwrites: a file you
edited is kept, and install prints `not updated: flows/<file>` (or
`pages/<file>`) when it differs from the repo. `uninstall.sh` removes the
agent and leaves the apps folder.

## Recovery (admin)

- Guard not running: `launchctl kickstart -k gui/$UID/com.govaios.guard`; if it is not loaded at all:
  `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.govaios.guard.plist`
- After an emergency stop: `bin/gov-aios resume` (Touch ID)
- Hook locks Claude Code out:
  `sudo rm "/Library/Application Support/ClaudeCode/managed-settings.json"`, then restart Claude Code

## Trust boundary

- `install.sh`, `handback.py` and `dist/` come from the checkout: run
  `sudo` only on a checkout you trust.
- `/Applications` is writable by admins, so the installed bundle can be
  replaced afterwards. The TCC designated requirement pins its identity
  only for the OS powers (Accessibility, Screen Recording), and
  `gov-aios doctor` checks it only when you run it. The Claude Code hook
  needs no TCC grant, and the stop and run checks (`is_govaios`) trust the
  path alone: a replaced bundle at that path is a working hook. This risk
  is accepted for now.
- A signed pkg is future work.
