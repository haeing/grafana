# COREA Grafana

Central configuration and collectors for **Dashboards → COREA → Gas Target**.
The collectors read instruments, convert measurements, and write them to a local
InfluxDB database. Grafana displays those measurements as line graphs.

## Open the dashboard

Open the dashboard from a computer on the same network:

http://192.168.10.4:3000/d/gl840-ch1-ch3

Login credentials:

- **Username:** `admin`
- **Password:** `ku_hd_exp`

Log in and select **Dashboards → COREA → Gas Target**. Use **Last 15 minutes**
and a **5s** refresh interval for live monitoring.

## Apply the configuration

On the acquisition computer, run:

```bash
sudo bash /share/grafana/scripts/apply.sh 2>&1 | tee /share/grafana/logs/apply.log
```

This installs the systemd service definitions, enables and restarts the two live
collectors, registers the datasource and dashboard, and restarts Grafana.
If the historical CSV importer was running, it migrates its checkpoint and restarts it.

Requirements: the existing Grafana and InfluxDB installations, Python 3, the
`gl840` InfluxDB database, the `hanul` Linux account, and network access to the instruments.
This script configures the existing installation; it does not install these prerequisites.
The InfluxDB service must already be running:

```bash
sudo systemctl start influxdb
```

The live collectors automatically start after computer reboot and retry after
instrument disconnection. Power-cycling an instrument does not normally require
manual service restart. A running service can still be retrying a failed connection;
check its measurement logs to confirm that data is being saved.

## Check status and measurements

```bash
systemctl status gl840-live lakeshore-grafana influxdb grafana-server --no-pager
```

View recent measurements and connection errors:

```bash
journalctl -u gl840-live.service -u lakeshore-grafana.service -n 30 --no-pager
```

Follow live output; press Ctrl+C to stop watching without stopping collection:

```bash
journalctl -u gl840-live.service -u lakeshore-grafana.service -f
```

The collectors log successful samples after InfluxDB accepts the write.
Live measurement timestamps use the acquisition computer's clock. Collector log
messages use UTC; the dashboard displays Asia/Seoul time.

## Restart or stop collection

After changing collector code, restart the corresponding service:

```bash
sudo systemctl restart gl840-live.service
sudo systemctl restart lakeshore-grafana.service
```

To stop either collector temporarily:

```bash
sudo systemctl stop gl840-live.service
sudo systemctl stop lakeshore-grafana.service
```

To resume:

```bash
sudo systemctl start gl840-live.service lakeshore-grafana.service
```

Stopping a service this way does not disable its automatic startup on reboot.
Avoid running another reader against the same instrument connection while these
services are collecting. In particular, the GL840 command port accepts one client.

## Measurements and intervals

| Instrument | Address | Collection interval | Service |
| --- | --- | --- | --- |
| GL840 | `192.168.10.104:8023` | 30 seconds | `gl840-live` |
| Lake Shore 325 | `192.168.10.105:4196` | 10 seconds | `lakeshore-grafana` |

Grafana refreshes the dashboard every 5 seconds. Screen refresh and instrument
collection are separate intervals.

### GL840 pressure

The collector reads the first and third analog channels from binary instantaneous
measurement responses. Both currently use `raw / 2000` to obtain volts.
Supported input configuration: CH1 is DC with a `1-5V` or `10V` range; CH3 is DC
with a `10V` range. Unsupported configurations are rejected and logged.

- **Target Pressure:** `(CH1 voltage - 1) * 937.58` Torr.
- **Chamber Pressure:** `10 ** (2 * (CH3 voltage - 5.5))` Torr.
- The Target Pressure chart also has a right-hand atm axis: `Torr / 760`.

Read-only device queries are used; the collector does not set instrument ranges
or control acquisition. After an instrument range change, compare the collected
voltage with the instrument display before relying on converted pressure.

InfluxDB measurement: `gl840_live`.
Fields: `ch1_voltage`, `ch3_voltage`, `target_pressure_torr`, `chamber_pressure_torr`.

### Lake Shore 325 temperature and heater

Three separate charts are displayed:

| Chart | Read-only command | Unit |
| --- | --- | --- |
| Target Monitor Temperature | `KRDG? A` | K |
| Target Set Temperature | `SETP? 1` | K |
| Heater Output | `HTR?` | % |

The collector reads the device's numeric responses directly. It does not change
the temperature setpoint or heater output. Temperature B is not collected.

InfluxDB measurement: `lakeshore325`.
Fields: `temperature_a_k`, `setpoint_1_k`, `heater_output_percent`.

## Edit the dashboard

Edit `/share/grafana/dashboards/gas-target.json`, then apply:

```bash
sudo bash /share/grafana/scripts/update-dashboard.sh
```

Refresh the browser afterward. This command updates the provisioned datasource
and dashboard and restarts Grafana; the collectors keep running.
Previous dashboard/provider files are backed up under the `/var/tmp/corea-grafana-backup.*`
path printed by the script. Keep permanent dashboard changes in this source JSON;
changes made only in the Grafana UI can be replaced when provisioning is reapplied.

The graphs use a minimum query interval matching each instrument's sampling
interval. Short gaps are connected (90 seconds for pressure, 30 seconds for
temperature); longer outages remain visible as gaps.

## Change collection intervals

1. Edit `INTERVAL` in `collectors/gl840.py` or `collectors/lakeshore325.py` (seconds).
2. Restart the corresponding collector service.
3. Adjust the affected panel's `interval` and `custom.spanNulls` in
   `dashboards/gas-target.json`, and its top-level `refresh` if needed.
4. Apply the dashboard using `scripts/update-dashboard.sh`.

Changing the dashboard refresh interval alone does not change instrument polling.

## Directory layout

```text
/share/grafana/
├── collectors/
│   ├── gl840.py
│   ├── lakeshore325.py
│   └── import_gl840_csv.py
├── dashboards/gas-target.json
├── provisioning/
│   ├── datasource.yaml
│   └── dashboards.yaml
├── services/
├── scripts/
│   ├── apply.sh
│   └── update-dashboard.sh
├── state/
├── logs/
└── README.md
```

Services execute the collectors from this directory. Provisioning is copied to
`/etc/grafana/provisioning/`, and the dashboard JSON is copied to
`/var/lib/grafana/dashboards/gl840.json`. The existing datasource UID is
`gl840-influx`, with database `gl840` at `http://127.0.0.1:8086`.

## CSV backups and historical import

Original CSV data and backup scripts remain under `/share/logger` and
`/share/lakeshore`. The live collectors do not depend on CSV downloads and do not
append to the original CSV files. Original backup/logging tasks are managed separately.

The optional `gl840-influx.service` reads `/share/logger/gl840_daily_test` and uses
checkpoints in `/share/grafana/state`. It imports older data into measurement
`gl840`, which is separate from the live dashboard's `gl840_live` measurement.
Historical imports do not populate the live pressure charts.

Do not delete original data folders or the active import checkpoints. Old Grafana
implementation files under `/share/logger/grafana`, plus
`/share/lakeshore/grafana_live.py` and `/share/lakeshore/install-grafana.sh`, are no
longer used by the migrated service definitions.

## Troubleshooting missing data

1. Check the service journal for successful recent measurements and errors.
2. Confirm that InfluxDB is running and the instrument is powered and reachable.
3. For GL840 `Unexpected configuration` errors, check the channel input/range
   against the supported ranges above. Do not simply remove the range check.
4. For timeouts, check the instrument IP, port, network connection, and other readers.
5. In Grafana, select a recent time range and confirm that auto-refresh is enabled.
6. After code changes, restart the collector; after JSON changes, run the dashboard
   update script and refresh the browser.

A missing value is not automatically a graph problem. The collector must receive
a valid instrument response and successfully write it to InfluxDB first.
