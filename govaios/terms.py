"""Per-domain site-terms verdicts (allowed/forbidden/unclear) that gate lessons."""
from datetime import date, timedelta
from urllib.parse import urlsplit

from govaios import applyfiles
from govaios.policy import origin

TERMS = "terms.json"
VERDICTS = ("allowed", "forbidden", "unclear")
MAX_AGE = timedelta(days=90)
_today = date.today   # patched in tests


def domain(url):
    """Registrable-ish domain, so a company's subdomains share one verdict."""
    parts = (urlsplit(url).hostname or "").split(".")
    # shortcut: no public-suffix list, add one when a site is misjudged
    n = 3 if len(parts) > 2 and len(parts[-2]) <= 3 and len(parts[-1]) == 2 else 2
    return ".".join(parts[-n:])


def verdict(home, url, declared):
    """'allowed' for localhost or a declared origin, else the stored verdict if under 90 days old, else None."""
    if urlsplit(url).hostname in ("localhost", "127.0.0.1") or origin(url) in declared:
        return "allowed"
    e = (applyfiles.read_json(home, TERMS) or {}).get(domain(url))
    try:
        if e and _today() - date.fromisoformat(e["date"]) < MAX_AGE:
            return e["value"] if e["value"] in VERDICTS else None
    except (KeyError, TypeError, ValueError):
        pass
    return None


def record(home, url, value, link, clause):
    """Store a verdict with the terms link and the clause it rests on."""
    if value not in VERDICTS:
        raise ValueError("verdict must be allowed, forbidden or unclear")
    if urlsplit(link).scheme != "https":
        raise ValueError("terms link must be https")
    if len(clause) > 2000:
        raise ValueError("clause too long")
    store = applyfiles.read_json(home, TERMS) or {}
    store[domain(url)] = {"value": value, "link": link, "clause": clause, "date": _today().isoformat()}
    applyfiles.write_json(home, TERMS, store)
