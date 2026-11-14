from govaios import fingerprint


def test_norm_and_of():
    assert fingerprint.norm("  Ada  LOVELACE ") == "ada lovelace"
    assert fingerprint.of("r1", 1, "Ada Lovelace") == fingerprint.of("r1", 1, " ada  lovelace")
    assert len(fingerprint.of("r1", 1, "Ada")) == 64
    assert fingerprint.of("r1", 1, "Ada") != fingerprint.of("r2", 1, "Ada")
    assert fingerprint.of("r1", 1, "Ada") != fingerprint.of("r1", 2, "Ada")
