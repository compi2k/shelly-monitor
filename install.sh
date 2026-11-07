#!/usr/bin/env bash
# shelly-monitor installer
# Installs / updates the collector, Prometheus and Grafana as native systemd
# services on Raspberry Pi OS / Debian.
#
#   sudo ./install.sh
#   sudo GRAFANA_PORT=3001 RETENTION=2y ./install.sh     # optional settings
#
# Safe to re-run: keeps your plug config, recorded data, Grafana password and
# the settings from previous runs.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Please run with sudo:  sudo ./install.sh"; exit 1; }
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ETC=/etc/shelly-monitor
SETTINGS="$ETC/install.env"

say()  { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!!  %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*"; exit 1; }

# settings: command line > previous run > defaults
_cli_port="${GRAFANA_PORT:-}"; _cli_ret="${RETENTION:-}"; _cli_size="${RETENTION_SIZE:-}"
# shellcheck disable=SC1090
[[ -f "$SETTINGS" ]] && source "$SETTINGS"
GRAFANA_PORT="${_cli_port:-${GRAFANA_PORT:-3000}}"
RETENTION="${_cli_ret:-${RETENTION:-5y}}"
RETENTION_SIZE="${_cli_size:-${RETENTION_SIZE:-8GB}}"

# --------------------------------------------------------------------------- #
say "Checking port $GRAFANA_PORT for Grafana"
if command -v ss >/dev/null; then
  holder="$(ss -tlnpH "sport = :$GRAFANA_PORT" 2>/dev/null | grep -o 'users:(("[^"]*' | cut -d'"' -f2 | head -1 || true)"
  if [[ -n "$holder" && "$holder" != grafana* ]]; then
    die "Port $GRAFANA_PORT is already used by '$holder'.
       Re-run with another port, e.g.:  sudo GRAFANA_PORT=3001 ./install.sh"
  fi
fi

# --------------------------------------------------------------------------- #
say "Installing packages (python, prometheus, grafana)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  python3 python3-venv ca-certificates curl gnupg iproute2 prometheus >/dev/null

if ! dpkg -s grafana >/dev/null 2>&1; then
  install -d -m 755 /etc/apt/keyrings
  curl -fsSL https://apt.grafana.com/gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/grafana.gpg
  echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
    > /etc/apt/sources.list.d/grafana.list
  apt-get update -qq
  apt-get install -y -qq grafana >/dev/null
fi

# --------------------------------------------------------------------------- #
say "Installing collector"
install -d /opt/shelly-monitor "$ETC"
install -m 644 "$SRC/collector/shelly_collector.py" /opt/shelly-monitor/
[[ -x /opt/shelly-monitor/venv/bin/python ]] || python3 -m venv /opt/shelly-monitor/venv
/opt/shelly-monitor/venv/bin/pip install -q --upgrade pip
/opt/shelly-monitor/venv/bin/pip install -q -r "$SRC/collector/requirements.txt"

FIRST_CONFIG=""
if [[ ! -f "$ETC/config.yml" ]]; then
  install -m 644 "$SRC/config/config.example.yml" "$ETC/config.yml"
  FIRST_CONFIG=1
fi
install -m 644 "$SRC/systemd/shelly-collector.service" /etc/systemd/system/

cat > "$SETTINGS" <<EOF
# written by install.sh – used again on the next run
GRAFANA_PORT=$GRAFANA_PORT
RETENTION=$RETENTION
RETENTION_SIZE=$RETENTION_SIZE
EOF

# --------------------------------------------------------------------------- #
say "Configuring Prometheus (retention $RETENTION / $RETENTION_SIZE)"
if [[ -f /etc/prometheus/prometheus.yml ]] && \
   ! grep -q "Managed by shelly-monitor" /etc/prometheus/prometheus.yml; then
  cp /etc/prometheus/prometheus.yml "/etc/prometheus/prometheus.yml.bak.$(date +%s)"
  warn "Backed up your previous /etc/prometheus/prometheus.yml"
fi
install -m 644 "$SRC/prometheus/prometheus.yml" /etc/prometheus/prometheus.yml
install -m 644 "$SRC/prometheus/rules.yml" /etc/prometheus/shelly-rules.yml
cat > /etc/default/prometheus <<EOF
# Managed by shelly-monitor install.sh
ARGS="--storage.tsdb.retention.time=$RETENTION --storage.tsdb.retention.size=$RETENTION_SIZE --web.listen-address=127.0.0.1:9090"
EOF

# --------------------------------------------------------------------------- #
say "Configuring Grafana (port $GRAFANA_PORT)"
install -m 644 "$SRC/grafana/provisioning/datasources/prometheus.yml" \
  /etc/grafana/provisioning/datasources/shelly-prometheus.yml
install -m 644 "$SRC/grafana/provisioning/dashboards/dashboards.yml" \
  /etc/grafana/provisioning/dashboards/shelly.yml
install -d -o grafana -g grafana /var/lib/grafana/dashboards/shelly
install -m 644 -o grafana -g grafana "$SRC/grafana/dashboards/shelly.json" /var/lib/grafana/dashboards/shelly/

install -d /etc/systemd/system/grafana-server.service.d
DROPIN=/etc/systemd/system/grafana-server.service.d/shelly.conf
cat > "$DROPIN" <<EOF
[Service]
# Managed by shelly-monitor install.sh
Environment=GF_SERVER_HTTP_PORT=$GRAFANA_PORT
# dashboard is viewable without login; log in as admin to edit
Environment=GF_AUTH_ANONYMOUS_ENABLED=true
Environment=GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer
Environment=GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/var/lib/grafana/dashboards/shelly/shelly.json
Environment=GF_ANALYTICS_REPORTING_ENABLED=false
Environment=GF_NEWS_NEWS_FEED_ENABLED=false
EOF

NEW_PW=""
if [[ ! -f /var/lib/grafana/grafana.db ]]; then
  # first start: Grafana takes its initial admin password from the environment
  NEW_PW="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16 || true)"
  echo "Environment=GF_SECURITY_ADMIN_PASSWORD=$NEW_PW" >> "$DROPIN"
  chmod 600 "$DROPIN"
  echo "$NEW_PW" > "$ETC/grafana-admin-password"
  chmod 600 "$ETC/grafana-admin-password"
fi

# --------------------------------------------------------------------------- #
say "Starting services"
systemctl daemon-reload
systemctl enable shelly-collector prometheus grafana-server
systemctl restart shelly-collector prometheus grafana-server

echo "   waiting for Grafana (the first start on a Pi can take a few minutes)…"
ok=""
for _ in $(seq 1 120); do
  if curl -sf "http://127.0.0.1:$GRAFANA_PORT/api/health" >/dev/null; then ok=1; break; fi
  systemctl is-failed --quiet grafana-server && break
  sleep 2
done

if [[ -n "$NEW_PW" && -n "$ok" ]]; then
  # Grafana has stored the password – remove it from the unit file
  sed -i '/GF_SECURITY_ADMIN_PASSWORD/d' "$DROPIN"
  systemctl daemon-reload
fi

failed=""
for svc in shelly-collector prometheus grafana-server; do
  if ! systemctl is-active --quiet "$svc"; then
    warn "$svc is not running – see:  journalctl -u $svc -n 50 --no-pager"
    failed=1
  fi
done
[[ -z "$ok" && -z "$failed" ]] && warn "Grafana hasn't answered yet; give it another minute."

# --------------------------------------------------------------------------- #
IP="$(hostname -I | awk '{print $1}')"
HOST="$(hostname)"
if [[ -n "$failed" ]]; then say "Finished with problems (see above)"; else say "Done"; fi
cat <<EOF

  Dashboard:   http://$HOST:$GRAFANA_PORT   or   http://$IP:$GRAFANA_PORT
  Collector:   http://$IP:9924   (shows which plugs are reachable)
EOF
if [[ -n "$NEW_PW" ]]; then
  echo "  Admin login: admin / $NEW_PW   (saved in $ETC/grafana-admin-password)"
fi
if [[ -n "$FIRST_CONFIG" ]]; then
  cat <<EOF

  NEXT: add your plugs' IP addresses, then restart the collector:
        sudo nano $ETC/config.yml
        sudo systemctl restart shelly-collector
EOF
fi
echo
