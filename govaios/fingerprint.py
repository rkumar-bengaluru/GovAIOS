"""A per-round commitment to an item's identity, so audit entries never carry the item's text."""
import hashlib
import unicodedata


def norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def of(run: str, round_no: int, identity: str) -> str:
    return hashlib.sha256(f"{run}\0{round_no}\0{norm(identity)}".encode()).hexdigest()
