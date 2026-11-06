import pytest

from govaios.audit.log import AuditLog
from govaios.delivery import Deliveries, build_payload, check_block

DESC = "d" * 300


def flow(deliver=None, allow=("deliver",), directory="jd_selected"):
    f = {"permissions": {"allow": list(allow)},
         "steps": [{"action": "for_each_item", "steps": [{"action": "write_json", "directory": directory}]}]}
    if deliver is not None:
        f["deliver"] = deliver
    return f


GOOD = {"to": "joblens", "from": "jd_selected", "source": "Himalayas"}


def test_check_block_none_without_deliver():
    assert check_block(flow()) is None


def test_check_block_accepts_himalayas_shape():
    assert check_block(flow(GOOD)) == GOOD


@pytest.mark.parametrize("block,allow,field", [
    ({**GOOD, "to": "other"}, ("deliver",), "to"),
    ({**GOOD, "url": "x"}, ("deliver",), "deliver"),
    ({**GOOD, "from": "elsewhere"}, ("deliver",), "from"),
    ({**GOOD, "source": ""}, ("deliver",), "source"),
    ({**GOOD, "source": "x" * 51}, ("deliver",), "source"),
    ({**GOOD, "source": "a\nb"}, ("deliver",), "source"),
    (GOOD, (), "permissions.allow"),
])
def test_check_block_refuses(block, allow, field):
    with pytest.raises(ValueError) as e:
        check_block(flow(block, allow))
    assert str(e.value) == field


def rec(**kw):
    return {"job_title": "Senior Dev", "company": "Acme", "description": DESC,
            "url": "https://himalayas.app/x", **kw}


def test_payload_maps_fields():
    p = build_payload(rec(job_title="  Senior\n  Dev "), "Himalayas")
    assert p == ({"title": "Senior Dev", "company": "Acme", "jd_text": DESC,
                  "url": "https://himalayas.app/x", "source": "Himalayas"}, None, None)


def test_payload_jd_limits():
    assert build_payload(rec(description="d" * 299), "S") == (None, "skipped_too_short", "jd_text")
    assert build_payload(rec(description="d" * 300), "S")[0]["jd_text"] == "d" * 300
    assert len(build_payload(rec(description="d" * 50000), "S")[0]["jd_text"]) == 50000
    assert build_payload(rec(description="d" * 50001), "S") == (None, "failed", "jd_text")


def test_payload_title_without_letters_fails():
    assert build_payload(rec(job_title="--- !!"), "S") == (None, "failed", "title")


def test_payload_bad_types_fail():
    assert build_payload(rec(company=5), "S") == (None, "failed", "company")


@pytest.mark.parametrize("url", ["javascript:x", None, "https://a b", "x" * 5, "http://[x"])
def test_payload_drops_bad_url(url):
    assert "url" not in build_payload(rec(url=url), "S")[0]


def test_payload_empty_company_left_out():
    assert "company" not in build_payload(rec(company="  "), "S")[0]


def test_deliveries_once(tmp_path):
    p = tmp_path / "deliveries.json"
    d = Deliveries(p)
    d.record("h", "delivered", 5)
    d.record("h2", "retry", None)
    d2 = Deliveries(p)
    assert d2.done("h") and not d2.done("h2") and not d2.done("h3")


def test_audit_accepts_delivery_entry(govaios_home):
    AuditLog(govaios_home).append("delivery", flow="f", target="joblens", file_hash="ab" * 32,
                                  response_code=202, listing_id=1, outcome="delivered")
