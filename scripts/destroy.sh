#!/usr/bin/env bash
# Удаление стенда: kubeadm reset и очистка следов. Деструктивно — вызывается только из `make destroy CONFIRM=yes`.
set -uo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Запустите от root (make destroy делает это через sudo)" >&2
  exit 2
fi

echo "==> kubeadm reset"
if command -v kubeadm >/dev/null 2>&1; then
  kubeadm reset -f --cri-socket unix:///run/containerd/containerd.sock || true
fi
systemctl stop kubelet 2>/dev/null || true

echo "==> Очистка каталогов и сетевых следов"
rm -rf /etc/kubernetes /var/lib/etcd /etc/cni/net.d /var/lib/cni /var/lib/kubelet
rm -rf /var/lib/fluentd-state /opt/local-path-provisioner /etc/hackops
for home in /root /home/*; do rm -rf "$home/.kube"; done
for link in vxlan.calico cni0 flannel.1; do ip link delete "$link" 2>/dev/null || true; done
if command -v iptables >/dev/null 2>&1; then
  iptables -F && iptables -t nat -F && iptables -t mangle -F && iptables -X || true
fi
if command -v ipvsadm >/dev/null 2>&1; then ipvsadm --clear || true; fi

echo "Готово. Пакеты (containerd, kubeadm, helm) оставлены на хосте; повторный make deploy работает с чистого листа."
