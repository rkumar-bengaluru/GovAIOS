import os
import pytest
import yaml
from govaios import formfill as ff

GOOD = {"cv_file": "~/cv.pdf", "answers": [
    {"key": "notice_period", "labels": ["Notice period"], "answer": "30 days"}]}


def _write(tmp_path, text):
    d = tmp_path / "apply"
    d.mkdir(exist_ok=True)
    p = d / "answers.yaml"
    p.write_text(text)
    return p


def test_normalize():
    assert ff.normalize("What is your official notice period?*") == "what is your official notice period"
    assert ff.normalize("Full name ✱") == "full name"
    assert ff.normalize("  E-mail  ") == "e mail"


def test_load_bank_ok_and_missing(tmp_path):
    assert ff.load_bank(tmp_path / "apply" / "answers.yaml", tmp_path) == ff.Bank()
    b = ff.load_bank(_write(tmp_path, yaml.safe_dump(GOOD)), tmp_path)
    assert b.cv_file == "~/cv.pdf"
    assert b.entries == (ff.Entry("notice_period", ("Notice period",), "30 days"),)


def _e(**kw):
    e = {"key": "k", "labels": ["l"], "answer": "SECRET-ANSWER"}
    e.update(kw)
    return yaml.safe_dump({"answers": [e]})


@pytest.mark.parametrize("text", [
    _e(key="Bad Key"),
    yaml.safe_dump({"answers": [{"key": "k", "labels": ["l"], "answer": "SECRET-ANSWER"}] * 2}),
    _e(labels=["x" * 301]),
    "- just\n- a list\n",
    "answers:\n  - key: k\n    answer: [SECRET-ANSWER\n",
    _e(answer="SECRET-ANSWER\x07"),
])
def test_load_bank_rejects(tmp_path, text):
    with pytest.raises(ff.BankError) as ei:
        ff.load_bank(_write(tmp_path, text), tmp_path)
    assert "SECRET-ANSWER" not in str(ei.value)


def test_load_bank_refuses_symlinks(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "answers.yaml").write_text(yaml.safe_dump(GOOD))
    (tmp_path / "apply").symlink_to(real)
    with pytest.raises(ff.BankError):
        ff.load_bank(tmp_path / "apply" / "answers.yaml", tmp_path)


def test_ok_value():
    assert ff.ok_value("a\nb", "textarea") and not ff.ok_value("a\nb", "text")
    for k in ("text", "textarea"):
        assert not ff.ok_value("a\tb", k) and not ff.ok_value("a\x00", k)
        assert not ff.ok_value("a\x7f", k)


def test_cv_path(tmp_path):
    (tmp_path / "cv.pdf").write_bytes(b"x")
    (tmp_path / "cv.txt").write_bytes(b"x")
    (tmp_path / "d.pdf").mkdir()
    (tmp_path / "ln.pdf").symlink_to(tmp_path / "cv.pdf")
    out = tmp_path.parent / "outside.pdf"
    out.write_bytes(b"x")
    cv = lambda f: ff.cv_path(ff.Bank(cv_file=f), tmp_path)
    assert cv("~/cv.pdf") == tmp_path / "cv.pdf"
    for bad in ("~/ln.pdf", "~/d.pdf", "~/cv.txt", str(out), "~/missing.pdf"):
        assert cv(bad) is None
    assert ff.cv_path(ff.Bank(), tmp_path) is None


def test_restricted():
    import re
    hit = lambda k, s: re.search(ff.RESTRICTED[k], ff.normalize(s), re.I)
    assert hit("sensitive", "Passport number") and hit("demographic", "Gender")
    assert hit("consent", "I agree to the terms") and not hit("sensitive", "Full name")


def test_add_answer_keys_and_mode(tmp_path):
    p = tmp_path / "apply" / "answers.yaml"
    assert ff.add_answer(p, "Notice period?", "30 days") == "notice_period"
    assert ff.add_answer(p, "Notice period", "60 days") == "notice_period_2"
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    b = ff.load_bank(p, tmp_path)
    assert [e.answer for e in b.entries] == ["30 days", "60 days"]
    with pytest.raises(ff.BankError):
        ff.add_answer(p, "x", "a\tb")


def test_add_answer_refuses_what_load_would_reject(tmp_path):
    p = tmp_path / "apply" / "answers.yaml"
    with pytest.raises(ff.BankError):
        ff.add_answer(p, "x" * 301, "a")
    assert not p.exists()
    rows = [{"key": f"k{i}", "labels": ["l"], "answer": "a"} for i in range(300)]
    _write(tmp_path, yaml.safe_dump({"answers": rows}))
    before = p.read_text()
    with pytest.raises(ff.BankError):
        ff.add_answer(p, "one more", "a")
    assert p.read_text() == before
    assert len(ff.load_bank(p, tmp_path).entries) == 300


# ---- reading a form (Task 3) ----
from govaios.desktop import Node


def N(role, name="", *children, value="", dom_id=""):
    return Node(role=role, name=name, value=value, dom_id=dom_id, children=list(children))


def test_greenhouse_shape():
    r = N("group", "",
          N("group", "", N("text", "First Name *"), dom_id="first_name-label"),
          N("text_field", "First Name *", dom_id="first_name"),
          N("combo_box", "What is your official notice period?", dom_id="question_1"),
          N("button", "Submit application"))
    fs = ff.read_form(r)
    assert [(f.kind, f.label, f.key) for f in fs] == [
        ("text", "First Name", "#first_name"),
        ("combo", "What is your official notice period?", "#question_1")]


def test_lever_unnamed_question_takes_group_text():
    r = N("group", "", N("group", "", N("group", "", N("text", "What is your current salary?"), N("text", "✱"))),
          N("group", "", N("text_field")))
    fs = ff.read_form(r)
    assert len(fs) == 1 and fs[0].label == "What is your current salary?"
    assert fs[0].key == "label:what is your current salary:0"


def test_radio_group_one_field():
    radios = [N("group", "", N("radio", n), N("text", n)) for n in ("Immediate", "15 Days", "30 Days", "60 Days")]
    r = N("group", "", N("group", "", N("text", "Notice period")), N("group", "", *radios))
    fs = ff.read_form(r)
    assert len(fs) == 1 and fs[0].kind == "radio" and fs[0].label == "Notice period"
    assert fs[0].options == ("Immediate", "15 Days", "30 Days", "60 Days") and not fs[0].filled
    assert ff.locate(r, fs[0]) is r.children[1]


def test_pronoun_checkboxes_are_multi_and_restricted():
    r = N("group", "", N("group", "", N("text", "Pronouns")),
          N("group", "", *[N("checkbox", n) for n in ("He/him", "She/her", "They/them")]),
          )
    fs = ff.read_form(r)
    assert [f.kind for f in fs] == ["multi"] and fs[0].label == "Pronouns"
    assert [f.kind for f in ff.read_form(N("group", "", N("checkbox", "I agree")))] == ["checkbox"]
    assert ff.restricted(fs[0]) == "demographic"


@pytest.mark.parametrize("label,expected", [
    ("Password", "sensitive"), ("Gender", "demographic"),
    ("I certify that the above is true", "consent"), ("Veteran status", "demographic"),
    ("Notice period", None)])
def test_restricted_patterns(label, expected):
    assert ff.restricted(ff.Field("k", label, "text", (), False)) == expected
    assert ff.restricted(ff.Field("k", "x", "other", (), False)) == "secure"


def _bank(*pairs):
    return ff.Bank(tuple(ff.Entry(k, tuple(ls), a) for k, ls, a in pairs))


def _f(label, kind="text", options=(), filled=False):
    return ff.Field("#" + label, label, kind, options, filled)


def test_answer_for_exact_and_ambiguous():
    f = _f("Notice period")
    assert ff.answer_for(f, _bank(("notice", ["notice period?"], "30 days")), [f]) == ("30 days", "bank:notice")
    assert ff.answer_for(f, _bank(("a", ["Notice period"], "1"), ("b", ["notice period"], "2")), [f]) is None
    g = ff.Field("#2", "notice period", "text", (), False)
    b = _bank(("a", ["Notice period"], "1"))
    assert ff.answer_for(f, b, [f, g]) is None and ff.answer_for(g, b, [f, g]) is None
    assert ff.answer_for(_f("Other"), b, [_f("Other")]) is None


def test_answer_for_choice_must_match_option():
    f = _f("Notice period", "radio", ("Immediate", "30 Days"))
    assert ff.answer_for(f, _bank(("notice", ["Notice period"], "30 days")), [f]) == ("30 Days", "bank:notice")
    assert ff.answer_for(f, _bank(("notice", ["Notice period"], "60 days")), [f]) is None


def test_filled_field_never_answered():
    f = _f("Notice period", filled=True)
    assert ff.answer_for(f, _bank(("n", ["Notice period"], "x")), [f]) is None
    r = N("group", "", N("text_field", "A", value="v", dom_id="a"), N("popup_button", "S", N("native:AXMenuItem", "-"),
          N("native:AXMenuItem", "x"), value="x", dom_id="s"), N("native:AXSecureTextField", "Pw", dom_id="pw"))
    fs = ff.read_form(r)
    assert [(f.kind, f.filled) for f in fs] == [("text", True), ("select", True), ("other", False)]
    assert fs[1].options == ("-", "x")


def test_newline_answer_only_for_textarea():
    b = _bank(("n", ["About"], "a\nb"))
    assert ff.answer_for(_f("About", "textarea"), b, [_f("About", "textarea")]) == ("a\nb", "bank:n")
    assert ff.answer_for(_f("About"), b, [_f("About")]) is None


def test_locate_finds_by_key_in_new_tree():
    def tree():
        return N("group", "", N("text_field", "A", dom_id="a"), N("text_field", "", dom_id="b"))
    f = ff.read_form(tree())[1]
    t2 = tree()
    assert ff.locate(t2, f) is t2.children[1]
    assert ff.locate(t2, ff.Field("#zz", "", "text", (), False)) is None


def test_question_scan_stops_at_field_bearing_sibling():
    r = N("group", "", N("group", "", N("text", "Q1")),
          N("group", "", N("text_field", "Email", dom_id="e")),
          N("group", "", N("text_field")))
    assert [f.label for f in ff.read_form(r)] == ["Email", ""]


def test_twin_siblings_resolve_by_identity():
    t = N("group", "", N("group", "", N("text", "X")), N("text_field"), N("text_field"))
    assert [f.label for f in ff.read_form(t)] == ["X", ""]


def test_option_with_control_char_not_returned():
    f = _f("Notice period", "radio", ("Immediate", "30\x07 Days"))
    assert ff.answer_for(f, _bank(("n", ["Notice period"], "30 days")), [f]) is None
