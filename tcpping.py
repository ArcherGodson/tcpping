#!/usr/bin/env python3

import socket
import time
import argparse
import signal
import sys

class TCPing:
    def __init__(self, host, port = 80, timeout = 3, count = -1):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.count = count if count else 2^63-1
        self.successful_attempts = 0
        self.failed_attempts = 0
        self.starttime = time.time()
        self.min = 0
        self.max = 0
        self.foravg = 0
        self.avg = 0

    def signal_handler(self, sig, frame):
        self.print_summary("Interrupted by user")
        sys.exit(0)

    def print_summary(self, message):
        real_attempts = self.successful_attempts+self.failed_attempts
        self.avg = self.foravg / real_attempts
        loss_percentage = (self.failed_attempts / real_attempts ) * 100 if real_attempts else 0
#        mdev = self.avg - self.min if self.avg - self.min > self.max - self.avg else self.max - self.avg
        mdev = (self.max - self.min) / real_attempts
        print(f"\n--- {self.host}:{self.port} TCP Ping statistics ---")
        print(f"{real_attempts} packets transmitted, {self.successful_attempts} packets received, {loss_percentage:.2f}% packet loss, time {int((time.time()-self.starttime)*1000)} ms")
        print(f"rtt min/avg/max/mdev = {self.min:.3f}/{self.max:.3f}/{self.avg:.3f}/{mdev:.3f} ms")
#        print(message)

    def tcping(self):
        print(f"TCP Ping to {self.host}:{self.port} with timeout {self.timeout*1000} ms:")
        signal.signal(signal.SIGINT, self.signal_handler)

        for attempt in range(1, self.count + 1):
            start_time = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            try:
                sock.connect((self.host, self.port))
                elapsed_time = (time.time() - start_time) * 1000  # Time in milliseconds
                print(f"Reply from {self.host}:{self.port} tcp_seq={attempt} time={elapsed_time:.2f} ms")
                self.successful_attempts += 1
                self.foravg += elapsed_time
                if elapsed_time > self.max:
                    self.max = elapsed_time
                if (elapsed_time < self.min) or (attempt == 1):
                    self.min = elapsed_time
            except socket.timeout:
                print(f"Request to {self.host}:{self.port} tcp_seq={attempt} timeout")
                self.failed_attempts += 1
            except socket.error as e:
                print(f"Request to {self.host}:{self.port} tcp_seq={attempt} {e}")
                self.failed_attempts += 1
            finally:
                sock.close()
            if attempt != self.count:
                time.sleep(args.interval)  # Delay between attempts
        self.print_summary("All attempts completed")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='TCP Ping Utility')
    parser.add_argument('host', type=str, help='Host[:port] to TCP Ping')
    parser.add_argument('-c', '--count', type=int, help='Number of attempts (default: infinite)')
    parser.add_argument('-i', '--interval', type=float, default=1, help='Interval in seconds between sending each packet (default: 1)')
    parser.add_argument('-p', '--port', type=int, default=80, help='Port to TCP Ping (default: 80)')
    parser.add_argument('-t', '--timeout', type=float, default=1, help='Timeout in seconds (default: 3)')

    args = parser.parse_args()
    try:
        if len(args.host.split(':')) > 1:
            args.host, args.port = args.host.split(':')
        tcping = TCPing(args.host, int(args.port), args.timeout, args.count)
        tcping.tcping()
    except ValueError:
        print(f"Invalid int value")
        exit(1)
    except Exception as err:
        print(f"Unexpected {err=}, {type(err)=} {type(err)}")
        exit(255)
