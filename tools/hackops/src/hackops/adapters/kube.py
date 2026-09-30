"""I/O-адаптеры: kubectl, HTTP, Prometheus и VictoriaLogs через API-прокси Kubernetes.

Доступ к Prometheus/VictoriaLogs идёт через `kubectl get --raw /api/v1/.../proxy/...` —
не нужны port-forward и открытые порты. Никакого shell=True, у всех вызовов есть таймауты.
"""
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class EnvError(RuntimeError):
    """Ошибка окружения (нет kubectl / недоступен кластер) — код возврата 2."""


def kubectl(*args: str, timeout: int = 60) -> str:
    try:
        p = subprocess.run(
            ["kubectl", *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as e:
        raise EnvError("kubectl не найден") from e
    except subprocess.TimeoutExpired as e:
        raise EnvError(f"kubectl {' '.join(args)}: таймаут") from e
    if p.returncode != 0:
        raise EnvError(f"kubectl {' '.join(args)}: {p.stderr.strip()[:300]}")
    return p.stdout


def kubectl_json(*args: str) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(kubectl(*args, "-o", "json"))
    return out


def http_get(
    url: str, headers: dict[str, str] | None = None, timeout: int = 10
) -> tuple[int, dict[str, str], str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (http, наш стенд)
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {}, str(e)


def prom_query(query: str) -> list[dict[str, Any]]:
    path = (
        "/api/v1/namespaces/monitoring/services/kps-prometheus:9090/proxy/api/v1/query?"
        + urllib.parse.urlencode({"query": query})
    )
    data = json.loads(kubectl("get", "--raw", path))
    if data.get("status") != "success":
        raise EnvError(f"Prometheus: {data}")
    result: list[dict[str, Any]] = data["data"]["result"]
    return result


def vl_query(query: str, limit: int = 20) -> list[dict[str, Any]]:
    path = (
        "/api/v1/namespaces/logging/services/victoria-logs:9428/proxy/select/logsql/query?"
        + urllib.parse.urlencode({"query": query, "limit": str(limit)})
    )
    out = kubectl("get", "--raw", path)
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows
