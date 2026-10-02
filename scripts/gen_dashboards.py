#!/usr/bin/env python3
"""Генерация дашбордов Grafana (JSON) в k8s/base/monitoring/dashboards/. `make lint` проверяет, что вывод совпадает с git."""
from __future__ import annotations

import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "k8s/base/monitoring/dashboards"
DS = {"type": "prometheus", "uid": "prometheus"}


def panel(pid: int, title: str, exprs: list[tuple[str, str]], x: int, y: int, unit: str = "short",
          w: int = 12, h: int = 8, kind: str = "timeseries") -> dict:
    return {
        "id": pid, "type": kind, "title": title, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "targets": [{"datasource": DS, "expr": e, "legendFormat": legend, "refId": chr(65 + i)}
                    for i, (e, legend) in enumerate(exprs)],
    }


def dashboard(uid: str, title: str, panels: list[dict]) -> dict:
    return {
        "uid": uid, "title": title, "schemaVersion": 39, "version": 1, "editable": True,
        "refresh": "30s", "time": {"from": "now-1h", "to": "now"}, "tags": ["hello-platform"],
        "panels": panels,
    }


GATEWAY = dashboard("hello-gateway", "Hello Platform / Gateway (Envoy)", [
    panel(1, "Запросы в секунду", [("sum(rate(envoy_cluster_upstream_rq_total[1m]))", "rps")], 0, 0, "reqps"),
    panel(2, "Ответы по классам HTTP-кодов",
          [("sum by (envoy_response_code_class) (rate(envoy_cluster_upstream_rq_xx[1m]))", "{{envoy_response_code_class}}xx")],
          12, 0, "reqps"),
    panel(3, "Latency upstream p50/p95/p99",
          [(f"histogram_quantile({q}, sum by (le) (rate(envoy_cluster_upstream_rq_time_bucket[5m])))", f"p{int(q * 100)}")
           for q in (0.5, 0.95, 0.99)], 0, 8, "ms"),
    panel(4, "Активные соединения (downstream)",
          [("sum(envoy_http_downstream_cx_active)", "active")], 12, 8),
    panel(5, "Доля 5xx", [(
        'sum(rate(envoy_cluster_upstream_rq_xx{envoy_response_code_class="5"}[5m]))'
        " / clamp_min(sum(rate(envoy_cluster_upstream_rq_total[5m])), 1)", "5xx")], 0, 16, "percentunit"),
    panel(6, "CPU/RAM pod'ов Envoy",
          [('sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="gateway-system",container="envoy"}[5m]))', "cpu {{pod}}"),
           ('sum by (pod) (container_memory_working_set_bytes{namespace="gateway-system",container="envoy"})', "ram {{pod}}")],
          12, 16, "short"),
])

APP = dashboard("hello-app", "Hello Platform / Приложение и узел", [
    panel(1, "Экземпляры hello (up)", [('sum(up{job="hello"})', "up")], 0, 0, kind="stat", w=6, h=4),
    panel(2, "Перезапуски контейнеров",
          [('sum(kube_pod_container_status_restarts_total{namespace="hello"})', "restarts")], 6, 0, kind="stat", w=6, h=4),
    panel(3, "Pod'ы не Running", [('sum(kube_pod_status_phase{namespace=~"hello|monitoring|logging|gateway-system",phase!~"Running|Succeeded"})', "bad")],
          12, 0, kind="stat", w=6, h=4),
    panel(4, "Fluentd: событий в секунду",
          [("sum(rate(fluentd_output_status_num_records_total[1m]))", "records/s")], 18, 0, "ops", w=6, h=4),
    panel(5, "CPU pod'ов hello",
          [('sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="hello",container!=""}[5m]))', "{{pod}}")], 0, 4),
    panel(6, "RAM pod'ов hello",
          [('sum by (pod) (container_memory_working_set_bytes{namespace="hello",container!=""})', "{{pod}}")], 12, 4, "bytes"),
    panel(7, "CPU узла", [('1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))', "cpu")], 0, 12, "percentunit"),
    panel(8, "RAM узла", [("1 - sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)", "ram")], 12, 12,
          "percentunit"),
])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, d in (("gateway.json", GATEWAY), ("app.json", APP)):
        (OUT / name).write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
