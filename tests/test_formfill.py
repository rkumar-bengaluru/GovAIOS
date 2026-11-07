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
