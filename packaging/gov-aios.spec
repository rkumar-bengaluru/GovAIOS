# Paths are relative to this spec file; ROOT is the repo root.
import os
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
a = Analysis(
    [ROOT + "/packaging/entry.py"],
    pathex=[ROOT],
    datas=[(ROOT + "/govaios/roles.yaml", "govaios"), (ROOT + "/flows", "flows"), (ROOT + "/pages", "pages")],
    hiddenimports=["objc", "AppKit", "Foundation", "ApplicationServices", "Quartz", "LocalAuthentication", "yaml", "cryptography", "segno"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="gov-aios", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="gov-aios")
app = BUNDLE(
    coll,
    name="gov-aios.app",
    bundle_identifier="com.govaios.cli",
    info_plist={
        "CFBundleExecutable": "gov-aios",
        "LSUIElement": True,
        "NSAppleEventsUsageDescription": "GOV-AIOS shows approval dialogs via osascript.",
    },
)
