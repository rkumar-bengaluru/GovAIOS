import argparse
import os

from . import identity


def _doctor(args) -> int:
    c = identity.check()
    for k, v in c.items():
        print(f"{k}: {v}")
    ok = c["bundle_id"] == "com.govaios.cli" and all(c[k] for k in ("frozen", "accessibility", "screen_recording"))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gov-aios")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor")
    d.add_argument("--dev", action="store_true")  # accepted and ignored (R1)
    d.set_defaults(fn=_doctor)
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
