#!/usr/bin/env bash
# End-to-end test: two fake plugs + one unreachable plug -> collector -> check metrics.
# Used by CI; run locally with:  ./tools/test_collector.sh
set -euo pipefail
cd "$(dirname "$0")/.."
TMP="$(mktemp -d)"
trap 'kill $(jobs -p) 2>/dev/null || true; rm -rf "$TMP"' EXIT

cat > "$TMP/config.yml" <<EOF
listen_port: 19924
price_per_kwh: 0.35
defaults: {poll_interval: 1}
plugs:
  - {name: plug-a, host: "127.0.0.1:18081", room: Test}
  - {name: plug-b, host: "127.0.0.1:18082"}
  - {name: plug-down, host: "127.0.0.1:18089"}
EOF

python3 tools/fake_shelly.py 18081 & python3 tools/fake_shelly.py 18082 &
sleep 1
SHELLY_CONFIG="$TMP/config.yml" SHELLY_STATE="$TMP/state.json" python3 collector/shelly_collector.py &
sleep 5
curl -sf localhost:19924/metrics > "$TMP/metrics.txt"

check() {  # check <description> <grep -E pattern>
  if grep -qE "$2" "$TMP/metrics.txt"; then echo "  ok   $1"; else echo "  FAIL $1"; FAIL=1; fi
}
FAIL=""
check "plug-a up"                 '^shelly_up\{plug="plug-a".*\} 1\.0$'
check "unreachable plug down"     '^shelly_up\{plug="plug-down".*\} 0\.0$'
check "power reported"            '^shelly_power_watts\{plug="plug-a"'
check "energy counter"            '^shelly_energy_wh_total\{plug="plug-a"'
check "4 toggles counted"         '^shelly_relay_toggles_total\{plug="plug-a".*\} 4\.0$'
check "toggle source recorded"    'shelly_relay_switches_total\{plug="plug-a".*source="app"\} 1\.0'
check "on-time tracked"           '^shelly_relay_on_seconds_total\{plug="plug-a"'
check "device info"               '^shelly_device_info\{plug="plug-a".*model="S3PL-20112EU"'
check "wifi rssi"                 '^shelly_wifi_rssi_dbm\{plug="plug-a".*\} -61\.0$'

python3 - "$TMP/metrics.txt" <<'EOF'
import sys
from prometheus_client.parser import text_string_to_metric_families
fams = list(text_string_to_metric_families(open(sys.argv[1]).read()))
print(f"  ok   exposition format parses ({len(fams)} metric families)")
EOF

if [[ -n "$FAIL" ]]; then
  echo "Some checks failed:"; cat "$TMP/metrics.txt"; exit 1
fi
echo "All checks passed."
