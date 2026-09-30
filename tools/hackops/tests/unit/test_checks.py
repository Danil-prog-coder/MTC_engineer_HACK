from hackops.core import checks
from hackops.core.checks import CheckResult, Report, Status


def test_condition_true():
    conds = [{"type": "Accepted", "status": "True"}, {"type": "Programmed", "status": "False"}]
    assert checks.condition_true(conds, "Accepted")
    assert not checks.condition_true(conds, "Programmed")
    assert not checks.condition_true(conds, "Missing")


def _route(accepted: str, resolved: str) -> dict:
    return {"status": {"parents": [{"conditions": [
        {"type": "Accepted", "status": accepted},
        {"type": "ResolvedRefs", "status": resolved},
    ]}]}}


def test_route_accepted():
    assert checks.route_accepted(_route("True", "True"))
    assert not checks.route_accepted(_route("True", "False"))
    assert not checks.route_accepted({"status": {}})   # нет родителей = не принят
    assert not checks.route_accepted({})


def test_images_without_pinned_tag():
    imgs = ["nginx:1.2", "foo/bar:latest", "baz", "reg:5000/x:1", "a/b@sha256:abc", "reg:5000/y"]
    assert checks.images_without_pinned_tag(imgs) == ["foo/bar:latest", "baz", "reg:5000/y"]


def test_report_exit_code():
    r = Report()
    r.add(CheckResult("R-1", "t", "cmd", Status.PASS))
    r.add(CheckResult("R-2", "t", "cmd", Status.SKIP))
    assert r.exit_code == 0
    r.add(CheckResult("R-3", "t", "cmd", Status.FAIL))
    assert r.exit_code == 1


def test_render_markdown_contains_evidence():
    r = Report()
    r.add(checks.check("R-06", "Hello", "curl x", True, "Hello World!"))
    md = checks.render_markdown(r, {"Узел": "1.2.3.4"})
    assert "R-06" in md and "Hello World!" in md and "1/1 PASS" in md
