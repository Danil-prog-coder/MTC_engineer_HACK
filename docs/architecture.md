# Архитектура Hello Platform

## Состав и namespace

| Namespace | Роль (модель ролей Gateway API) | Содержимое | Pod Security (enforce) |
|---|---|---|---|
| `gateway-system` | Провайдер инфраструктуры / оператор кластера | Envoy Gateway (controller), Envoy Proxy ×2, `EnvoyProxy`, `GatewayClass`, `Gateway` | baseline |
| `hello` | Разработчик приложения | Deployments `hello-v1`/`hello-v2`, Services, `HTTPRoute`, PDB, NetworkPolicy | **restricted** |
| `monitoring` | Платформа | kube-prometheus-stack, ServiceMonitor/PodMonitor/PrometheusRule | privileged (node-exporter) |
| `logging` | Платформа | Fluentd (DaemonSet), VictoriaLogs | privileged (чтение `/var/log` узла) |
| `cert-manager` | Платформа | cert-manager (пока без Certificate) | baseline |
| `kube-system`, `tigera-operator`, `calico-*`, `local-path-storage` | Системные | kubeadm, Calico, local-path-provisioner | — |

`Gateway/public-gw` допускает маршруты только из namespace с меткой `gateway-access: "true"` (сейчас — `hello`):
команда приложения не может «захватить» чужой listener.

## Путь запроса

```
curl :30080 → NodePort Service (Envoy Gateway создаёт его по EnvoyProxy) → Envoy Proxy
  → HTTPRoute (hello-default: любой Host; hello: Host hello.hack.local) → Service hello / hello-v1 / hello-v2
  → Angie :8080 → "Hello World!"
```

- Envoy генерирует `X-Request-Id`, если клиент его не передал; клиентский заголовок сохраняется.
- Angie берёт `X-Request-Id` из запроса, пишет его в access-лог и возвращает клиенту в заголовке ответа.
- `externalTrafficPolicy: Local` сохраняет адрес клиента; в логах приложения он маскируется до `/24`.

## Метрики

| Источник | Порт | Ресурс сбора | Что даёт |
|---|---|---|---|
| Angie | 9113 `/metrics` (шаблон `prometheus all`) | `ServiceMonitor/hello` | Технические метрики веб-сервера |
| Envoy Proxy | `/stats/prometheus` | `PodMonitor/envoy-proxy` | RED-метрики на уровне Gateway |
| Envoy Gateway controller | metrics | `ServiceMonitor/envoy-gateway` | Состояние контроллера |
| Fluentd | 24231 | `PodMonitor/fluentd` | Очередь буфера, счётчики записей |
| VictoriaLogs | chart `serviceMonitor` | встроенный в чарт | Состояние хранилища логов |
| Кластер | — | kube-prometheus-stack | kubelet/cAdvisor, node-exporter, kube-state-metrics, apiserver, etcd, scheduler, controller-manager, kube-proxy |

Метрики Angie доступны Prometheus только из namespace `monitoring` (NetworkPolicy пропускает порт 9113 оттуда).
Правила и алерты — `k8s/base/monitoring/rules.yaml`.

## Логи

```
Angie stdout (JSON access) ─┐
Angie stderr (error_log)   ─┼→ /var/log/containers → Fluentd (tail → kubernetes_metadata → JSON parser
Envoy stdout (JSON access) ─┘    → log_type → буфер на диске) → VictoriaLogs /insert/jsonline
```

- `log_type`: `access` (Angie), `gateway_access` (Envoy), `error` (stderr Angie), иначе `app`.
- Общее поле `request_id` позволяет одним запросом (`make logs-find ID=…`) найти путь запроса через Gateway и приложение.
- Файловый буфер Fluentd (до 512 МБ, `retry_forever`) переживает недоступность VictoriaLogs; хранение логов — 7 дней.

## Автоматизация

```
make deploy → bootstrap (.venv: ansible-core + hackops) → ansible-playbook site.yml
  хост (os_prep, containerd, kubernetes_pkgs) → кластер (kubeadm_init, cni_calico)
  → платформа (storage, namespaces, secrets, cert_manager, envoy_gateway, monitoring, logging)
  → приложение (app_hello) → ожидание готовности (wait_ready)
```

Кластерный слой применяется только идемпотентными модулями: `kubernetes.core.helm` (точные версии) и
`kubernetes.core.k8s` с server-side apply и манифестами из Kustomize. Поэтому второй прогон отчитывается
`changed=0` — это проверяет `make idempotency-check`.

## Принятые решения (ADR, кратко)

| Решение | Почему | Альтернатива |
|---|---|---|
| kubeadm, а не kind/k3s | Приоритет кейса; «настоящий» кластер | kind — только для CI (в этой версии CI нет) |
| Kubernetes 1.36, не 1.37 | В проверенном диапазоне Envoy Gateway v1.9 | 1.37 — новее, но вне матрицы совместимости |
| Envoy Gateway | Эталонная реализация Gateway API, политики и метрики Envoy из коробки | NGINX Gateway Fabric, Cilium |
| NodePort 30080 | Работает в любой сети без свободных IP | MetalLB (нужен диапазон адресов) |
| Angie | Назван в кейсе; встроенные Prometheus-метрики без sidecar | `nginx-unprivileged` + exporter (запасной вариант, `images.nginx_fallback`) |
| Fluentd → VictoriaLogs | Нативный `out_http` без сторонних плагинов, мало RAM | Loki, OpenSearch (тяжелее) |
| Calico | Работающие NetworkPolicy | flannel (политик нет) |
| Ansible + Helm + Kustomize + Make | Идемпотентность и корректный `changed` | shell + `kubectl apply` (всегда `changed`) |
| Пароли генерируются при деплое | Ни одного секрета в git | — |
