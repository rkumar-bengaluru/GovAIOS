import argparse
import os
import time

from . import identity


def _doctor(args) -> int:
    c = identity.check()
    for k, v in c.items():
        print(f"{k}: {v}")
    ok = c["bundle_id"] == "com.govaios.cli" and all(c[k] for k in ("frozen", "accessibility", "screen_recording"))
    return 0 if ok else 1


def _selftest(args) -> int:
    if args.mode == "lines":
        print("\n".join(f"line {i}" for i in range(args.n)))
    else:
        time.sleep(args.n)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gov-aios")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor")
    d.add_argument("--dev", action="store_true")  # accepted and ignored (R1)
    d.set_defaults(fn=_doctor)
    t = sub.add_parser("selftest")  # shim test hook: `selftest lines N` / `selftest sleep N`
    t.add_argument("mode", choices=["lines", "sleep"])
    t.add_argument("n", type=int)
    t.set_defaults(fn=_selftest)
    pf = os.environ.get("GOVAIOS_PID_FILE")  # lets the shim stop this run on Ctrl-C
    if pf:
        with open(pf, "w") as fh:
            fh.write(str(os.getpid()))
    try:
        args = p.parse_args(argv)
        code = args.fn(args)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 2
    f = os.environ.get("GOVAIOS_EXIT_FILE")
    if f:
        with open(f, "w") as fh:
            fh.write(str(code))
    return code
