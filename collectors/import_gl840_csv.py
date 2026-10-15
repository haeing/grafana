#!/usr/bin/env python3
"""Incrementally import GL840 daily CSV into local InfluxDB 1.x."""
import argparse
import csv
import datetime as dt
import fcntl
import json
import math
from pathlib import Path
import time
import urllib.request

BASE = Path('/share/grafana/state')
SOURCE = Path('/share/logger/gl840_daily_test')
KST = dt.timezone(dt.timedelta(hours=9))

def point(row):
    if not row or not row[0].strip().isdigit():
        return None
    if len(row) < 6:
        raise ValueError('Incomplete CSV row')
    stamp = dt.datetime.strptime(row[1].strip(), '%Y/%m/%d %H:%M:%S').replace(tzinfo=KST)
    millis = int(row[2].strip())
    if not 0 <= millis <= 999:
        raise ValueError('Invalid milliseconds')
    fields = []
    for name, index in (('ch1', 3), ('ch3', 5)):
        raw = ''.join(row[index].split())
        # GL840 uses repeated signs for overload / unavailable readings.
        if raw and set(raw) <= set('+-'):
            continue
        value = float(raw)
        if math.isfinite(value):
            fields.append('{}={}'.format(name, value))
            if name == 'ch3':
                try:
                    pressure = 10.0 ** (2.0 * (value - 5.5))
                except OverflowError:
                    pressure = float('inf')
                if math.isfinite(pressure) and pressure > 0:
                    fields.append('chamber_pressure_torr={}'.format(pressure))
    if not fields:
        return None
    timestamp = int(stamp.timestamp()) * 1000 + millis
    return 'gl840 {} {}'.format(','.join(fields), timestamp)

def run(dry_run=False):
    # New checkpoint replays historical CSV to add converted pressure fields.
    state_path = BASE / 'state-pressure-v1.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    count = 0
    for path in sorted(SOURCE.glob('*/*.CSV')):
        key = str(path)
        size = path.stat().st_size
        offset = state.get(key, 0)
        if size < offset:
            offset = 0
        if size == offset:
            continue
        with path.open('rb') as source:
            source.seek(offset)
            while True:
                batch = []
                end = source.tell()
                for _ in range(5000):
                    raw = source.readline()
                    if not raw or not raw.endswith(b'\n'):
                        break
                    row = next(csv.reader([raw.decode('ascii')]))
                    value = point(row)
                    if value is not None:
                        batch.append(value)
                    end = source.tell()
                if end == offset:
                    break
                if dry_run:
                    if batch and count == 0:
                        print('First point:', batch[0])
                elif batch:
                    request = urllib.request.Request(
                        'http://127.0.0.1:8086/write?db=gl840&precision=ms',
                        data='\n'.join(batch).encode(), method='POST')
                    with urllib.request.urlopen(request, timeout=30) as response:
                        if response.status != 204:
                            raise RuntimeError('Unexpected write response')
                count += len(batch)
                offset = end
                if not dry_run:
                    state[key] = offset
                    temporary = state_path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(state))
                    temporary.replace(state_path)
    print('{} points {}'.format(count, 'validated (no writes)' if dry_run else 'written'), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    with (BASE / 'collector.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                run(args.dry_run)
            except Exception as error:
                if not args.watch:
                    raise
                print('Import failed; will retry:', error, flush=True)
            if not args.watch:
                break
            time.sleep(30)
