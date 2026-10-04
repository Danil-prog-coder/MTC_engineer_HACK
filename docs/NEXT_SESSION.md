# С чего начинать следующей сессии

Состояние: каркас уровня 1 + Makefile, README (13 обязательных пунктов), docs/architecture.md, чек-лист прогона.
На реальной ВМ (Ubuntu 24.04, РФ, с профилем зеркал `mirrors-ru.env`) пройден полный цикл deploy/verify/idempotency:
17/17 PASS, `changed=0`. **Единственное, что не проверено, — `make deploy` без зеркал (upstream)**: нужна ВМ с нормальным
интернетом, без `.env`. Это следующий шаг.

## Сделано в последней сессии
- Makefile: bootstrap (.venv, python3-venv), deploy, verify, idempotency-check, creds, ca, logs-find, logs-query,
  lint, test, destroy; `hackops idempotency` разбирает PLAY RECAP -> artifacts/idempotency.json.
- Найдены и закрыты пробелы каркаса: не было роли `secrets` (site.yml на неё ссылался) и Namespace'ов
  (k8s/base/namespaces + роль `namespaces`); kubeconfig теперь создаётся и для пользователя, запустившего make
  (HACK_USER/HACK_HOME); `stdout_callback = yaml` заменён на `default` + `result_format = yaml`.

## Порядок работ дальше
1. Пользователь прогоняет `docs/VERIFY_ON_VM.md` на чистой Ubuntu 24.04 и присылает результаты; чиним по ним.
2. Только после зелёных `make deploy && make verify` (и `changed=0`): бонусы — TLS (Certificate + https listener,
   `make ca` уже ждёт Secret `hack-local-ca` в ns cert-manager), redirect, rate limit, SLO, сверка логов,
   бизнес-метрики, дашборды, CI. Каждый бонус — отдельный Kustomize-компонент/флаг.
3. После каждого бонуса обновлять README (раздел 13 и «Ограничения»): заявлять только то, что проверяемо.

Не делаем: презентация, паспорт, архив (по решению пользователя).
Отклонения от ТЗ: ns monitoring = privileged (node-exporter требует hostPath/hostNetwork);
EXPOSE=metallb не реализован; `make versions-check` из ТЗ заменён ручным чек-листом.
