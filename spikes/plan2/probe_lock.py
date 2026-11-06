"""Row 8 probe: print the lock-relevant CGSession keys once a second.

Usage: python probe_lock.py [seconds=30]   (admin locks, unlocks, switches user meanwhile)
Prints only the two keys of row 8 plus the row-8 verdict; no user names.
"""
import sys
import time

import Quartz


def screen_locked() -> bool:
    """Row 8 rule, as Task 6 will implement it."""
    d = Quartz.CGSessionCopyCurrentDictionary()
    if d is None:
        return True
    return bool(d.get("CGSSessionScreenIsLocked", False)) or not bool(d.get(Quartz.kCGSessionOnConsoleKey, False))


def main(seconds: int) -> None:
    print(f"kCGSessionOnConsoleKey = {Quartz.kCGSessionOnConsoleKey!r}")
    for i in range(seconds):
        d = Quartz.CGSessionCopyCurrentDictionary()
        if d is None:
            print(f"{i:3d}s dict=None locked=True", flush=True)
        else:
            print(f"{i:3d}s CGSSessionScreenIsLocked={d.get('CGSSessionScreenIsLocked')!r} "
                  f"onConsole={d.get(Quartz.kCGSessionOnConsoleKey)!r} locked={screen_locked()}", flush=True)
        time.sleep(1)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
