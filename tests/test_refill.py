import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("refill", Path(__file__).parent.parent / "scripts" / "refill_shortlisted.py")
refill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refill)


def run(monkeypatch, capsys, statuses, counts, send=None, n=4):
    """statuses: id -> list of polled statuses; counts: successive shortlisted values (None = unreachable)."""
    posts, polls, cs = [], {}, iter(counts)

    def fake_send(url, payload, timeout=20):
        posts.append((url, payload))
        return send(len(posts)) if send else (202, {"id": len(posts), "status": "new", "duplicate": False})

    def fake_get(url):
        if url.endswith("/counts"):
            v = next(cs)
            return None if v is None else {"shortlisted": v}
        lid = int(url.rsplit("/", 1)[1])
        s = statuses[lid]
        polls[lid] = polls.get(lid, 0) + 1
        return {"status": s[min(polls[lid], len(s)) - 1], "reason": "r%d" % lid}

    monkeypatch.setattr(refill.delivery, "send", fake_send)
    monkeypatch.setattr(refill, "get", fake_get)
    rc = refill.main(["--n", str(n)], sleep=lambda s: None)
    out = capsys.readouterr()
    return rc, posts, out.out, out.err, polls


def test_refill_posts_unique_test_listings_to_joblens_only(monkeypatch, capsys):
    st = {i: ["shortlisted"] for i in range(1, 5)}
    rc, posts, out, err, _ = run(monkeypatch, capsys, st, [2, 6])
    assert rc == 0
    assert len(posts) == 4
    assert {u for u, _ in posts} == {"http://127.0.0.1:8100/api/discover/listings"}
    assert len({p["title"] for _, p in posts}) == 4 and len({p["url"] for _, p in posts}) == 4
    assert {p["source"] for _, p in posts} == {"GOV-AIOS test"}
    assert all(len(p["jd_text"]) >= 300 for _, p in posts)
    assert "1 shortlisted r1" in out and "shortlisted: 2 -> 6" in out


def test_refill_unreachable_exits_2(monkeypatch, capsys):
    assert run(monkeypatch, capsys, {}, [None])[0] == 2
    rc, posts, _, err, _ = run(monkeypatch, capsys, {}, [0], send=lambda i: (None, None))
    assert rc == 2 and "not reachable" in err


def test_refill_fails_when_screened_out(monkeypatch, capsys):
    st = {1: ["shortlisted"], 2: ["screened_out"], 3: ["shortlisted"], 4: ["screened_out"]}
    rc, _, out, err, _ = run(monkeypatch, capsys, st, [0, 2])
    assert rc == 1
    assert "2 screened_out r2" in out
    assert err.strip() == ("only 2 of 4 reached Shortlisted; JobLens screened the rest (reasons above). Teach on what is "
                           "there, or lower Quick threshold in JobLens's Discover settings for the test.")


def test_refill_waits_past_new(monkeypatch, capsys):
    rc, _, out, _, polls = run(monkeypatch, capsys, {1: ["new", "shortlisted"]}, [0, 1], n=1)
    assert rc == 0 and polls[1] == 2 and "1 shortlisted r1" in out
