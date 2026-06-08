#!/usr/bin/env python3

import argparse
import curses
import errno
import shutil
import socket
import sys
import threading
import time


class TCPingTarget:
    PENDING = object()

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.label = f"{host}:{port}"

        self.successful_attempts = 0
        self.failed_attempts = 0
        self.starttime = time.time()
        self.min = 0
        self.max = 0
        self.foravg = 0
        self.last = 0
        self.previous_success = None
        self.jitter_total = 0
        self.jitter_samples = 0
        self.consecutive_failures = 0
        self.history = []
        self.status = "waiting"
        self.status_changed_at = time.time()
        self.lock = threading.RLock()

    def start_attempt(self):
        with self.lock:
            self.expire_pending()
            self.history.append(self.PENDING)
            return len(self.history) - 1

    def skip_attempt(self, slot_index):
        with self.lock:
            if slot_index < len(self.history):
                self.history[slot_index] = None

    def expire_pending(self):
        for idx, value in enumerate(self.history):
            if value is self.PENDING:
                self.history[idx] = None

    def ping_once(self, attempt, slot_index):
        try:
            start_time = time.time()
            with socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout,
            ):
                elapsed_time = (time.time() - start_time) * 1000
                self.finish_attempt(attempt, slot_index, elapsed_time, "ok", True)
        except socket.timeout:
            self.finish_attempt(attempt, slot_index, None, "timeout", False)
        except OSError as err:
            self.finish_attempt(
                attempt,
                slot_index,
                None,
                self.short_error(err),
                False,
            )
        except Exception as err:
            self.finish_attempt(
                attempt,
                slot_index,
                None,
                self.short_error(err),
                False,
            )

    def finish_attempt(self, attempt, slot_index, elapsed_time, status, success):
        with self.lock:
            if success:
                self.successful_attempts += 1
                self.consecutive_failures = 0
                self.last = elapsed_time
                self.foravg += elapsed_time
                self.max = max(self.max, elapsed_time)
                if self.min == 0 or elapsed_time < self.min:
                    self.min = elapsed_time
                if self.previous_success is not None:
                    self.jitter_total += abs(elapsed_time - self.previous_success)
                    self.jitter_samples += 1
                self.previous_success = elapsed_time
            else:
                self.failed_attempts += 1
                self.consecutive_failures += 1
            if status != self.status:
                self.status = status
                self.status_changed_at = time.time()
            self.set_history_value(slot_index, elapsed_time)

    @staticmethod
    def short_error(err):
        err_no = getattr(err, "errno", None)
        if err_no == errno.ECONNREFUSED:
            return "refused"
        if err_no in (errno.ENETUNREACH, errno.EHOSTUNREACH):
            return "unreach"
        if getattr(err, "strerror", None):
            return err.strerror
        return str(err)

    def set_history_value(self, slot_index, value):
        if (
            slot_index == len(self.history) - 1
            and self.history[slot_index] is self.PENDING
        ):
            self.history[slot_index] = value

    def real_attempts(self):
        with self.lock:
            return self.successful_attempts + self.failed_attempts

    def avg(self):
        with self.lock:
            attempts = self.successful_attempts + self.failed_attempts
            return self.foravg / attempts if attempts else 0

    def loss_percentage(self):
        with self.lock:
            attempts = self.successful_attempts + self.failed_attempts
            return (self.failed_attempts / attempts) * 100 if attempts else 0

    def mdev(self):
        with self.lock:
            attempts = self.successful_attempts + self.failed_attempts
            return (self.max - self.min) / attempts if attempts else 0

    def elapsed_ms(self):
        return int((time.time() - self.starttime) * 1000)

    def packets_summary(self):
        with self.lock:
            attempts = self.successful_attempts + self.failed_attempts
            loss = (self.failed_attempts / attempts) * 100 if attempts else 0
            return (
                f"{self.label}: {attempts} tx, "
                f"{self.successful_attempts} rx, "
                f"{loss:.2f}% loss, "
                f"{self.elapsed_ms()} ms"
            )

    def rtt_summary(self):
        with self.lock:
            attempts = self.successful_attempts + self.failed_attempts
            avg = self.foravg / attempts if attempts else 0
            mdev = (self.max - self.min) / attempts if attempts else 0
            jitter = (
                self.jitter_total / self.jitter_samples
                if self.jitter_samples
                else 0
            )
            return (
                f"{self.label}: "
                f"{GTCPPing.format_duration(self.min)}/"
                f"{GTCPPing.format_duration(avg)}/"
                f"{GTCPPing.format_duration(self.max)}/"
                f"{GTCPPing.format_duration(mdev)}/"
                f"{GTCPPing.format_duration(jitter)}"
            )

    def snapshot(self, point_width):
        with self.lock:
            jitter = (
                self.jitter_total / self.jitter_samples
                if self.jitter_samples
                else 0
            )
            return {
                "history": self.history[-point_width:],
                "attempts": self.successful_attempts + self.failed_attempts,
                "successful": self.successful_attempts,
                "failed": self.failed_attempts,
                "status": self.status,
                "status_age": time.time() - self.status_changed_at,
                "last": self.last,
                "min": self.min,
                "avg": self.avg(),
                "max": self.max,
                "jitter": jitter,
                "loss": self.loss_percentage(),
                "dim": self.consecutive_failures > 5,
            }


class GTCPPing:
    BRAILLE_DOTS = (
        (0x01, 0x08),
        (0x02, 0x10),
        (0x04, 0x20),
        (0x40, 0x80),
    )

    COLORS = (
        curses.COLOR_GREEN,
        curses.COLOR_CYAN,
        curses.COLOR_YELLOW,
        curses.COLOR_MAGENTA,
        curses.COLOR_BLUE,
        curses.COLOR_RED,
        curses.COLOR_WHITE,
    )
    ANSI_COLORS = ("32", "36", "33", "35", "34", "31", "37")
    SORT_FIELDS = ("ls", "host", "last", "min", "avg", "max", "jtr", "loss")
    SORT_HOTKEYS = {
        ord("l"): "ls",
        ord("h"): "host",
        ord("t"): "last",
        ord("n"): "min",
        ord("a"): "avg",
        ord("x"): "max",
        ord("j"): "jtr",
        ord("o"): "loss",
    }

    def __init__(
        self,
        targets,
        interval=1,
        count=0,
        timeout=3,
        sort_field="host",
        sort_reverse=False,
    ):
        self.targets = targets
        self.interval = interval
        self.count = count
        self.timeout = timeout
        self.colors_enabled = False
        self.sort_field = sort_field
        self.sort_reverse = sort_reverse

    def summary_lines(self, snapshots, scale_max):
        total_attempts = sum(snapshot["attempts"] for snapshot in snapshots)
        total_successful = sum(snapshot["successful"] for snapshot in snapshots)
        total_failed = sum(snapshot["failed"] for snapshot in snapshots)
        total_loss = (
            (total_failed / total_attempts) * 100
            if total_attempts
            else 0
        )
        states = {}
        for snapshot in snapshots:
            states[snapshot["status"]] = states.get(snapshot["status"], 0) + 1
        state_parts = [
            f"{state}={count}"
            for state, count in sorted(states.items())
        ]

        target_count = len(snapshots) or 1
        avg_last = sum(snapshot["last"] for snapshot in snapshots) / target_count
        avg_avg = sum(snapshot["avg"] for snapshot in snapshots) / target_count
        avg_jitter = sum(snapshot["jitter"] for snapshot in snapshots) / target_count

        return [
            (
                f"| total {total_attempts} tx / {total_successful} rx / "
                f"{total_loss:.1f}% loss | states "
                + ", ".join(state_parts)
            ),
            (
                "| avg across hosts "
                f"last {self.format_duration(avg_last)} | "
                f"avg {self.format_duration(avg_avg)} | "
                f"jtr {self.format_duration(avg_jitter)}"
            ),
        ]

    def layout(self, height, width):
        footer_height = 2
        legend_height = min(len(self.targets), max(0, height - 4 - footer_height))
        graph_height = max(1, height - 3 - footer_height - legend_height)
        graph_width = max(1, width - 12)
        host_width = max(8, min(24, width - 72))

        return {
            "footer_height": footer_height,
            "legend_height": legend_height,
            "graph_height": graph_height,
            "graph_width": graph_width,
            "graph_left": 10,
            "host_width": host_width,
        }

    def render_data(self, height, width):
        layout = self.layout(height, width)
        point_width = layout["graph_width"] * 2
        snapshots = [target.snapshot(point_width) for target in self.targets]
        visible_by_target = [snapshot["history"] for snapshot in snapshots]
        values = [
            value
            for visible in visible_by_target
            for value in visible
            if value not in (None, TCPingTarget.PENDING)
        ]
        scale_max = max(values) if values else self.timeout * 1000
        scale_max = max(scale_max, 1)

        return layout, snapshots, visible_by_target, scale_max

    def sorted_indices(self, snapshots):
        indexed = list(range(len(snapshots)))

        def key_for(target_idx):
            snapshot = snapshots[target_idx]
            target = self.targets[target_idx]
            if self.sort_field == "ls":
                return snapshot["status_age"]
            if self.sort_field == "host":
                return target.label.lower()
            if self.sort_field == "last":
                return snapshot["last"]
            if self.sort_field == "min":
                return snapshot["min"]
            if self.sort_field == "avg":
                return snapshot["avg"]
            if self.sort_field == "max":
                return snapshot["max"]
            if self.sort_field == "jtr":
                return snapshot["jitter"]
            if self.sort_field == "loss":
                return snapshot["loss"]
            return target.label.lower()

        return sorted(
            indexed,
            key=lambda target_idx: (key_for(target_idx), self.targets[target_idx].label),
            reverse=self.sort_reverse,
        )

    def set_sort(self, field):
        if field == self.sort_field:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_field = field
            self.sort_reverse = field != "host"

    def draw(self, stdscr):
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        layout, snapshots, visible_by_target, scale_max = self.render_data(
            height,
            width,
        )
        footer_height = layout["footer_height"]
        legend_height = layout["legend_height"]
        graph_height = layout["graph_height"]
        graph_width = layout["graph_width"]
        graph_left = layout["graph_left"]
        host_width = layout["host_width"]

        title = (
            f"GTCPPing {len(self.targets)} targets  "
            f"interval={self.interval}s timeout={self.timeout}s  "
            f"sort={self.sort_field}{' desc' if self.sort_reverse else ' asc'}  "
            "keys l/h/t/n/a/x/j/o,d,q"
        )
        stdscr.addnstr(0, 0, title, width - 1, curses.A_BOLD)

        point_height = graph_height * 4

        for row in range(1, graph_height + 1):
            label_value = scale_max * (graph_height - row + 1) / graph_height
            label = f"{label_value:>7.1f}ms "
            stdscr.addnstr(row, 0, label, min(len(label), width - 1))
            if width > 10:
                stdscr.addch(row, 9, curses.ACS_VLINE)

        baseline = graph_height + 1
        if baseline < height - 3 and width > 10:
            stdscr.hline(baseline, graph_left, curses.ACS_HLINE, graph_width)

        for target_idx, target in enumerate(self.targets):
            color = self.color_attr(target_idx, snapshots[target_idx]["dim"])
            self.draw_target(
                stdscr,
                visible_by_target[target_idx],
                graph_left,
                graph_height,
                point_height,
                scale_max,
                width,
                color,
            )

        legend_start = graph_height + 2
        legend_header = (
            f"{'LS':>8} {'Host':<{host_width}.{host_width}} "
            f"{'last':>10} {'min':>10} {'avg':>10} {'max':>10} "
            f"{'jtr':>10} {'loss':>6}"
        )
        stdscr.addnstr(legend_start, 0, legend_header, width - 1, curses.A_BOLD)
        for row_idx, target_idx in enumerate(self.sorted_indices(snapshots)[:legend_height]):
            target = self.targets[target_idx]
            snapshot = snapshots[target_idx]
            color = self.color_attr(target_idx, snapshot["dim"])
            y = legend_start + 1 + row_idx
            last = self.format_last(snapshot)
            legend = (
                f"{self.format_age(snapshot['status_age']):>8} "
                f"{target.label:<{host_width}.{host_width}} "
                f"{last:>10.10} "
                f"{self.format_duration(snapshot['min']):>10.10} "
                f"{self.format_duration(snapshot['avg']):>10.10} "
                f"{self.format_duration(snapshot['max']):>10.10} "
                f"{self.format_duration(snapshot['jitter']):>10.10} "
                f"{snapshot['loss']:5.1f}%"
            )
            self.addnstr_color(stdscr, y, 0, legend[:width - 1], color)

        for offset, line in enumerate(self.summary_lines(snapshots, scale_max)):
            y = height - footer_height + offset
            if 0 <= y < height:
                stdscr.addnstr(y, 0, line, width - 1)

        stdscr.refresh()

    def print_final(self):
        size = shutil.get_terminal_size((80, 24))
        height = max(10, size.lines)
        width = max(40, size.columns)
        layout, snapshots, visible_by_target, scale_max = self.render_data(
            height,
            width,
        )

        screen = [[" " for _ in range(width)] for _ in range(height)]
        colors = [[None for _ in range(width)] for _ in range(height)]

        def put(y, x, text, color=None):
            if not (0 <= y < height) or x >= width:
                return
            for idx, char in enumerate(text[:max(0, width - x)]):
                screen[y][x + idx] = char
                colors[y][x + idx] = color

        title = (
            f"GTCPPing {len(self.targets)} targets  "
            f"interval={self.interval}s timeout={self.timeout}s"
        )
        put(0, 0, title)

        graph_height = layout["graph_height"]
        graph_width = layout["graph_width"]
        graph_left = layout["graph_left"]
        point_height = graph_height * 4

        for row in range(1, graph_height + 1):
            label_value = scale_max * (graph_height - row + 1) / graph_height
            put(row, 0, f"{label_value:>7.1f}ms |")

        baseline = graph_height + 1
        if baseline < height - layout["footer_height"]:
            put(baseline, graph_left, "-" * graph_width)

        canvas = {}
        failures = {}
        for target_idx, visible in enumerate(visible_by_target):
            self.collect_plain_target(
                canvas,
                failures,
                visible,
                target_idx,
                snapshots[target_idx]["dim"],
                graph_left,
                graph_height,
                point_height,
                scale_max,
                width,
            )

        for (cell_y, cell_x), (dots, color) in canvas.items():
            put(cell_y, cell_x, chr(0x2800 + dots), color)
        for cell_x, color in failures.items():
            put(graph_height, cell_x, "x", color)

        legend_start = graph_height + 2
        host_width = layout["host_width"]
        legend_header = (
            f"{'LS':>8} {'Host':<{host_width}.{host_width}} "
            f"{'last':>10} {'min':>10} {'avg':>10} {'max':>10} "
            f"{'jtr':>10} {'loss':>6}"
        )
        put(legend_start, 0, legend_header)
        for row_idx, target_idx in enumerate(
            self.sorted_indices(snapshots)[:layout["legend_height"]]
        ):
            target = self.targets[target_idx]
            snapshot = snapshots[target_idx]
            last = self.format_last(snapshot)
            legend = (
                f"{self.format_age(snapshot['status_age']):>8} "
                f"{target.label:<{host_width}.{host_width}} "
                f"{last:>10.10} "
                f"{self.format_duration(snapshot['min']):>10.10} "
                f"{self.format_duration(snapshot['avg']):>10.10} "
                f"{self.format_duration(snapshot['max']):>10.10} "
                f"{self.format_duration(snapshot['jitter']):>10.10} "
                f"{snapshot['loss']:5.1f}%"
            )
            put(
                legend_start + 1 + row_idx,
                0,
                legend,
                self.ansi_color(target_idx, snapshot["dim"]),
            )

        for offset, line in enumerate(self.summary_lines(snapshots, scale_max)):
            put(height - layout["footer_height"] + offset, 0, line)

        print(self.render_ansi(screen, colors))

    def collect_plain_target(self, canvas, failures, visible, target_idx, dim,
                             graph_left, graph_height, point_height, scale_max,
                             width):
        previous_point = None
        color = self.ansi_color(target_idx, dim)

        for idx, value in enumerate(visible):
            cell_x = graph_left + (idx // 2)
            if cell_x >= width:
                break

            if value is TCPingTarget.PENDING:
                previous_point = None
                continue

            if value is None:
                failures[cell_x] = color
                previous_point = None
                continue

            normalized = min(1, value / scale_max)
            dot_y_abs = point_height - 1 - int(normalized * (point_height - 1))
            point = (idx, dot_y_abs)
            if previous_point is None:
                self.plot_braille_point(canvas, graph_left, graph_height, *point, color)
            else:
                self.plot_braille_line(
                    canvas,
                    graph_left,
                    graph_height,
                    previous_point,
                    point,
                    color,
                )
            previous_point = point

    def render_ansi(self, screen, colors):
        lines = []
        for row, color_row in zip(screen, colors):
            active_color = None
            rendered = []
            last_non_space = -1
            for idx, char in enumerate(row):
                if char != " ":
                    last_non_space = idx

            for idx, char in enumerate(row[:last_non_space + 1]):
                color = color_row[idx]
                if color != active_color:
                    rendered.append("\033[0m" if color is None else f"\033[{color}m")
                    active_color = color
                rendered.append(char)
            if active_color is not None:
                rendered.append("\033[0m")
            lines.append("".join(rendered))

        return "\n".join(lines)

    def ansi_color(self, target_idx, dim=False):
        color = self.ANSI_COLORS[target_idx % len(self.ANSI_COLORS)]
        return f"2;{color}" if dim else color

    @staticmethod
    def addnstr_color(stdscr, y, x, text, color):
        try:
            stdscr.addnstr(y, x, text, len(text), color)
        except curses.error:
            pass

    def draw_target(self, stdscr, visible, graph_left, graph_height,
                    point_height, scale_max, width, color):
        canvas = {}
        failures = {}
        previous_point = None

        for idx, value in enumerate(visible):
            cell_x = graph_left + (idx // 2)
            if cell_x >= width:
                break

            if value is TCPingTarget.PENDING:
                previous_point = None
                continue

            if value is None:
                failures[cell_x] = True
                previous_point = None
                continue

            normalized = min(1, value / scale_max)
            dot_y_abs = point_height - 1 - int(normalized * (point_height - 1))
            point = (idx, dot_y_abs)
            if previous_point is None:
                self.plot_braille_point(canvas, graph_left, graph_height, *point)
            else:
                self.plot_braille_line(
                    canvas,
                    graph_left,
                    graph_height,
                    previous_point,
                    point,
                )
            previous_point = point

        for (cell_y, cell_x), dots in canvas.items():
            if isinstance(dots, tuple):
                dots = dots[0]
            self.addnstr_color(stdscr, cell_y, cell_x, chr(0x2800 + dots), color)

        for cell_x in failures:
            self.addnstr_color(
                stdscr,
                graph_height,
                cell_x,
                "x",
                color,
            )

    def color_pair(self, target_idx):
        return (target_idx % len(self.COLORS)) + 1

    def color_attr(self, target_idx, dim=False):
        if not self.colors_enabled:
            return curses.A_NORMAL
        attr = curses.color_pair(self.color_pair(target_idx))
        if dim:
            attr |= curses.A_DIM
        return attr

    @staticmethod
    def format_age(seconds):
        if seconds < 60:
            return f"{seconds:6.3f}s"

        minutes = int(seconds // 60)
        if minutes < 60:
            return f"{minutes}m{int(seconds % 60):02d}s"

        hours = minutes // 60
        if hours < 100:
            return f"{hours}h{minutes % 60:02d}m"

        return "99h+"

    @staticmethod
    def format_duration(milliseconds):
        seconds = milliseconds / 1000
        if seconds < 1:
            return f"{milliseconds:.3f}ms"
        return GTCPPing.format_age(seconds)

    @staticmethod
    def format_last(snapshot):
        if snapshot["status"] == "ok":
            return GTCPPing.format_duration(snapshot["last"])
        if snapshot["status"] == "waiting":
            return "waiting"
        if snapshot["status"] == "timeout":
            return "timeout"
        return snapshot["status"][:12]

    def plot_braille_line(self, canvas, graph_left, graph_height, start, end,
                          color=None):
        start_x, start_y = start
        end_x, end_y = end
        distance = max(abs(end_x - start_x), abs(end_y - start_y), 1)

        for step in range(distance + 1):
            x = round(start_x + (end_x - start_x) * step / distance)
            y = round(start_y + (end_y - start_y) * step / distance)
            self.plot_braille_point(canvas, graph_left, graph_height, x, y, color)

    def plot_braille_point(self, canvas, graph_left, graph_height, point_x, point_y,
                           color=None):
        cell_x = graph_left + point_x // 2
        dot_x = point_x % 2
        cell_y = 1 + point_y // 4
        dot_y = point_y % 4

        if 1 <= cell_y <= graph_height:
            current = canvas.get((cell_y, cell_x), (0, color))
            canvas[(cell_y, cell_x)] = (
                current[0] | self.BRAILLE_DOTS[dot_y][dot_x],
                color if color is not None else current[1],
            )

    def run(self, stdscr):
        curses.curs_set(0)
        self.colors_enabled = curses.has_colors()
        if self.colors_enabled:
            curses.use_default_colors()
            for idx, color in enumerate(self.COLORS, start=1):
                curses.init_pair(idx, color, -1)
        stdscr.nodelay(True)

        stop_event = threading.Event()
        active = {}
        attempt = 0
        next_ping = time.monotonic()

        try:
            while True:
                key = stdscr.getch()
                if key in (ord("q"), ord("Q")):
                    stop_event.set()
                    break
                if key in self.SORT_HOTKEYS:
                    self.set_sort(self.SORT_HOTKEYS[key])
                elif key == ord("d"):
                    self.sort_reverse = not self.sort_reverse

                active = {
                    target: worker
                    for target, worker in active.items()
                    if worker.is_alive()
                }

                now = time.monotonic()
                if (self.count == 0 or attempt < self.count) and now >= next_ping:
                    attempt += 1
                    for target in self.targets:
                        slot_index = target.start_attempt()
                        if target in active:
                            target.skip_attempt(slot_index)
                            continue

                        worker = threading.Thread(
                            target=target.ping_once,
                            args=(attempt, slot_index),
                            daemon=True,
                        )
                        active[target] = worker
                        worker.start()
                    next_ping = now + self.interval

                self.draw(stdscr)
                if self.count and attempt >= self.count and not active:
                    break
                time.sleep(0.05)
        finally:
            stop_event.set()
            for worker in active.values():
                worker.join(timeout=0.1)

        stdscr.nodelay(False)


def parse_host(value, default_port):
    if ":" not in value:
        return value, default_port

    host, port = value.rsplit(":", 1)
    if not host:
        raise ValueError("Invalid host value")
    return host, int(port)


def main():
    parser = argparse.ArgumentParser(description="Graphical TCP Ping Utility")
    parser.add_argument(
        "hosts",
        nargs="+",
        type=str,
        help="One or more Host[:port] values to TCP Ping",
    )
    parser.add_argument(
        "-c",
        "--count",
        type=int,
        default=0,
        help="Number of attempts (default: infinite)",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=1,
        help="Interval in seconds between sending each packet (default: 1)",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=80,
        help="Port to TCP Ping (default: 80)",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=1,
        help="Timeout in seconds (default: 3)",
    )
    parser.add_argument(
        "-s",
        "--sort",
        choices=GTCPPing.SORT_FIELDS,
        default="host",
        help="Initial table sort field (default: host)",
    )
    parser.add_argument(
        "--descending",
        action="store_true",
        help="Sort the table in descending order",
    )

    args = parser.parse_args()

    try:
        if args.interval <= 0:
            raise ValueError("Interval must be greater than zero")
        if args.timeout <= 0:
            raise ValueError("Timeout must be greater than zero")
        targets = [
            TCPingTarget(host, int(port), args.timeout)
            for host, port in (parse_host(value, args.port) for value in args.hosts)
        ]
        gtcpping = GTCPPing(
            targets,
            timeout=args.timeout,
            interval=args.interval,
            count=args.count,
            sort_field=args.sort,
            sort_reverse=args.descending,
        )
        try:
            curses.wrapper(gtcpping.run)
        except KeyboardInterrupt:
            pass
        finally:
            gtcpping.print_final()
    except ValueError as err:
        print(err or "Invalid int value")
        return 1
    except KeyboardInterrupt:
        return 0
    except Exception as err:
        print(f"Unexpected {err=}, {type(err)=} {type(err)}")
        return 255

    return 0


if __name__ == "__main__":
    sys.exit(main())
