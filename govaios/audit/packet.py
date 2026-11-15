"""Proof packet: one run's signed entries plus the flow's approval context, verifiable with verify.py --packet."""
from govaios.audit.verify import CONTEXT

NOTE = "Fingerprints are commitments: anyone who can guess the item's name can confirm it."


def build(entries: list[dict], run_id: str, export_entry: dict, pubkey_pem: str) -> dict:
    mine = [e for e in entries if e.get("run") == run_id and isinstance(e.get("run_seq"), int)]
    flow_hash = next((e.get("flow_hash") for e in mine if e["kind"] == "flow_start"), None)
    context = []
    for kind, field, val in CONTEXT:
        hit = [e for e in entries if e["kind"] == kind and e.get(field) == val and e.get("flow_hash") == flow_hash]
        if hit and not any(hit[-1] is m for m in mine):
            context.append(hit[-1])
    return {"format": "govaios-proof-1", "run": run_id, "entries": mine, "context": context,
            "export": export_entry, "pubkey": pubkey_pem, "note": NOTE}
