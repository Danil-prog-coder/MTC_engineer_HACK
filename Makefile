# Hello Platform. Единственная обязательная команда: make deploy
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# Параметры: значения по умолчанию, при желании переопределяются в .env или окружении.
-include .env
DOMAIN        ?= hack.local
EXPOSE        ?= nodeport
NODE_IP       ?=
METALLB_RANGE ?=
INVENTORY     ?= ansible/inventory/local.yml
# В .env допустимы комментарии после значения — обрезаем хвостовые пробелы.
DOMAIN        := $(strip $(DOMAIN))
EXPOSE        := $(strip $(EXPOSE))
NODE_IP       := $(strip $(NODE_IP))
METALLB_RANGE := $(strip $(METALLB_RANGE))
INVENTORY     := $(strip $(INVENTORY))

# Автовыбор источников загрузки. MIRRORS=auto (по умолчанию): если pypi.org, files.pythonhosted.org, Docker Hub, quay.io или CDN Kubernetes
# недоступны с этого хоста, подключается профиль зеркал mirrors-ru.env. MIRRORS=on - принудительно профиль, off - только upstream.
# Если зеркала заданы вручную (.env или окружение), автовыбор не вмешивается. Проверка идёт только для целей, которым нужна сеть.
MIRRORS := $(strip $(or $(MIRRORS),auto))
ifneq ($(filter bootstrap deploy idempotency-check verify lint test,$(MAKECMDGOALS)),)
ifneq ($(MIRRORS),off)
ifeq ($(strip $(PIP_INDEX_URL)$(K8S_APT_REPO)$(DOCKERHUB_MIRRORS)$(QUAY_MIRRORS)$(K8S_REGISTRY_MIRRORS)$(OCI_DOCKERHUB_MIRROR)$(CALICO_REGISTRY)$(GHCR_MIRROR)),)
MIRRORS_MODE := $(if $(filter on,$(MIRRORS)),ru,$(strip $(shell bash scripts/detect-mirrors.sh)))
ifeq ($(MIRRORS_MODE),ru)
$(info [mirrors] upstream недоступен или MIRRORS=on: подключён профиль зеркал mirrors-ru.env)
include mirrors-ru.env
endif
endif
endif
endif

# Пользователь, запустивший make (для kubeconfig): при `sudo make` это SUDO_USER.
HACK_USER := $(or $(SUDO_USER),$(shell id -un))
HACK_HOME := $(shell getent passwd $(HACK_USER) | cut -d: -f6)
export DOMAIN EXPOSE NODE_IP METALLB_RANGE HACK_USER HACK_HOME
export KUBECONFIG ?= $(HACK_HOME)/.kube/config

SUDO    := $(if $(filter 0,$(shell id -u)),,sudo)
VENV    := .venv
BIN     := $(VENV)/bin
HACKOPS := $(BIN)/hackops
PLAY    := ANSIBLE_CONFIG=ansible/ansible.cfg $(BIN)/ansible-playbook -i $(INVENTORY) ansible/site.yml
SECRETS := /etc/hackops/secrets

# Источники загрузки: по умолчанию upstream. Для сетей с блокировками — зеркала в .env (пример: mirrors-ru.env).
PIP_INDEX_URL       ?= https://pypi.org/simple/
# Короткий таймаут + докачка: на нестабильных каналах соединение «замирает», pip продолжает файл с места обрыва
PIP_DEFAULT_TIMEOUT ?= 20
PIP_RETRIES         ?= 10
PIP_RESUME_RETRIES  ?= 10
MIRROR_VARS := PIP_INDEX_URL K8S_APT_REPO DOCKERHUB_MIRRORS QUAY_MIRRORS K8S_REGISTRY_MIRRORS \
               OCI_DOCKERHUB_MIRROR CALICO_REGISTRY GHCR_MIRROR
$(foreach v,$(MIRROR_VARS),$(eval $(v) := $(strip $($(v)))))
export PIP_DEFAULT_TIMEOUT PIP_RETRIES PIP_RESUME_RETRIES $(MIRROR_VARS)

.PHONY: help bootstrap deploy verify idempotency-check creds ca logs-find logs-query lint test destroy

help: ## Список команд
	@awk -F ':.*## ' '/^[a-z-]+:.*## /{printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

$(VENV)/.bootstrapped: requirements.txt requirements-dev.txt ansible/requirements.yml tools/hackops/pyproject.toml
	@if [ -n "$(SUDO)" ] && ! sudo -n true 2>/dev/null; then \
	  echo "Нужен sudo без пароля (или запустите от root): sudo -v && make deploy" >&2; exit 2; fi
	$(SUDO) apt-get update -qq
	$(SUDO) apt-get install -y -qq python3-venv python3-pip git curl ca-certificates
	python3 -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -r requirements.txt -r requirements-dev.txt -e "tools/hackops[dev]"
	# galaxy.ansible.com отдаёт архивы из S3, который бывает недоступен: fallback — пакет ansible с PyPI-зеркала
	# (входят нужные коллекции: kubernetes.core 5.4.1, community.general 10.7.6, ansible.posix 1.6.2; ansible-core 2.18)
	timeout 120 $(BIN)/ansible-galaxy collection install --timeout 30 -r ansible/requirements.yml || \
	  $(BIN)/pip install -q "ansible==11.13.0"
	@touch $@

bootstrap: $(VENV)/.bootstrapped ## Окружение (.venv: ansible, hackops)

deploy: bootstrap ## Полное развёртывание: хост -> kubeadm -> платформа -> приложение
	@mkdir -p artifacts
	$(PLAY) 2>&1 | tee artifacts/deploy.log

verify: bootstrap ## Отчёт-доказательство artifacts/verification-report.md
	$(HACKOPS) verify

idempotency-check: bootstrap ## Повторный прогон деплоя: ожидаем changed=0
	@mkdir -p artifacts
	($(PLAY) 2>&1 | tee artifacts/ansible-run2.log) || true
	$(HACKOPS) idempotency artifacts/ansible-run2.log

creds: ## Сгенерированные учётные данные (Grafana)
	@echo "Grafana: user=admin password=$$($(SUDO) cat $(SECRETS)/grafana-admin-password)"
	@echo "Доступ:  kubectl -n monitoring port-forward svc/kps-grafana 3000:80  ->  http://localhost:3000"

ca: ## Корневой сертификат для TLS -> artifacts/ca.crt (появляется вместе с TLS-бонусом)
	@mkdir -p artifacts
	@if kubectl -n cert-manager get secret hack-local-ca >/dev/null 2>&1; then \
	  kubectl -n cert-manager get secret hack-local-ca -o jsonpath='{.data.tls\.crt}' | base64 -d > artifacts/ca.crt; \
	  echo "CA сохранён: artifacts/ca.crt"; \
	else echo "TLS не включён в этой сборке: CA не создавался (см. README, «Ограничения»)"; fi

logs-find: bootstrap ## Найти записи по request_id: make logs-find ID=...
	@$(if $(ID),,$(error Укажите ID=<request_id>))
	$(HACKOPS) logs-find '$(ID)'

logs-query: bootstrap ## Запрос LogsQL: make logs-query Q='log_type:error'
	@$(if $(Q),,$(error Укажите Q=<запрос LogsQL>))
	$(HACKOPS) logs-query '$(Q)'

lint: bootstrap ## Статические проверки
	$(BIN)/yamllint -c .yamllint ansible k8s helm-values versions.yaml
	$(BIN)/ruff check tools/hackops
	cd tools/hackops && ../../$(BIN)/mypy
	python3 scripts/gen_hello.py && git diff --exit-code -- k8s/base/hello
	python3 scripts/gen_dashboards.py && git diff --exit-code -- k8s/base/monitoring/dashboards
	ANSIBLE_CONFIG=ansible/ansible.cfg $(BIN)/ansible-playbook -i $(INVENTORY) ansible/site.yml --syntax-check
	@if command -v kubectl >/dev/null; then \
	  for d in k8s/base/* k8s/overlays/*; do kubectl kustomize $$d >/dev/null && echo "kustomize OK: $$d"; done; \
	else echo "kubectl не найден: kustomize build пропущен"; fi

test: bootstrap ## Unit-тесты hackops
	$(BIN)/pytest -q tools/hackops

destroy: ## Удалить стенд (деструктивно): make destroy CONFIRM=yes
	@[ "$(CONFIRM)" = "yes" ] || { echo "Деструктивная операция: make destroy CONFIRM=yes" >&2; exit 2; }
	$(SUDO) ./scripts/destroy.sh
