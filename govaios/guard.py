"""Resident guard (`gov-aios guard`, LaunchAgent com.govaios.guard): owns the emergency-stop hotkey (rows 10-12).

ctrl+option+cmd+. is registered with Carbon RegisterEventHotKey via ctypes (no Accessibility or Input Monitoring,
row 53), exclusively, so a second guard fails to register and exits 1. guard.pid is written only after
registration succeeds and removed on exit. Each press runs runstate.emergency_stop.

Run loop (row 53): idle inside NSApp.run(), Python never runs, so a Python signal handler (SIGTERM from launchd,
Ctrl-C) stays pending forever. A repeating 0.2 s timer re-enters Python so pending handlers run; the handler stops
the app and posts an event so run() returns. App Nap is opted out so neither timer nor hotkey is throttled.
"""
import ctypes
import os
import signal
import sys
from pathlib import Path

from . import runstate
from .audit.log import AuditLog

KVK_ANSI_PERIOD = 47
CMD, OPTION, CONTROL = 0x0100, 0x0800, 0x1000
K_EVENT_HOTKEY_EXCLUSIVE = 1   # fail if any other process holds the same combo
K_EVENT_CLASS_KEYBOARD = int.from_bytes(b"keyb", "big")
K_EVENT_HOTKEY_PRESSED = 5
TICK_S = 0.2


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_keep = []   # ctypes callback and refs must outlive registration


def _app():
    import AppKit
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)   # no Dock icon, no menu bar
    return app


def _register(on_press) -> int:
    """OSStatus of the hotkey registration (0 = registered). Copied from spikes/plan2/probe_hotkey.py."""
    _app()   # Carbon's application event target needs NSApplication first
    carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
    carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
    carbon.InstallEventHandler.argtypes = [ctypes.c_void_p, HANDLER, ctypes.c_ulong, ctypes.POINTER(EventTypeSpec),
                                           ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    carbon.InstallEventHandler.restype = ctypes.c_int32
    carbon.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID, ctypes.c_void_p,
                                           ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    carbon.RegisterEventHotKey.restype = ctypes.c_int32

    @HANDLER
    def handler(_call, _event, _data):
        on_press()
        return 0

    target = carbon.GetApplicationEventTarget()
    spec, href, ref = EventTypeSpec(K_EVENT_CLASS_KEYBOARD, K_EVENT_HOTKEY_PRESSED), ctypes.c_void_p(), ctypes.c_void_p()
    _keep.extend([handler, href, ref])
    st = carbon.InstallEventHandler(target, handler, 1, ctypes.byref(spec), None, ctypes.byref(href))
    if st:
        return st
    hid = EventHotKeyID(int.from_bytes(b"GVAI", "big"), 1)
    return carbon.RegisterEventHotKey(KVK_ANSI_PERIOD, CONTROL | OPTION | CMD, hid, target,
                                      K_EVENT_HOTKEY_EXCLUSIVE, ctypes.byref(ref))


def _on_press(home: Path) -> None:
    try:
        runstate.emergency_stop(home, AuditLog(home))
    except Exception as e:   # never let a press take the guard down; STOPPED is written first
        print(f"gov-aios guard: emergency stop error: {type(e).__name__}", file=sys.stderr, flush=True)


def _run_loop() -> None:
    """Runs until SIGTERM or SIGINT."""
    import AppKit
    import Foundation
    app = _app()

    def quit_(signum, frame):
        app.stop_(None)   # takes effect after the next event, so post one
        app.postEvent_atStart_(AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            AppKit.NSEventTypeApplicationDefined, (0, 0), 0, 0, 0, None, 0, 0, 0), True)
    signal.signal(signal.SIGTERM, quit_)
    signal.signal(signal.SIGINT, quit_)
    timer = Foundation.NSTimer.scheduledTimerWithTimeInterval_repeats_block_(TICK_S, True, lambda t: None)
    activity = Foundation.NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
        Foundation.NSActivityUserInitiatedAllowingIdleSystemSleep, "emergency stop hotkey")
    app.run()
    timer.invalidate()
    Foundation.NSProcessInfo.processInfo().endActivity_(activity)


def main(home: Path) -> int:
    home = Path(home)
    try:
        st = _register(lambda: _on_press(home))
    except Exception as e:
        st = type(e).__name__
    if st:
        print(f"gov-aios guard: cannot register ctrl+option+cmd+. ({st}); another guard may hold it",
              file=sys.stderr, flush=True)
        return 1
    pid_file = home / "guard.pid"
    pid_file.write_text(str(os.getpid()))
    try:
        _run_loop()
    finally:
        pid_file.unlink(missing_ok=True)
    return 0
