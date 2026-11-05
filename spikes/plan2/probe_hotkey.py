"""Row 10 probe: Carbon RegisterEventHotKey for ctrl+option+cmd+. via ctypes, accessory-app run loop.

Usage:
  python probe_hotkey.py [seconds=60]   # register, print "FIRED <n>" on each press, exit after N s
  python probe_hotkey.py 0              # register and exit at once (status only)
  python probe_hotkey.py 0 --sandbox    # apply RUN_PROFILE (row 22) first, as `guard` will
Exit 2 if registration fails (e.g. combo taken by another process with the exclusive flag).
Needs no Accessibility or Input Monitoring grant (that is what this probe checks). Task 5 copies the ctypes code.
"""
import ctypes
import sys
import time

import AppKit
from PyObjCTools import AppHelper

_carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")

KVK_ANSI_PERIOD = 47
CMD, OPTION, CONTROL = 0x0100, 0x0800, 0x1000
MODS = CONTROL | OPTION | CMD
K_EVENT_HOTKEY_EXCLUSIVE = 1  # fail if any other process holds the same combo
K_EVENT_CLASS_KEYBOARD = int.from_bytes(b"keyb", "big")
K_EVENT_HOTKEY_PRESSED = 5


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
_carbon.InstallEventHandler.argtypes = [ctypes.c_void_p, HANDLER, ctypes.c_ulong,
                                        ctypes.POINTER(EventTypeSpec), ctypes.c_void_p,
                                        ctypes.POINTER(ctypes.c_void_p)]
_carbon.InstallEventHandler.restype = ctypes.c_int32
_carbon.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID, ctypes.c_void_p,
                                        ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
_carbon.RegisterEventHotKey.restype = ctypes.c_int32

fired = 0


@HANDLER
def _on_hotkey(_call, _event, _data):
    global fired
    fired += 1
    print(f"FIRED {fired} at {time.strftime('%H:%M:%S')}", flush=True)
    return 0


def register(on_press=_on_hotkey) -> int:
    """Returns OSStatus (0 = registered). Call after NSApplication exists, on the main thread."""
    target = _carbon.GetApplicationEventTarget()
    spec = EventTypeSpec(K_EVENT_CLASS_KEYBOARD, K_EVENT_HOTKEY_PRESSED)
    href = ctypes.c_void_p()
    st = _carbon.InstallEventHandler(target, on_press, 1, ctypes.byref(spec), None, ctypes.byref(href))
    if st:
        return st
    ref = ctypes.c_void_p()
    hid = EventHotKeyID(int.from_bytes(b"GVAI", "big"), 1)
    return _carbon.RegisterEventHotKey(KVK_ANSI_PERIOD, MODS, hid, target, K_EVENT_HOTKEY_EXCLUSIVE, ctypes.byref(ref))


def main(seconds: int) -> int:
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    st = register()
    print(f"RegisterEventHotKey status={st}", flush=True)
    if st:
        return 2
    if seconds <= 0:
        return 0
    def finish():
        print(f"done: fired={fired}", flush=True)
        AppHelper.stopEventLoop()  # terminates the app
    AppHelper.callLater(seconds, finish)
    AppHelper.runEventLoop(installInterrupt=True)
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--sandbox"]
    if "--sandbox" in sys.argv:
        from probe_sandbox import RUN_PROFILE, sandbox_init
        sandbox_init(RUN_PROFILE)
        print("sandbox_init applied (RUN_PROFILE, row 22)", flush=True)
    sys.exit(main(int(args[0]) if args else 60))
