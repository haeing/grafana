#!/usr/bin/env python3
"""Read GL840 instantaneous measurements every thirty seconds, without settings writes."""
import argparse
import datetime as dt
import math
import socket
import struct
import time
import urllib.request

HOST = '192.168.10.104'
INTERVAL = 30.0

def decode(payload):
    if len(payload) != 48:
        raise ValueError('Expected verified 20-channel GL840 payload (48 bytes)')
    raw = struct.unpack('>24h', payload)
    # Supported ranges: CH1=1-5V or 10V, CH3=10V; 2000 counts/V.
    volts = [raw[0] / 2000.0, raw[2] / 2000.0]
    # Do not convert overrange codes into plausible pressure readings.
    if not (-11.0 <= volts[0] <= 11.0 and -11.0 <= volts[1] <= 11.0):
        raise ValueError('Invalid or overrange voltage: {}'.format(volts))
    target = (volts[0] - 1.0) * 937.58
    chamber = 10.0 ** (2.0 * (volts[1] - 5.5))
    if not all(math.isfinite(x) for x in (target, chamber)):
        raise ValueError('Non-finite pressure')
    return volts[0], volts[1], target, chamber

class Device:
    def __enter__(self):
        self.socket = socket.create_connection((HOST, 8023), timeout=3)
        self.stream = self.socket.makefile('rb')
        try:
            for command, expected in (
                (':AMP:CH1:INP?', ('DC',)), (':AMP:CH1:RANG?', ('1-5V', '10V')),
                (':AMP:CH3:INP?', ('DC',)), (':AMP:CH3:RANG?', ('10V',))):
                self.socket.sendall((command+'\r\n').encode())
                reply = self.stream.readline(4096).decode('ascii').strip()
                prefix = command[:-1] + ' '
                if not reply.startswith(prefix) or reply[len(prefix):] not in expected:
                    raise ValueError('Unexpected configuration: '+reply)
        except Exception:
            self.__exit__(None, None, None)
            raise
        print("GL840 channel configuration accepted (CH1=1-5V/10V, CH3=10V)", flush=True)
        return self

    def read_exact(self, size):
        result = bytearray()
        while len(result) < size:
            chunk = self.stream.read(size-len(result))
            if not chunk:
                raise ConnectionError('GL840 closed the connection')
            result.extend(chunk)
        return bytes(result)

    def sample(self):
        self.socket.sendall(b':MEAS:OUTP:ONE?\r\n')
        first = self.read_exact(1)
        # Some firmware terminates binary blocks with CR/LF.
        for _ in range(2):
            if first not in (b'\r', b'\n'):
                break
            first = self.read_exact(1)
        header = first + self.read_exact(7)
        if header[:2] != b'#6' or not header[2:].isdigit():
            raise ValueError('Invalid binary header: {!r}'.format(header))
        size = int(header[2:])
        if size != 48:
            raise ValueError('Unexpected GL840 block length: {}'.format(size))
        return decode(self.read_exact(size))

    def __exit__(self, *args):
        self.stream.close()
        self.socket.close()

def publish(values):
    ch1, ch3, target, chamber = values
    timestamp = time.time_ns() // 1000000
    line = ('gl840_live ch1_voltage={},ch3_voltage={},target_pressure_torr={},'
            'chamber_pressure_torr={} {}').format(ch1, ch3, target, chamber, timestamp)
    request = urllib.request.Request('http://127.0.0.1:8086/write?db=gl840&precision=ms',
                                     data=line.encode(), method='POST')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=3) as response:
        if response.status != 204:
            raise RuntimeError('InfluxDB write returned {}'.format(response.status))

def report(values):
    print('{} CH1={:.6g} V -> {:.6g} Torr; CH3={:.6g} V -> {:.6g} Torr [CH1 raw={}, divisor=2000, calibration unverified]'.format(
        dt.datetime.now(dt.timezone.utc).isoformat(), *[values[i] for i in (0,2,1,3)], round(values[0]*2000)), flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    while True:
        try:
            with Device() as device:
                deadline = time.monotonic()
                while True:
                    values = device.sample()
                    if not args.dry_run:
                        publish(values)
                    report(values)
                    if args.once:
                        return
                    deadline += INTERVAL
                    if deadline < time.monotonic():
                        deadline = time.monotonic()
                    time.sleep(max(0, deadline-time.monotonic()))
        except Exception as error:
            if args.once:
                raise
            print('Live collection failed; retry in 30 seconds: {}'.format(error), flush=True)
            time.sleep(INTERVAL)

if __name__ == '__main__':
    main()
