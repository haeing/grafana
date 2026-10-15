#!/bin/bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Run: sudo bash /share/grafana/scripts/apply.sh'; exit 1; }
if pgrep -f '^(/usr/bin/)?python[0-9.]* (.*[/])?lakeshore325_logger.py([[:space:]]|$)' >/dev/null; then
    echo 'Existing lakeshore325_logger.py is running. Stop it before starting the Grafana Lake Shore reader.' >&2
    exit 1
fi
systemctl is-active --quiet influxdb || { echo 'InfluxDB must be running.'; exit 1; }
# Pause the importer before migrating checkpoints; retain all original files.
importer_active=false
if systemctl is-active --quiet gl840-influx.service; then
    importer_active=true
    systemctl stop gl840-influx.service
fi
restore_importer() {
    if [ "$importer_active" = true ]; then systemctl start gl840-influx.service; fi
}
trap restore_importer EXIT
for name in state.json state-pressure-v1.json; do
    if [ ! -f "/share/grafana/state/$name" ] && [ -f "/share/logger/grafana/$name" ]; then
        install -o hanul -g hanul -m 644 "/share/logger/grafana/$name" "/share/grafana/state/$name"
    fi
done
for name in gl840-live lakeshore-grafana gl840-influx; do
    install -m 644 "/share/grafana/services/$name.service" "/etc/systemd/system/$name.service"
done
systemctl daemon-reload
bash /share/grafana/scripts/update-dashboard.sh
systemctl enable gl840-live.service lakeshore-grafana.service
systemctl restart gl840-live.service lakeshore-grafana.service
if [ "$importer_active" = true ]; then
    systemctl start gl840-influx.service
fi
trap - EXIT
sleep 12
journalctl -u gl840-live.service -u lakeshore-grafana.service -n 12 --no-pager
echo 'Central Grafana configuration applied from /share/grafana.'
