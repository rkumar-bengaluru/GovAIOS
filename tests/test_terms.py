import os
from datetime import date, timedelta

import pytest

from govaios import terms


def test_domain_groups_company_subdomains():
    assert terms.domain("https://fa-ewji-saasfaprod1.fa.ocs.oraclecloud.com/x") == "oraclecloud.com"
    assert terms.domain("https://a.co.uk") == "a.co.uk"


def test_verdict_expires_after_90_days(tmp_path, monkeypatch):
    terms.record(tmp_path, "https://x.com/a", "allowed", "https://x.com/t", "ok")
    assert terms.verdict(tmp_path, "https://www.x.com", []) == "allowed"
    assert oct(os.stat(tmp_path / "terms.json").st_mode & 0o777) == "0o600"
    monkeypatch.setattr(terms, "_today", lambda: date.today() + timedelta(days=91))
    assert terms.verdict(tmp_path, "https://x.com", []) is None


def test_localhost_and_declared_need_no_check(tmp_path):
    assert terms.verdict(tmp_path, "http://localhost:8000/", []) == "allowed"
    assert terms.verdict(tmp_path, "http://127.0.0.1/", []) == "allowed"
    assert terms.verdict(tmp_path, "https://himalayas.app/jobs", ["https://himalayas.app"]) == "allowed"
    assert terms.verdict(tmp_path, "https://other.app/", ["https://himalayas.app"]) is None


def test_unclear_is_not_allowed(tmp_path):
    terms.record(tmp_path, "https://y.com", "unclear", "https://y.com/t", "")
    assert terms.verdict(tmp_path, "https://y.com", []) == "unclear"


def test_record_refuses_bad_input(tmp_path):
    for args in (("maybe", "https://y.com/t", ""), ("allowed", "http://y.com/t", ""), ("allowed", "https://y.com/t", "x" * 2001)):
        with pytest.raises(ValueError):
            terms.record(tmp_path, "https://y.com", *args)


def _age(tmp_path, monkeypatch, days):
    monkeypatch.setattr(terms, "_today", date.today)
    terms.record(tmp_path, "https://x.com", "allowed", "https://x.com/t", "")
    monkeypatch.setattr(terms, "_today", lambda: date.today() + timedelta(days=days))
    return terms.verdict(tmp_path, "https://x.com", [])


def test_expiry_boundaries(tmp_path, monkeypatch):
    assert _age(tmp_path, monkeypatch, 89) == "allowed"
    assert _age(tmp_path, monkeypatch, 90) is None
    assert _age(tmp_path, monkeypatch, -1) is None   # future-dated record


def test_domain_edges():
    assert terms.domain("https://x.com./a") == "x.com"
    assert terms.domain("http://10.1.2.3/") == "10.1.2.3"
    assert terms.domain("http://10.9.2.3/") != terms.domain("http://10.1.2.3/")
    assert terms.domain("/nohost") == ""


def test_non_dict_store_and_bad_entry(tmp_path):
    (tmp_path / "terms.json").write_text("[1]")
    assert terms.verdict(tmp_path, "https://x.com", []) is None
    terms.record(tmp_path, "https://x.com", "forbidden", "https://x.com/t", "")
    assert terms.verdict(tmp_path, "https://x.com", []) == "forbidden"
    (tmp_path / "terms.json").write_text('{"x.com": 5}')
    assert terms.verdict(tmp_path, "https://x.com", []) is None


def test_record_refuses_bad_url_and_link(tmp_path):
    for url, link in (("ftp://x.com", "https://x.com/t"), ("/nohost", "https://x.com/t"), (5, "https://x.com/t"), ("https://x.com", "https:"), ("https://x.com", None)):
        with pytest.raises(ValueError):
            terms.record(tmp_path, url, "allowed", link, "")


def test_localhost_lookalike_is_not_local(tmp_path):
    assert terms.verdict(tmp_path, "http://localhost.evil.com", []) is None
