# Чек-лист прогона на чистой Ubuntu 24.04

Каркас платформы ни разу не запускался на реальной ВМ: локально проверены только синтаксис Ansible,
yamllint, ruff/mypy и unit-тесты `hackops`. Ниже — что пройти на **чистой** ВМ (4 vCPU / 8 ГБ / 40 ГБ,
Ubuntu 24.04, sudo без пароля). Результат каждого пункта записывайте: «ок» или текст ошибки.

## A. Основной прогон

```bash
git clone https://github.com/danil-prog-coder/MTC_engineer_HACK.git && cd MTC_engineer_HACK
time make deploy 2>&1 | tail -50      # цель ≤ 15 минут
make verify                            # код возврата 0; смотреть artifacts/verification-report.md
make idempotency-check                 # changed=0; цель ≤ 3 минуты
make verify                            # теперь R-20 должен быть PASS, а не SKIP
```

Если `make deploy` упал — приложите последние ~50 строк и `artifacts/deploy.log`; повторный запуск
`make deploy` допустим (он идемпотентен).

## B. Пункты (verify) — версии и имена, угаданные по документации

| # | Что проверить | Как | Если не так |
|---|---|---|---|
| 1 | Существует патч `kubelet=1.36.4-1.1` | `apt-cache madison kubeadm \| head` | поправить `kubernetes.patch` / `apt_suffix` |
| 2 | Calico v3.31.0, local-path v0.0.32 существуют | `make deploy` доходит до ролей `cni_calico`, `storage_local_path` | поправить версии |
| 3 | Версии чартов: cert-manager v1.19.1, kube-prometheus-stack 77.13.0, victoria-logs-single 0.11.12, Envoy Gateway v1.9.2 | `helm ls -A` после деплоя | поправить `versions.yaml` |
| 4 | Образы тянутся: Angie `1.12.1-minimal`, fluentd `v1.19.3-debian-forward-1.0` | `kubectl get pods -A` — нет `ImagePullBackOff` | поправить теги в `versions.yaml` **и** в манифестах (`k8s/base/logging/daemonset.yaml`, `scripts/gen_hello.py`) |
| 5 | Имя порта Envoy Service `http-80` (патч nodePort 30080 применился) | `kubectl -n gateway-system get svc -o wide`; `curl -si http://<IP>:30080/` | поправить имя порта в `k8s/base/gateway/envoyproxy.yaml` |
| 6 | Имя сервиса VictoriaLogs `victoria-logs`, порт 9428 | `kubectl -n logging get svc`; `make logs-query Q='*'` | поправить `fullnameOverride` в `helm-values/victoria-logs.yaml` и адрес в `fluent.conf`, `adapters/kube.py` |
| 7 | Метки Envoy pod и имя порта `metrics` для `PodMonitor` | `kubectl -n gateway-system get pods --show-labels`; `kubectl -n gateway-system get pod <envoy> -o jsonpath='{.spec.containers[*].ports}'`; target `envoy-proxy` в Prometheus UP | поправить selector/port в `k8s/base/monitoring/monitors.yaml` |
| 8 | Метки Service контроллера Envoy Gateway (`control-plane: envoy-gateway`), порт `metrics` | `kubectl -n gateway-system get svc --show-labels` | поправить `ServiceMonitor/envoy-gateway` |
| 9 | Синтаксис Angie: `prometheus all`, `status_zone` | `kubectl -n hello logs deploy/hello-v1` — нет `[emerg]`; `curl` на pod:9113/metrics из ns monitoring | поправить `scripts/gen_hello.py` и перегенерировать |
| 10 | Angie под uid 101 с read-only rootfs запускается | поды `hello-*` Running/Ready | fallback на `images.nginx_fallback` (nginx-unprivileged + exporter) |
| 11 | `error_log` Angie попадает в VictoriaLogs как `log_type:error` | `curl http://<IP>:30080/__error_demo; make logs-query Q='log_type:error'` | поправить фильтры в `fluent.conf` |
| 12 | Все targets в Prometheus зелёные (kube-controller-manager, scheduler, etcd, kube-proxy, kubelet) | `kubectl -n monitoring port-forward svc/kps-prometheus 9090:9090`, `/targets` | смотреть, какой target красный |

## C. Дополнительно, чего мы пока не знаем

- `kubernetes.core.kustomize` lookup находит `kubectl` (роли `app_hello`, `namespaces`, `envoy_gateway`, `monitoring`, `logging`).
- `kubernetes.core.k8s` с server-side apply возвращает `changed=false` на втором прогоне (если нет — назвать, какие задачи `changed`; это главный риск R-20).
- `sudo make deploy` и `make deploy` от обычного пользователя дают рабочий `~/.kube/config` (`kubectl get nodes` без sudo).
- `make creds` печатает пароль; вход в Grafana (`port-forward svc/kps-grafana 3000:80`) работает.
- Reboot ВМ: кластер сам поднимается, `make verify` снова зелёный (swap не вернулся, kubelet стартует).
- `make destroy CONFIRM=yes`, затем `make deploy` заново работает с чистого листа.

## D. Что прислать после прогона

`artifacts/verification-report.md`, `artifacts/deploy.log` (или ошибку), `artifacts/idempotency.json`, список
проваленных пунктов из таблицы B/C. Бонусы уровня 3 (TLS, redirect, rate limit, SLO, дашборды, CI…) начинаем
только после зелёных `make deploy && make verify`.
