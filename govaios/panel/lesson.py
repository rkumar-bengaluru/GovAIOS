"""The "What I learned" page: one section per page of a lesson, its step lines and bank lines, and the admin's edits.
Every value is the admin's own (dev mode, unmasked) but comes from a web page: escaped wherever it is shown."""
import hashlib
import json
import re
from html import escape

from govaios import lessons

KEEPS = (("bank", "Keep in bank"), ("job", "This job only"), ("drop", "Don't keep"))
WORDS = {"click": "Click", "fill_form": "Fill the form from the bank", "attach_file": "Attach your CV",
         "hand_over": "Hand over: you check and submit", "hand_fill": "You fill this yourself"}


def digest(proposal):
    """Binds the approval to the proposal the admin saw."""
    return hashlib.sha256(json.dumps(proposal, sort_keys=True, default=str).encode()).hexdigest()[:16]


def edits(proposal, form):
    """(deleted {(page, line)}, keeps {bank line: keep}) from the posted form; ValueError on anything else."""
    deleted, keeps = set(), {}
    for k, v in form.items():
        if k in ("csrf", "name", "p"):
            continue
        d, b = re.fullmatch(r"del:([0-9]{1,3}):([0-9]{1,3})", k), re.fullmatch(r"keep:([0-9]{1,3})", k)
        if d and v == "1" and int(d[1]) < len(proposal["pages"]) \
                and int(d[2]) < len(proposal["pages"][int(d[1])]["steps"]):
            deleted.add((int(d[1]), int(d[2])))
        elif b and int(b[1]) < len(proposal["bank"]) and v in dict(KEEPS):
            keeps[int(b[1])] = v
        else:
            raise ValueError("unknown field")
    return deleted, keeps


def _bank_line(i, o):
    k, lab, val = escape(o["key"]), escape(o["label"][:300]), escape(o["value"][:300])
    what = {"add": f"New key <code>{k}</code> = “{val}” (label “{lab}”)",
            "label": f"Add label “{lab}” to <code>{k}</code>",
            "change": f"Change <code>{k}</code> to “{val}” (label “{lab}”)"}.get(o["op"], "?")
    opts = "".join(f"<option value={v}{' selected' if v == o['keep'] else ''}>{t}</option>" for v, t in KEEPS)
    tag = " <b>sensitive</b>" if o.get("sensitive") else ""
    return (f"<li>{what}{tag} <label class=vh for=keep{i}>Keep</label>"
            f"<select id=keep{i} name='keep:{i}'>{opts}</select></li>")


def page(name, lesson, proposal, flow_cases, others, hidden):
    """The page body. flow_cases: page ids the flow's step already handles (their steps are not added);
    others: {known page gaining elements: names of the other apps that use it}."""
    secs = []
    for i, p in enumerate(proposal["pages"]):
        lp = lesson["pages"][i] if i < len(lesson["pages"]) else {}
        rows = []
        for j, s in enumerate(p["steps"]):
            text = f"{WORDS.get(s['kind'], escape(s['kind']))}: {escape(str(s.get('label'))[:200])}"
            if s["kind"] == "hand_fill" or not s["keep"]:
                note = " (not replayed)" if s["kind"] != "hand_fill" else ""
                rows.append(f"<li>{text}{note}</li>")
            else:
                rows.append(f"<li>{text} <label><input type=checkbox name='del:{i}:{j}' value=1> Delete</label></li>")
        added = (f"<p class=m>Adds to this page: {escape(', '.join(p['added']))}</p>" if p["added"] else "")
        handled = ("<p class=note>The flow already handles this page: these steps are not added.</p>"
                   if p["id"] in flow_cases else "")
        if others.get(p["id"]):
            handled += (f"<p class=note>Changing this page means approving again: "
                        f"{escape(', '.join(others[p['id']]))}.</p>")
        secs.append(f"<section class=appcard><h2><code>{escape(p['id'])}</code> · {'new' if p['new'] else 'known'}"
                    f"</h2><p class=m>{escape(str(lp.get('title') or '')[:200])} "
                    f"<code>{escape(str(lp.get('url') or '')[:200])}</code></p>{added}{handled}"
                    f"<ol>{''.join(rows)}</ol></section>")
    last = proposal["pages"][-1] if proposal["pages"] else None
    if last and lesson.get("flow") not in lessons.SANDBOX and (last["id"] in flow_cases or not any(
            s["keep"] and lessons._do(s, last) for s in last["steps"])):
        secs.append("<p class=note>The last page gets no steps, so the run does not end there: it looks at the "
                    "page again and stops if it does not know it.</p>")
    bank = "".join(_bank_line(i, o) for i, o in enumerate(proposal["bank"])) \
        if lesson.get("flow") not in lessons.SANDBOX else ""   # a sandbox lesson writes pages only
    bank = f"<h2>Answer bank</h2><ul>{bank}</ul>" if bank else ""
    flow = escape(str(lesson.get("flow") or "Studio"))
    return (f"<h1>What I learned</h1><p class=m>Lesson <code>{escape(name)}</code> for <b>{flow}</b>. Nothing changes "
            f"until you approve it with Touch ID.</p>"
            f"<form method=post action=/lesson/approve>{hidden}<input type=hidden name=name value='{escape(name)}'>"
            f"<input type=hidden name=p value='{digest(proposal)}'>{''.join(secs)}{bank}"
            f"<p><button class=go>Approve with Touch ID</button></p></form>"
            f"<form method=post action=/lesson/discard>{hidden}<input type=hidden name=name value='{escape(name)}'>"
            f"<button>Discard</button></form>")
