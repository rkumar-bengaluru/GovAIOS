import base64, hashlib, json, re
from pathlib import Path

EXT = Path(__file__).resolve().parent.parent / "extension"
manifest = lambda: json.loads((EXT / "manifest.json").read_text())


def ext_id():
    der = base64.b64decode(manifest()["key"], validate=True)
    return hashlib.sha256(der).hexdigest()[:32].translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))


def test_host_permissions_exact():
    assert manifest()["host_permissions"] == ["http://127.0.0.1:8765/*", "http://localhost/*", "http://127.0.0.1/*"]


def test_key_is_base64_and_no_content_scripts():
    base64.b64decode(manifest()["key"], validate=True)
    assert "content_scripts" not in manifest()


def test_content_js_reads_no_form_data_and_has_no_message_listener():
    src = (EXT / "content.js").read_text()
    for bad in (".value", "innerHTML", 'addEventListener("message"', "addEventListener('message'"):
        assert bad not in src


def test_js_talks_only_to_the_panel():
    for f in EXT.glob("*.js"):
        for url in re.findall(r"https?://[^\s\"'`]+", f.read_text()):
            assert url.startswith("http://127.0.0.1:8765"), (f.name, url)


def test_id_in_readme():
    assert ext_id() in (EXT / "README.md").read_text()


def test_no_private_key_in_extension():
    for f in EXT.rglob("*"):
        if f.is_file():
            assert "PRIVATE KEY" not in f.read_text(errors="ignore"), f


def test_content_js_trusts_only_real_presses_and_climbs_like_the_recorder():
    src = (EXT / "content.js").read_text()
    assert "isTrusted" in src
    assert 'closest("a,button,[role=button],[role=tab],[role=link],[role=radio],summary")' in src
