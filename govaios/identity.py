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


def require_app(dev: bool) -> None:
    if check()["bundle_id"] != "com.govaios.cli":
        if not dev:
            raise SystemExit("gov-aios must run as com.govaios.cli (use bin/gov-aios); --dev allows Python for development only")
        print("DEV MODE: insecure, not for real use", file=sys.stderr)
