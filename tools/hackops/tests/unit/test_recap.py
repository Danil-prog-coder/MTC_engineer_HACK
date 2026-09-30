from hackops.core import recap

RECAP = """
PLAY RECAP *********************************************************************
node1                      : ok=87   changed=0    unreachable=0    failed=0    skipped=12   rescued=0    ignored=0
"""


def test_parse_recap_idempotent():
    r = recap.parse_recap(RECAP)
    assert r == {"ok": 87, "changed": 0, "unreachable": 0, "failed": 0}
    assert recap.is_idempotent(r)


def test_parse_recap_changed():
    r = recap.parse_recap(RECAP.replace("changed=0", "changed=3"))
    assert r["changed"] == 3
    assert not recap.is_idempotent(r)


def test_parse_recap_missing_is_not_idempotent():
    r = recap.parse_recap("ERROR! something")
    assert r["ok"] == -1
    assert not recap.is_idempotent(r)


def test_parse_recap_sums_hosts():
    two = RECAP + "node2 : ok=5 changed=1 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0\n"
    assert recap.parse_recap(two)["changed"] == 1
