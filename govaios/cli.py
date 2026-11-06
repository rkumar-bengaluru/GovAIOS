import argparse
import errno
import os
import stat
import time

import sys

from . import identity, sandbox

PROFILES = {"doctor": None, "audit-ui": sandbox.UI_PROFILE, "panel": sandbox.UI_PROFILE, "deliver": sandbox.DELIVER_PROFILE}   # every other subcommand: RUN_PROFILE (row 22)


def _doctor(args) -> int:
    from . import auth, executor, hook, powers, runstate
    from .home import data_home

    home = data_home()
    c = identity.check()
    try:
        st = hook.MANAGED_SETTINGS.stat()   # follows a link: who can change the content is what counts
        managed = st.st_uid == 0 and st.st_mode & 0o022 == 0
    except OSError:
        managed = False
    try:   # row 32: the hook's own comparison
        current = hook.drift(hook.MANAGED_SETTINGS, executor.load(home)[0]) is None
    except Exception:   # no or bad policy: not current
        current = False
    ts = powers.last(home)
    c.update(guard=runstate.guard_alive(home), managed_settings=managed, managed_settings_current=current,
             powers_review=ts.date().isoformat() if ts else "missing", screen_locked=auth.screen_locked())
    for k, v in c.items():
        print(f"{k}: {v}")
    ok = (not identity.failing(c) and c["guard"] and managed and current and powers.fresh(home)
          and not c["screen_locked"])
    return 0 if ok else 1


def preflight(home, dev: bool) -> None:
    """Rows 28 and 24, in order (the sandbox is already applied in main). Dev differs only in identity."""
    from . import auth, powers, runstate

    if not runstate.guard_alive(home):
        raise SystemExit("refused: the gov-aios guard is not running")
    if runstate.stopped(home):
        raise SystemExit("refused: STOPPED (emergency stop); run `gov-aios resume`")
    if auth.screen_locked():
        raise SystemExit("refused: the screen is locked")
    if not powers.fresh(home):
        raise SystemExit("refused: no powers review in the last 30 days; run `gov-aios review-powers`")
    bad = [] if dev else identity.failing(identity.check())
    if bad:
        raise SystemExit(f"refused: doctor check failed: {', '.join(bad)}")


def _run(args) -> int:
    from pathlib import Path

    from .desktop import get_desktop
    from .engine import Runner, Stop
    from .home import data_home
    from .netguard import block_all_network
    from .runstate import register_run, unregister_run

    packaged = identity.require_app(args.dev)
    block_all_network()  # before Runner exists, so nothing it builds can open a socket
    executor = "gov_runner" if packaged and not args.dev else "gov_runner_dev"
    home = data_home()
    register_run(home)   # before the STOPPED check, so a stop pressed in between still finds this run
    try:
        preflight(home, dev=not packaged)
        runner = Runner(Path(args.flow).resolve(), get_desktop(), home, executor,
                        ticket=os.environ.get("GOVAIOS_RUN_TICKET") or None)
        runner.run()
        if runner.deliver:   # only after flow_end: the shim then starts `deliver`, which re-checks everything
            _write_shim_file("GOVAIOS_NEXT_FILE", "deliver")
    except Stop as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        return 1
    except Exception as e:   # type only: messages and tracebacks can carry page content
        print(f"ERROR: {type(e).__name__}", file=sys.stderr)
        return 1
    finally:
        unregister_run(home)
    return 0


def _deliver(args) -> int:
    from pathlib import Path

    from . import delivery
    from .audit.log import AuditLog
    from .home import data_home
    from .runstate import Stop, register_run, unregister_run

    packaged = identity.require_app(args.dev)
    home = data_home()   # no block_all_network(): DELIVER_PROFILE already allows only 127.0.0.1:8100
    register_run(home)   # as _run: so the emergency stop finds and ends it
    try:
        preflight(home, dev=not packaged)
        return delivery.run_delivery(Path(args.flow).resolve(), home, AuditLog(home))
    except Stop as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        return 1
    except Exception as e:   # type only: messages can carry job content
        print(f"ERROR: {type(e).__name__}", file=sys.stderr)
        return 1
    finally:
        unregister_run(home)


def _verify_audit(args) -> int:
    from .audit.log import AuditLog
    from .audit.verify import main as verify_main
    from .home import data_home

    log = AuditLog(data_home())
    return verify_main([str(log.path), str(log.pub_path)])


def _audit_ui(args) -> int:
    from pathlib import Path

    from .audit.web import make_server
    from .home import data_home

    home = data_home()   # sign-in (Touch ID, audited ui_login) happens on the page
    flows = Path(args.flows_dir).resolve() if args.flows_dir else None
    try:
        server = make_server(home, args.port, flows_dir=flows, helper=args.helper)
    except OSError as e:
        if not args.agent:
            raise
        from .panel import agentlog   # a login agent has no terminal: one log line, not a traceback
        agentlog.once(home, f"panel: port {args.port} is in use" if e.errno == errno.EADDRINUSE
                      else f"panel: cannot start ({type(e).__name__})")
        return 1
    print(f"Control panel: http://127.0.0.1:{server.server_address[1]}/", flush=True)
    import signal

    def _term(*_):
        raise KeyboardInterrupt   # the shim's trap sends SIGTERM: end like Ctrl-C, so server_close runs
    prev = signal.signal(signal.SIGTERM, _term)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)   # a 2nd SIGTERM must not cut the session end / run stop short
        try:
            server.server_close()
        finally:
            signal.signal(signal.SIGTERM, prev)
    return 0


def _panel(args) -> int:
    return _audit_ui(args)   # audit-ui is the older name


def _dump(args) -> int:
    # Read-only: no navigation, keystrokes or app launch (only sets Chrome's AX-enable flags); page content to stdout only.
    from .home import data_home
    from .runstate import register_run, unregister_run

    packaged = identity.require_app(args.dev)
    from .netguard import block_all_network
    block_all_network()  # dump reads page content; nothing it does needs the network
    home = data_home()
    register_run(home)   # as _run: before the STOPPED check, so a stop pressed in between finds it
    try:
        return _dump_registered(home, packaged)
    finally:
        unregister_run(home)


def _dump_registered(home, packaged) -> int:
    import time

    from . import auth
    from .audit.log import AuditLog
    from .desktop import get_desktop

    preflight(home, dev=not packaged)
    ok, how = auth.prove("print the open Chrome page", home)   # row 29: else a confused deputy for AX
    AuditLog(home).append("request", action="dump", decision="allow" if ok else "deny", approver="admin",
                          channel="touch_id", auth=how)   # metadata only: never page content
    if not ok:
        print("not proven; nothing read", file=sys.stderr)
        return 1
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
    from .hook import ID, bad_destination, bad_root, managed_settings
    from .home import data_home

    home = data_home()
    path = home / executor.POLICY_PATH
    if any(bad_root(r, home) for r in args.root):
        print("refused: a project root equals, contains or sits inside a protected path", file=sys.stderr)
        return 1
    if path.exists():
        print(f"note: {path} exists; its project_roots are used, not --root", file=sys.stderr)
    else:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(executor.default_policy(*(os.path.realpath(r) for r in args.root)))
    raw = path.read_bytes()   # shown and approved bytes must be the hashed bytes (Rule 11)
    try:
        pol, digest = executor.load(home)
    except ValueError as e:   # our own message: field names only
        print(f"refused: {path}: {e}", file=sys.stderr)
        return 1
    if hashlib.sha256(raw).hexdigest() != digest:
        print("refused: policy changed while reading; try again", file=sys.stderr)
        return 1
    if not pol.get("project_roots") or any(bad_root(r, home) for r in pol["project_roots"]):
        print(f"refused: {path} needs project_roots, none inside or above a protected path", file=sys.stderr)
        return 1
    dests = pol.get("destinations")
    if not isinstance(dests, list) or any(bad_destination(d) for d in dests):
        print(f"refused: {path} destinations must be bare host names (e.g. github.com)", file=sys.stderr)
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


def _review_powers(args) -> int:
    from . import powers
    from .audit.log import AuditLog
    from .home import data_home

    home = data_home()
    if not powers.review(home, args.kept, AuditLog(home)):
        print("powers review not approved", file=sys.stderr)
        return 1
    print("powers review recorded")
    return 0


def _selftest(args) -> int:
    if not args.dev:
        sys.exit("selftest requires --dev")
    if args.mode == "lines":
        print("\n".join(f"line {i}" for i in range(args.n)))
    else:
        time.sleep(args.n)
    return 0


AGENT_PORT = 8765   # test seam: the agent port is not a CLI flag


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
    dl = sub.add_parser("deliver")
    dl.add_argument("flow")
    dl.add_argument("--dev", action="store_true")
    dl.set_defaults(fn=_deliver)
    sub.add_parser("verify-audit").set_defaults(fn=_verify_audit)
    for name, fn in (("audit-ui", _audit_ui), ("panel", _panel)):
        a = sub.add_parser(name)
        a.add_argument("flows_dir", nargs="?")
        a.add_argument("--port", type=int, default=0)
        a.add_argument("--agent", action="store_true")   # login LaunchAgent: fixed port, apps under the data home, log file
        a.set_defaults(fn=fn)
    x = sub.add_parser("dump")
    x.add_argument("--dev", action="store_true")
    x.set_defaults(fn=_dump)
    sub.add_parser("guard").set_defaults(fn=_guard)
    sub.add_parser("resume").set_defaults(fn=_resume)
    sub.add_parser("hook").set_defaults(fn=_hook)
    c = sub.add_parser("claude-settings")
    c.add_argument("--root", action="append", required=True)
    c.set_defaults(fn=_claude_settings)
    rp = sub.add_parser("review-powers")
    rp.add_argument("kept", nargs="*", metavar="KEPT")   # the apps the admin keeps in the three panes
    rp.set_defaults(fn=_review_powers)
    _write_shim_file("GOVAIOS_PID_FILE", os.getpid())  # lets the shim stop this run on Ctrl-C
    code = 1
    helper = None
    out_err = None
    try:
        args = p.parse_args(argv)
        args.helper = None
        if getattr(args, "agent", False):
            from .home import data_home
            from .panel import agentlog
            args.port = AGENT_PORT
            args.flows_dir = str(data_home() / "apps" / "flows")   # may not exist: the panel shows "No apps yet."
            log = agentlog.open_log(data_home())   # before the sandbox (it allows file writes; opened early anyway)
            out_err = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = log
        if args.cmd in ("panel", "audit-ui") and args.flows_dir:   # before the sandbox and any thread: it runs the app
            from pathlib import Path

            from .home import data_home
            from .panel import helper as launch_helper
            args.helper = helper = launch_helper.start_helper(Path(args.flows_dir).resolve(), data_home())
        profile = PROFILES.get(args.cmd, sandbox.RUN_PROFILE)
        if profile:   # first, before anything can resolve a name: a resolver opened earlier outlives the sandbox
            try:
                sandbox.apply(profile)
            except RuntimeError:
                print("refused: OS sandbox could not be applied", file=sys.stderr)
                _write_exit(1)
                return 1
        code = args.fn(args)
    except SystemExit as e:
        if isinstance(e.code, int):
            code = e.code
        else:
            code = 0 if e.code is None else 1
            if e.code is not None:
                print(e.code, file=sys.stderr)
        _write_exit(code)
        raise SystemExit(code) from None   # message already printed; re-raising the string prints it twice
    except BaseException:
        _write_exit(1)
        raise
    finally:
        if helper is not None:
            helper.close()   # ends the helper and any run it still has
        if out_err:
            sys.stdout, sys.stderr = out_err
            log.close()
    _write_exit(code)
    return code


def _write_exit(code: int) -> None:
    _write_shim_file("GOVAIOS_EXIT_FILE", code)


def _write_shim_file(var: str, value) -> None:
    """Only into an existing empty regular file (the shim's mktemp), never through a link: the hook's env may be
    shaped by Claude (M-6). Anything else is skipped silently; the shim then just lacks the value."""
    f = os.environ.get(var)
    if not f:
        return
    try:
        fd = os.open(f, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK)   # no O_CREAT; NONBLOCK: a FIFO cannot hang us
    except OSError:
        return
    with os.fdopen(fd, "w") as fh:
        st = os.fstat(fd)
        if stat.S_ISREG(st.st_mode) and st.st_size == 0:
            fh.write(str(value))


if __name__ == "__main__":
    sys.exit(main())
