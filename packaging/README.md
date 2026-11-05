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

Nothing is ever written inside the bundle. All data lives in
`$GOVAIOS_HOME`, which defaults to
`~/Library/Application Support/GOV-AIOS/`.

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
   `+` and add `dist/gov-aios.app`.
2. Do the same under Screen Recording.
3. Run `bin/gov-aios doctor`. Every line should say `True`, and the exit
   code should be 0.

With an ad-hoc build, repeat these steps after every rebuild. If an old
entry no longer applies, remove it and add the app again.

## The shim (`bin/gov-aios`)

The shim launches the app with `open -W -n -a dist/gov-aios.app`, so
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
