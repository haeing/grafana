#!/usr/bin/env python3
"""Read Lake Shore 325 temperature A, setpoint and heater without control writes."""
import datetime as dt
import math
import socket
import time
import urllib.request

HOST = '192.168.10.105'
PORT = 4196
INTERVAL = 10.0

def query(sock, stream, command):
    sock.sendall((command+'\r\n').encode('ascii'))
    response = stream.readline(4096)
    if not response.endswith(b'\n'):
        raise ConnectionError('Incomplete Lake Shore response')
    return response.decode('ascii').strip()

def read_values(sock, stream):
    values = []
    for command in ('KRDG? A', 'SETP? 1', 'HTR?'):
        value = float(query(sock, stream, command))
        if not math.isfinite(value):
            raise ValueError('Invalid response for '+command)
        values.append(value)
        time.sleep(0.1)
    if values[0] <= 0 or values[1] < 0 or not 0 <= values[2] <= 100:
        raise ValueError('Invalid temperature / setpoint / heater: '+str(values))
    return values

def publish(values):
    line = 'lakeshore325 temperature_a_k={},setpoint_1_k={},heater_output_percent={} {}'.format(
        *values, time.time_ns()//1000000)
    request = urllib.request.Request('http://127.0.0.1:8086/write?db=gl840&precision=ms',
                                     data=line.encode(), method='POST')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=5) as response:
        if response.status != 204:
            raise RuntimeError('InfluxDB write failed: '+str(response.status))

def main():
    while True:
        try:
            with socket.create_connection((HOST, PORT), timeout=5) as sock:
                with sock.makefile('rb') as stream:
                    identity = query(sock, stream, '*IDN?')
                    if '325' not in identity:
                        raise ValueError('Unexpected instrument: '+identity)
                    print('Connected: '+identity, flush=True)
                    deadline = time.monotonic()
                    while True:
                        values = read_values(sock, stream)
                        publish(values)
                        print('{} A={} K, Setpoint={} K, Heater={} %'.format(
                            dt.datetime.now(dt.timezone.utc).isoformat(), *values), flush=True)
                        deadline += INTERVAL
                        if deadline < time.monotonic():
                            deadline = time.monotonic()
                        time.sleep(max(0, deadline-time.monotonic()))
        except (OSError, ValueError, RuntimeError) as error:
            print('Lake Shore collection failed; retry in 10s: '+str(error), flush=True)
            time.sleep(INTERVAL)

if __name__ == '__main__':
    main()
