import argparse
import os
import time

import sys

from . import identity


def _doctor(args) -> int:
    c = identity.check()
    for k, v in c.items():
        print(f"{k}: {v}")
    ok = c["bundle_id"] == "com.govaios.cli" and all(c[k] for k in ("frozen", "accessibility", "screen_recording"))
    return 0 if ok else 1


def _run(args) -> int:
    from pathlib import Path

    from .desktop import get_desktop
    from .engine import Runner, Stop
    from .home import data_home
    from .netguard import block_all_network

    packaged = identity.require_app(args.dev)
    block_all_network()  # before Runner exists, so nothing it builds can open a socket
    executor = "gov_runner" if packaged and not args.dev else "gov_runner_dev"
    try:
        Runner(Path(args.flow).resolve(), get_desktop(), data_home(), executor).run()
    except Stop as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        return 1
    except Exception as e:   # type only: messages and tracebacks can carry page content
        print(f"ERROR: {type(e).__name__}", file=sys.stderr)
        return 1
    return 0


def _verify_audit(args) -> int:
    from .audit.log import AuditLog
    from .audit.verify import main as verify_main
    from .home import data_home

    log = AuditLog(data_home())
    return verify_main([str(log.path), str(log.pub_path)])


def _audit_ui(args) -> int:
    from .audit.web import make_server
    from .home import data_home

    server, token = make_server(data_home(), args.port)
    print(f"http://127.0.0.1:{server.server_address[1]}/?t={token}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _dump(args) -> int:
    # Read-only: no navigation, keystrokes or app launch (only sets Chrome's AX-enable flags); stdout only, never the audit.
    import time

    from .desktop import get_desktop

    identity.require_app(args.dev)
    from .netguard import block_all_network
    block_all_network()  # dump reads page content; nothing it does needs the network
    d = get_desktop()
    if not d._app("chrome"):
        sys.exit("chrome is not running")
    root = None
    for _ in range(10):
        root = d.web_root("chrome")
        if root and len(root.children):
            break
        time.sleep(1)
    print("WINDOW:", d.window_title("chrome"))
    if not root:
        sys.exit("no web document")
    n = 0

    def show(node, depth):
        nonlocal n
        n += 1
        bits = [node.role] + [f'{k}="{v[:100]}"' for k, v in (("name", node.name), ("value", node.value)) if v]
        if node.dom_id:
            bits.append("#" + node.dom_id)
        print("  " * depth + " ".join(bits))
        for c in node.children:
            show(c, depth + 1)

    show(root, 0)
    print("NODES:", n)
    return 0


def _guard(args) -> int:
    from .guard import main as guard_main
    from .home import data_home

    return guard_main(data_home())


def _resume(args) -> int:
    from .audit.log import AuditLog
    from .home import data_home
    from .runstate import resume

    home = data_home()
    if not resume(home, AuditLog(home)):
        print("resume not proven; gov-aios stays stopped", file=sys.stderr)
        return 1
    print("resumed")
    return 0


def _hook(args) -> int:
    from .hook import main as hook_main
    from .home import data_home

    return hook_main(sys.stdin, sys.stdout, sys.stderr, data_home())


def _claude_settings(args) -> int:
    import hashlib
    import json

    from . import auth, executor
    from .approvals import Approvals
    from .audit.log import AuditLog
    from .hook import ID, bad_root, managed_settings
    from .home import data_home

    home = data_home()
    path = home / executor.POLICY_PATH
    if any(bad_root(r, home) for r in args.root):
        print("refused: a project root equals, contains or sits inside a protected path", file=sys.stderr)
        return 1
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(executor.default_policy(*(os.path.realpath(r) for r in args.root)))
    raw = path.read_bytes()   # shown and approved bytes must be the hashed bytes (Rule 11)
    pol, digest = executor.load(home)
    if hashlib.sha256(raw).hexdigest() != digest:
        print("refused: policy changed while reading; try again", file=sys.stderr)
        return 1
    if not pol.get("project_roots") or any(bad_root(r, home) for r in pol["project_roots"]):
        print(f"refused: {path} needs project_roots, none inside or above a protected path", file=sys.stderr)
        return 1
    q = f"Approve this Claude Code executor policy ({path})?\n\n" + raw.decode(errors="replace")
    ok, how = auth.approve(q, "approve Claude Code executor policy", home)
    AuditLog(home).append("flow_approval", flow=ID, flow_hash=digest, executor=ID, decision="allow" if ok else "deny",
                          approver="admin", channel="touch_id", auth=how)
    if not ok:
        print("approval busy" if how == "busy" else "not approved", file=sys.stderr)
        return 1
    Approvals(home / "approvals.json").approve_flow(ID, digest)
    print(json.dumps(managed_settings(pol, home), indent=2))
    return 0


def _selftest(args) -> int:
    if not args.dev:
        sys.exit("selftest requires --dev")
    if args.mode == "lines":
        print("\n".join(f"line {i}" for i in range(args.n)))
    else:
        time.sleep(args.n)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gov-aios", allow_abbrev=False)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor")
    d.add_argument("--dev", action="store_true")  # accepted and ignored (R1)
    d.set_defaults(fn=_doctor)
    t = sub.add_parser("selftest")  # shim test hook: `selftest lines N` / `selftest sleep N`
    t.add_argument("mode", choices=["lines", "sleep"])
    t.add_argument("n", type=int)
    t.add_argument("--dev", action="store_true")
    t.set_defaults(fn=_selftest)
    r = sub.add_parser("run")
    r.add_argument("flow")
    r.add_argument("--dev", action="store_true")
    r.set_defaults(fn=_run)
    sub.add_parser("verify-audit").set_defaults(fn=_verify_audit)
    a = sub.add_parser("audit-ui")
    a.add_argument("--port", type=int, default=0)
    a.set_defaults(fn=_audit_ui)
    x = sub.add_parser("dump")
    x.add_argument("--dev", action="store_true")
    x.set_defaults(fn=_dump)
    sub.add_parser("guard").set_defaults(fn=_guard)
    sub.add_parser("resume").set_defaults(fn=_resume)
    sub.add_parser("hook").set_defaults(fn=_hook)
    c = sub.add_parser("claude-settings")
    c.add_argument("--root", action="append", required=True)
    c.set_defaults(fn=_claude_settings)
    pf = os.environ.get("GOVAIOS_PID_FILE")  # lets the shim stop this run on Ctrl-C
    if pf:
        with open(pf, "w") as fh:
            fh.write(str(os.getpid()))
    code = 1
    try:
        args = p.parse_args(argv)
        code = args.fn(args)
    except SystemExit as e:
        if isinstance(e.code, int):
            code = e.code
        else:
            code = 0 if e.code is None else 1
            if e.code is not None:
                print(e.code, file=sys.stderr)
        _write_exit(code)
        raise
    except BaseException:
        _write_exit(1)
        raise
    _write_exit(code)
    return code


def _write_exit(code: int) -> None:
    f = os.environ.get("GOVAIOS_EXIT_FILE")
    if f:
        with open(f, "w") as fh:
            fh.write(str(code))


if __name__ == "__main__":
    sys.exit(main())
