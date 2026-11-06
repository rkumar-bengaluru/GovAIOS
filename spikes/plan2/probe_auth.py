"""Rows 4, 6 probe: LocalAuthentication policies, sheet, reason text, 60 s invalidate.

Usage:
  python probe_auth.py                 # canEvaluatePolicy for both policies (no prompt)
  python probe_auth.py prompt          # one prompt, policy chosen as row 6; admin touches (or cancels)
  python probe_auth.py abandon         # one prompt; admin leaves it alone; invalidate() at 60 s
  python probe_auth.py prompt --owner  # force LAPolicyDeviceOwnerAuthentication
Prints policy codes, error codes and timings only.
"""
import sys
import threading
import time

import LocalAuthentication as LA

REASON = "approve: test run"
POLICIES = {
    "biometrics": LA.LAPolicyDeviceOwnerAuthenticationWithBiometrics,
    "device_owner": LA.LAPolicyDeviceOwnerAuthentication,
}


def can(policy):
    ctx = LA.LAContext.alloc().init()
    ok, err = ctx.canEvaluatePolicy_error_(policy, None)
    return bool(ok), (err.code() if err else None), ctx.biometryType()


def choose():
    """Row 6: biometrics when available, else device owner, else None (deny)."""
    if can(POLICIES["biometrics"])[0]:
        return "biometrics"
    if can(POLICIES["device_owner"])[0]:
        return "device_owner"
    return None


def prompt(name, abandon):
    ctx = LA.LAContext.alloc().init()  # a new context per prompt (row 4)
    ctx.setTouchIDAuthenticationAllowableReuseDuration_(0)
    if name == "biometrics":
        ctx.setLocalizedFallbackTitle_("")  # hide "Enter Password" (row 6)
    done = threading.Event()
    res = {}
    t0 = time.monotonic()

    def reply(success, error):
        res.update(ok=bool(success), code=(error.code() if error else None),
                   at=round(time.monotonic() - t0, 1))
        done.set()

    ctx.evaluatePolicy_localizedReason_reply_(POLICIES[name], REASON, reply)
    print(f"prompt shown: policy={name} reason={REASON!r}", flush=True)
    if abandon:
        if done.wait(60):
            print(f"reply before 60 s (admin was asked not to touch): {res}")
            return
        print("60 s elapsed: calling invalidate()", flush=True)
        ctx.invalidate()
        got = done.wait(10)
        print(f"after invalidate: reply={'arrived' if got else 'NEVER (10 s)'} {res}")
    else:
        got = done.wait(120)
        print(f"reply: {res if got else 'none in 120 s'}")


def main(argv):
    for n, p in POLICIES.items():
        ok, code, bt = can(p)
        print(f"canEvaluatePolicy {n}: {ok} error={code} biometryType={bt}")
    name = "device_owner" if "--owner" in argv else choose()
    print(f"row-6 choice: {name}")
    if argv and argv[0] in ("prompt", "abandon"):
        if name is None:
            print("no policy available: deny")
            return 1
        prompt(name, argv[0] == "abandon")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
