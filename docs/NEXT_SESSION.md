# С чего начинать следующей сессии

Состояние: написан каркас уровня 1 (база) + начало уровня 2. Ничего не запускалось на реальной ВМ
(локально нет helm/ansible/make) — вся база НЕ проверена.

Сделано: versions.yaml, ansible (14 ролей), k8s/base (gateway, hello, logging, monitoring),
helm-values, tools/hackops (verify, logs-find, logs-query + unit-тесты core), scripts/gen_hello.py.

## Порядок работ
1. Makefile: deploy, verify, creds, ca, logs-find/logs-query, idempotency-check
   (ansible-playbook дважды, парсить `changed=` -> artifacts/idempotency.json), lint, test, destroy.
   Установка hackops в .venv (python3-venv добавить в роль os_prep).
2. Проверить typer --help после фикса `click<8.2`.
3. Прогнать `make deploy` на чистой Ubuntu 24.04 ВМ и чинить. Проверить на стенде помеченные (verify):
   версии в versions.yaml (чарты, k8s 1.36.x, Fluentd-тег), имя порта Envoy Service (http-80),
   имя сервиса VictoriaLogs (victoria-logs), метки Envoy pod/порт metrics для PodMonitor,
   метки сервиса Envoy Gateway controller, синтаксис Angie (`prometheus all`, status_zone),
   образ Angie под uid 101 / read-only rootfs (иначе fallback nginx-unprivileged).
4. README по 13 пунктам (раздел 11 ТЗ) + docs/architecture.md + раздел «Ограничения».
5. Только после зелёного `make deploy && make verify`: бонусы (TLS, redirect, rate limit, SLO,
   сверка логов, бизнес-метрики, дашборды, CI).

Не делаем: презентация, паспорт, архив (по решению пользователя).
Отклонение от ТЗ: ns monitoring = privileged (node-exporter требует hostPath/hostNetwork).
