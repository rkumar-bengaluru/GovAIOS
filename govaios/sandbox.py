"""OS-level network block (decision row 22). sandbox_init cannot be undone: call once, early, in the CLI process."""
import ctypes

# Final strings, verbatim from row 22. The mDNSResponder deny stays last so it overrides the unix-socket allow.
_BASE = ('(version 1) (allow default) (deny network*) (allow network* (remote unix-socket)) '
         '(deny mach-lookup (global-name "com.apple.dnssd.service"))')
_DNS_FIX = '(deny network-outbound (remote unix-socket (path-literal "/private/var/run/mDNSResponder")))'
RUN_PROFILE = _BASE + " " + _DNS_FIX
UI_PROFILE = _BASE + ' (allow network-bind network-inbound (local ip "localhost:*"))' + " " + _DNS_FIX


def apply(profile: str) -> None:
    lib = ctypes.CDLL("/usr/lib/libsandbox.1.dylib")
    lib.sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p)]
    lib.sandbox_init.restype = ctypes.c_int
    lib.sandbox_free_error.argtypes = [ctypes.c_char_p]
    err = ctypes.c_char_p()
    if lib.sandbox_init(profile.encode(), 0, ctypes.byref(err)) != 0:
        if err.value is not None:   # non-NULL buffer, even if empty
            lib.sandbox_free_error(err)
        raise RuntimeError("sandbox refused")
