#!/usr/bin/env python3
"""Генерирует Deployment'ы hello-v1/v2 и конфиги Angie из одного шаблона (без дублирования правок).

Запуск: python3 scripts/gen_hello.py   (результат коммитится; CI проверяет актуальность)
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "k8s" / "base" / "hello"

DEPLOYMENT = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: hello-@V@
  namespace: hello
  labels: { app: hello, variant: "@V@" }
spec:
  replicas: 2
  selector:
    matchLabels: { app: hello, variant: "@V@" }
  template:
    metadata:
      labels: { app: hello, variant: "@V@" }
    spec:
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 101
        runAsGroup: 101
        seccompProfile: { type: RuntimeDefault }
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels: { app: hello, variant: "@V@" }
      containers:
        - name: angie
          image: docker.angie.software/angie:1.12.1-minimal
          command: ["angie", "-c", "/etc/angie/angie.conf", "-g", "daemon off;"]
          ports:
            - { name: http, containerPort: 8080 }
            - { name: metrics, containerPort: 9113 }
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: { drop: [ALL] }
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits: { cpu: 200m, memory: 128Mi }
          readinessProbe:
            httpGet: { path: /healthz, port: http }
            periodSeconds: 5
          livenessProbe:
            httpGet: { path: /healthz, port: http }
            initialDelaySeconds: 10
            periodSeconds: 10
          volumeMounts:
            - { name: conf, mountPath: /etc/angie/angie.conf, subPath: angie.conf, readOnly: true }
            - { name: tmp, mountPath: /tmp }
      volumes:
        - name: conf
          configMap: { name: angie-@V@ }
        - name: tmp
          emptyDir: {}
"""

ANGIE = r"""# Angie 1.12 — приложение hello (вариант @V@). Сгенерировано scripts/gen_hello.py — не править руками.
pid /tmp/angie.pid;
worker_processes 1;
error_log stderr warn;

events { worker_connections 1024; }

http {
    default_type text/plain;
    client_body_temp_path /tmp/client_body;
    proxy_temp_path       /tmp/proxy;
    fastcgi_temp_path     /tmp/fastcgi;
    uwsgi_temp_path       /tmp/uwsgi;
    scgi_temp_path        /tmp/scgi;

    map $http_x_request_id $req_id {
        ""      $request_id;
        default $http_x_request_id;
    }
    # маскирование IP клиента (X-Forwarded-For выставляет Envoy)
    map $http_x_forwarded_for $client_ip_masked {
        default "masked";
        "~^(?<net>\d+\.\d+\.\d+)\.\d+" "$net.0";
    }
    map $uri $route_group {
        default  other;
        /        root;
        ~^/api/  api;
        ~^/promo promo;
    }

    log_format json_access escape=json
      '{"ts":"$time_iso8601","log_type":"access","request_id":"$req_id",'
      '"method":"$request_method","path":"$uri","status":$status,"bytes":$body_bytes_sent,'
      '"request_time":$request_time,"host":"$host","route_group":"$route_group",'
      '"client_ip":"$client_ip_masked","user_agent":"$http_user_agent",'
      '"referer":"$http_referer","version":"@V@","pod":"$hostname"}';

    # трафик: 8080
    server {
        listen 8080;
        status_zone hello;
        access_log /dev/stdout json_access;

        add_header X-Request-Id $req_id always;
        add_header X-App-Version @V@ always;

        location = / { return 200 "Hello World!\n"; }
        location = /api/info {
            default_type application/json;
            return 200 '{"app":"hello","version":"@V@","pod":"$hostname","request_id":"$req_id"}\n';
        }
        location /promo { return 200 "Promo page\n"; }
        location = /healthz { access_log off; return 200 "ok\n"; }
        # демонстрация error-лога: open() failed -> запись в error_log (вызывает hackops verify изнутри кластера)
        location = /__error_demo {
            root /nonexistent;
        }
    }

    # метрики: 9113 (доступ только из ns monitoring — NetworkPolicy)
    server {
        listen 9113;
        access_log off;
        location = /metrics { prometheus all; }
    }
}
"""

for v in ("v1", "v2"):
    (ROOT / f"deployment-{v}.yaml").write_text(DEPLOYMENT.replace("@V@", v), encoding="utf-8")
    (ROOT / f"angie-{v}.conf").write_text(ANGIE.replace("@V@", v), encoding="utf-8")
print("generated")
