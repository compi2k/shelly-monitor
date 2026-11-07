#!/usr/bin/env bash
# Removes the Shelly collector service. Prometheus/Grafana packages and all
# recorded data are kept unless you pass --purge.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo"; exit 1; }

systemctl disable --now shelly-collector 2>/dev/null || true
rm -f /etc/systemd/system/shelly-collector.service
rm -rf /opt/shelly-monitor
rm -f /etc/grafana/provisioning/datasources/shelly-prometheus.yml \
      /etc/grafana/provisioning/dashboards/shelly.yml \
      /etc/systemd/system/grafana-server.service.d/shelly.conf
rm -rf /var/lib/grafana/dashboards/shelly
systemctl daemon-reload

if [[ "${1:-}" == "--purge" ]]; then
  systemctl disable --now prometheus grafana-server 2>/dev/null || true
  apt-get purge -y prometheus grafana
  rm -rf /var/lib/prometheus /var/lib/grafana /var/lib/private/shelly-monitor \
         /var/lib/shelly-monitor /etc/shelly-monitor /etc/apt/sources.list.d/grafana.list
  echo "Everything removed, including recorded data."
else
  systemctl restart grafana-server 2>/dev/null || true
  echo "Collector removed. Data, config (/etc/shelly-monitor), Prometheus and Grafana kept."
  echo "Use --purge to remove everything."
fi
