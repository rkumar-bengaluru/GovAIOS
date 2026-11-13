"""Test-only: post the admin's own test listings to their own local JobLens and check they reached Shortlisted."""
import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from govaios import delivery  # noqa: E402

BASE = "http://127.0.0.1:8100/api/discover/listings"
JD = ("This is a GOV-AIOS test listing, posted by the admin to their own local JobLens. " * 5).strip()
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url):
    try:
        with _OPENER.open(url, timeout=20) as r:
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


def main(argv=None, sleep=time.sleep):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4, choices=range(1, 11))
    n = ap.parse_args(argv).n
    c = get(BASE + "/counts")
    if not isinstance(c, dict) or "shortlisted" not in c:
        print("JobLens not reachable at 127.0.0.1:8100 (is it running?)", file=sys.stderr)
        return 2
    before = c["shortlisted"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    ids = []
    for i in range(n):
        code, body = delivery.send(delivery.TARGETS["joblens"]["url"], {
            "title": f"GOV-AIOS test profile {stamp}-{i}", "source": "GOV-AIOS test", "company": "Test Co",
            "url": f"http://localhost/test/{stamp}-{i}", "jd_text": JD})
        if code is None:
            print("JobLens not reachable at 127.0.0.1:8100 (is it running?)", file=sys.stderr)
            return 2
        if code not in (200, 202) or not isinstance(body, dict) or "id" not in body:
            print(f"JobLens refused listing {i} (http {code})", file=sys.stderr)
            return 1
        ids.append(body["id"])
    for lid in ids:
        for _ in range(60):
            d = get(f"{BASE}/{lid}") or {}
            if d.get("status") not in (None, "new"):
                break
            sleep(2)
        print(lid, d.get("status"), d.get("reason") or "")
    after = (get(BASE + "/counts") or {}).get("shortlisted")
    print(f"shortlisted: {before} -> {after}")
    if after is not None and after - before == n:
        return 0
    k = max(0, after - before) if after is not None else 0
    print(f"only {k} of {n} reached Shortlisted; JobLens screened the rest (reasons above). Teach on what is there, "
          "or lower Quick threshold in JobLens's Discover settings for the test.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
