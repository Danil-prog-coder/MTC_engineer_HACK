"""CLI hackops: verify (F1), logs-find / logs-query. Коды возврата: 0 PASS, 1 FAIL, 2 ошибка окружения."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import socket
import sys
import time
import uuid

import typer

from hackops.adapters import kube
from hackops.core import checks
from hackops.core.checks import CheckResult, Report, Status, check

app = typer.Typer(add_completion=False, help="Hello Platform: проверки и отчёты")

NAMESPACES = ["hello", "monitoring", "logging", "gateway-system", "cert-manager"]


def _node_ip() -> str:
    import os

    if os.environ.get("NODE_IP"):
        return os.environ["NODE_IP"]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return str(s.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _wait_logs(query: str, want: int, timeout: int = 90) -> list[dict[str, object]]:
    deadline = time.time() + timeout
    rows: list[dict[str, object]] = []
    while time.time() < deadline:
        try:
            rows = kube.vl_query(query)
        except kube.EnvError:
            rows = []
        if len(rows) >= want:
            return rows
        time.sleep(3)
    return rows


def _os_release() -> str:
    try:
        text = pathlib.Path("/etc/os-release").read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return "unknown"


@app.command()
def verify(
    out_dir: pathlib.Path = typer.Option(pathlib.Path("artifacts"), help="Каталог отчёта"),
    node_ip: str = typer.Option("", help="IP узла (по умолчанию автоопределение)"),
) -> None:
    """Отчёт-доказательство: каждое требование кейса — реальный ответ с временной меткой."""
    ip = node_ip or _node_ip()
    base = f"http://{ip}:30080"
    rep = Report()
    try:
        _run_checks(rep, base)
    except kube.EnvError as e:
        typer.echo(f"Ошибка окружения: {e}", err=True)
        raise typer.Exit(2) from e

    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "Время": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%SZ"),
        "Узел": ip,
        "ОС": _os_release(),
    }
    md = checks.render_markdown(rep, meta)
    (out_dir / "verification-report.md").write_text(md, encoding="utf-8")
    (out_dir / "verification-report.json").write_text(
        json.dumps(
            [
                {"req": r.req, "title": r.title, "status": r.status.value, "command": r.command}
                for r in rep.results
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    for r in rep.results:
        typer.echo(f"[{r.status.value:4}] {r.req:5} {r.title}")
    typer.echo(f"\nОтчёт: {out_dir / 'verification-report.md'}")
    raise typer.Exit(rep.exit_code)


def _run_checks(rep: Report, base: str) -> None:
    # R-01/R-02: узлы и версия
    nodes = kube.kubectl_json("get", "nodes")["items"]
    ready = all(
        checks.condition_true(n["status"]["conditions"], "Ready") for n in nodes
    ) and bool(nodes)
    ver = ", ".join(f'{n["metadata"]["name"]}={n["status"]["nodeInfo"]["kubeletVersion"]}' for n in nodes)
    rep.add(check("R-01/R-02", "Узлы kubeadm-кластера Ready", "kubectl get nodes -o wide", ready, ver))

    rep.add(check("R-18", "ОС Ubuntu 24.04", "lsb_release -a", "24.04" in _os_release(), _os_release()))

    # состояние подов
    bad, total = [], 0
    for ns in NAMESPACES:
        for p in kube.kubectl_json("get", "pods", "-n", ns)["items"]:
            total += 1
            phase = p["status"].get("phase")
            if phase not in ("Running", "Succeeded"):
                bad.append(f'{ns}/{p["metadata"]["name"]}={phase}')
            elif phase == "Running" and not all(
                c.get("ready") for c in p["status"].get("containerStatuses", [])
            ):
                bad.append(f'{ns}/{p["metadata"]["name"]}=NotReady')
    rep.add(check("R-01", "Все поды решения Running/Ready", "kubectl get pods -A", not bad and total > 0,
                  f"pods={total}; проблемные: {bad or 'нет'}"))

    # R-09: Gateway API
    gc = kube.kubectl_json("get", "gatewayclass", "eg")
    rep.add(check("R-09", "GatewayClass Accepted", "kubectl get gatewayclass",
                  checks.condition_true(gc["status"]["conditions"], "Accepted"),
                  json.dumps(gc["status"]["conditions"], ensure_ascii=False)))
    gw = kube.kubectl_json("get", "gateway", "public-gw", "-n", "gateway-system")
    rep.add(check("R-09", "Gateway Programmed", "kubectl get gateway -A",
                  checks.condition_true(gw["status"]["conditions"], "Programmed"),
                  json.dumps(gw["status"]["conditions"], ensure_ascii=False)))
    routes = kube.kubectl_json("get", "httproute", "-A")["items"]
    ok_routes = bool(routes) and all(checks.route_accepted(r) for r in routes)
    rep.add(check("R-09", "HTTPRoute Accepted и ResolvedRefs", "kubectl get httproute -A", ok_routes,
                  "; ".join(f'{r["metadata"]["namespace"]}/{r["metadata"]["name"]}' for r in routes)))

    # R-06/R-11: Hello World
    code, _, body = kube.http_get(f"{base}/")
    rep.add(check("R-06/R-11", "GET / через Gateway -> Hello World!", f"curl {base}/",
                  code == 200 and body.strip() == "Hello World!", f"HTTP {code}\n{body}"))

    # R-16 + F2: сквозной request_id
    marker = f"verify-{uuid.uuid4()}"
    code, hdrs, body = kube.http_get(f"{base}/", {"X-Request-Id": marker})
    rep.add(check("F2", "X-Request-Id возвращается клиентом", f'curl -si -H "X-Request-Id: {marker}" {base}/',
                  hdrs.get("x-request-id") == marker, f"HTTP {code}; X-Request-Id={hdrs.get('x-request-id')}"))
    rows = _wait_logs(f'request_id:"{marker}"', want=2)
    types = sorted({str(r.get("log_type")) for r in rows})
    rep.add(check("R-14/R-15/R-16/F2", "Запрос найден в логах: gateway_access + access (один request_id)",
                  f"make logs-find ID={marker}",
                  "gateway_access" in types and "access" in types,
                  json.dumps(rows, ensure_ascii=False, indent=1)[:2500]))

    # R-14: error-лог
    kube.http_get(f"{base}/__error_demo", {"X-Request-Id": marker + "-err"})
    erows = _wait_logs("log_type:error _time:10m", want=1, timeout=60)
    rep.add(check("R-14", "error-лог приложения собран", "make logs-query Q='log_type:error'",
                  bool(erows), json.dumps(erows[:1], ensure_ascii=False)[:1000]))

    # R-12: Prometheus
    up = kube.prom_query("up")
    down = [f'{s["metric"].get("job")}/{s["metric"].get("instance")}' for s in up if s["value"][1] != "1"]
    jobs = sorted({s["metric"].get("job", "") for s in up})
    rep.add(check("R-12", "Все Prometheus targets up", "sum by (job) (up)", bool(up) and not down,
                  f"targets={len(up)}; jobs={jobs}; down={down or 'нет'}"))
    hello_up = kube.prom_query('sum(up{job="hello"})')
    rep.add(check("R-12", "Метрики приложения (Angie) собираются", 'sum(up{job="hello"})',
                  bool(hello_up) and float(hello_up[0]["value"][1]) >= 1, json.dumps(hello_up)))
    envoy_rq = kube.prom_query("sum(envoy_cluster_upstream_rq_total)")
    rep.add(check("R-12", "Метрики Gateway (Envoy) содержат запросы", "sum(envoy_cluster_upstream_rq_total)",
                  bool(envoy_rq) and float(envoy_rq[0]["value"][1]) > 0, json.dumps(envoy_rq)))

    # R-08/R-24: теги образов
    pods = [p for ns in NAMESPACES for p in kube.kubectl_json("get", "pods", "-n", ns)["items"]]
    images = sorted({c["image"] for p in pods for c in p["spec"]["containers"]})
    unpinned = checks.images_without_pinned_tag(images)
    rep.add(check("R-08", "Все образы с фиксированным тегом (нет latest)", "kubectl get pods -A -o jsonpath=...image",
                  not unpinned, f"образов={len(images)}; без тега: {unpinned or 'нет'}"))

    # R-20: идемпотентность (результат make idempotency-check)
    idem = pathlib.Path("artifacts/idempotency.json")
    if idem.exists():
        d = json.loads(idem.read_text(encoding="utf-8"))
        rep.add(check("R-20", "Повторный запуск: changed=0", "make idempotency-check", d.get("changed") == 0,
                      json.dumps(d)))
    else:
        rep.add(CheckResult("R-20", "Повторный запуск: changed=0", "make idempotency-check", Status.SKIP,
                            "ещё не запускался: выполните make idempotency-check"))


@app.command("logs-find")
def logs_find(id: str = typer.Argument(..., help="request_id")) -> None:
    """Найти все записи логов по request_id."""
    try:
        rows = kube.vl_query(f'request_id:"{id}"')
    except kube.EnvError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e
    for r in rows:
        typer.echo(json.dumps(r, ensure_ascii=False))
    typer.echo(f"найдено записей: {len(rows)}", err=True)
    raise typer.Exit(0 if rows else 1)


@app.command("logs-query")
def logs_query(q: str = typer.Argument(..., help="запрос LogsQL")) -> None:
    """Произвольный запрос LogsQL к VictoriaLogs."""
    try:
        rows = kube.vl_query(q, limit=50)
    except kube.EnvError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e
    for r in rows:
        typer.echo(json.dumps(r, ensure_ascii=False))
    raise typer.Exit(0)


def main() -> None:
    app()


if __name__ == "__main__":
    sys.exit(main())
