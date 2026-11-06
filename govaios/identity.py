import os
import pwd
import sys


def check() -> dict:
    import Quartz
    from AppKit import NSBundle
    from ApplicationServices import AXIsProcessTrusted

    return {
        "bundle_id": NSBundle.mainBundle().bundleIdentifier(),
        "frozen": getattr(sys, "frozen", False),
        "accessibility": bool(AXIsProcessTrusted()),
        "screen_recording": bool(Quartz.CGPreflightScreenCaptureAccess()),
    }


def failing(c: dict) -> list[str]:
    """Doctor's identity checks that fail: the installed, frozen app holding its two TCC grants."""
    bad = [] if c["bundle_id"] == "com.govaios.cli" else ["bundle_id"]
    return bad + [k for k in ("frozen", "accessibility", "screen_recording") if not c[k]]


def require_app(dev: bool) -> bool:
    """True when running as the packaged app; with --dev outside it, False (dev mode)."""
    if check()["bundle_id"] == "com.govaios.cli":
        return True
    if not dev:
        raise SystemExit("gov-aios must run as com.govaios.cli (use bin/gov-aios); --dev allows Python for development only")
    _require_dev_home()
    print("DEV MODE: insecure, not for real use", file=sys.stderr)
    return False


def _require_dev_home() -> None:
    """Row 28: dev runs never touch the real audit, key or approvals."""
    from .policy import _inside
    env = os.environ.get("GOVAIOS_HOME")
    real = os.path.realpath(os.path.join(pwd.getpwuid(os.getuid()).pw_dir, "Library/Application Support/GOV-AIOS"))
    if not env or _inside(os.path.realpath(env), real, True):
        raise SystemExit("--dev needs GOVAIOS_HOME set to a directory outside the real data home")
