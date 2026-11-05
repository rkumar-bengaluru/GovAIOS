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
