#!/bin/bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Run with sudo bash'; exit 1; }
backup_dir=$(mktemp -d /var/tmp/corea-grafana-backup.XXXXXX)
for file in /etc/grafana/provisioning/dashboards/gl840.yaml /var/lib/grafana/dashboards/gl840.json; do
    if [ -f "$file" ]; then cp -a "$file" "$backup_dir/"; fi
done
install -d /etc/grafana/provisioning/dashboards /etc/grafana/provisioning/datasources /var/lib/grafana/dashboards
install -m 644 /share/grafana/provisioning/dashboards.yaml /etc/grafana/provisioning/dashboards/gl840.yaml
install -m 644 /share/grafana/provisioning/datasource.yaml /etc/grafana/provisioning/datasources/gl840.yaml
install -m 644 /share/grafana/dashboards/gas-target.json /var/lib/grafana/dashboards/gl840.json
systemctl restart grafana-server
echo "Updated COREA > Gas Target. Backup: $backup_dir"
