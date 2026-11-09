"""Per-domain site-terms verdicts (allowed/forbidden/unclear) that gate lessons."""
import ipaddress
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
    host = (urlsplit(url).hostname or "").rstrip(".")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    parts = host.split(".")
    # shortcut: no public-suffix list, add one when a site is misjudged
    n = 3 if len(parts) > 2 and len(parts[-2]) <= 3 and len(parts[-1]) == 2 else 2
    return ".".join(parts[-n:])


def _store(home):
    s = applyfiles.read_json(home, TERMS)
    return s if isinstance(s, dict) else {}


def verdict(home, url, declared):
    """'allowed' for localhost or a declared origin, else the stored verdict if under 90 days old, else None."""
    if urlsplit(url).hostname in ("localhost", "127.0.0.1") or origin(url) in declared:
        return "allowed"
    d = domain(url)
    e = _store(home).get(d) if d else None
    try:
        # a future date is refused too, or a bad clock would make it fresh forever
        if timedelta(0) <= _today() - date.fromisoformat(e["date"]) < MAX_AGE and e["value"] in VERDICTS:
            return e["value"]
    except (KeyError, TypeError, ValueError):
        pass
    return None


def record(home, url, value, link, clause):
    """Store a verdict with the terms link and the clause it rests on."""
    if value not in VERDICTS:
        raise ValueError("verdict must be allowed, forbidden or unclear")
    if not isinstance(url, str) or urlsplit(url).scheme not in ("http", "https") or not domain(url):
        raise ValueError("url must be http(s) with a host")
    if not isinstance(link, str) or urlsplit(link).scheme != "https" or not urlsplit(link).netloc:
        raise ValueError("terms link must be https")
    if not isinstance(clause, str) or len(clause) > 2000:
        raise ValueError("clause must be a string up to 2000 chars")
    store = _store(home)
    store[domain(url)] = {"value": value, "link": link, "clause": clause, "date": _today().isoformat()}
    applyfiles.write_json(home, TERMS, store)
