"""Telemetry hub: pyserial thread (or simulator), ring buffer, parser, state derivation, ACK tracking."""
import math
import threading
import time
from collections import deque
from datetime import datetime

import serial
import serial.tools.list_ports

from simulator import Board

BAUD = 9600
LINK_TIMEOUT = 3.0
ARDUINO_VIDS = {0x2341, 0x2A03, 0x1A86, 0x0403, 0x10C4}  # Arduino, CH340, FTDI, CP210x


def list_serial_ports():
    """Every serial port pyserial can see, flagged if it looks like an Arduino."""
    out = []
    for p in serial.tools.list_ports.comports():
        desc = p.description or ""
        looks = (p.vid in ARDUINO_VIDS) or any(
            k in (desc + (p.manufacturer or "")).lower() for k in ("arduino", "ch340", "usb serial")
        )
        out.append({
            "port": p.device,
            "description": desc,
            "manufacturer": p.manufacturer or "",
            "vid:pid": f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None else "",
            "arduino": looks,
        })
    out.sort(key=lambda r: (not r["arduino"], r["port"]))
    return out


def parse_packet(line):
    """'T:31.2, H:48 ,D:8.5,...' -> dict, or None if not a telemetry line. NaN -> None."""
    fields = {}
    for item in line.strip().split(","):
        if ":" not in item:
            continue
        k, v = item.strip().split(":", 1)
        fields[k.strip().upper()] = v.strip()
    if "T" not in fields or "LOCK" not in fields:
        return None

    def num(key, default=None):
        raw = fields.get(key)
        if raw is None:
            return default
        try:
            x = float(raw)
        except ValueError:
            return None
        return None if math.isnan(x) else x

    def intval(key, default=0):
        x = num(key)
        return default if x is None else int(x)

    thr = num("THR")
    return {
        "t": num("T"), "h": num("H"), "d": num("D"),
        "occ": intval("OCC"), "lock": intval("LOCK"), "fan": intval("FAN"),
        "srv": intval("SRV"), "buz": intval("BUZ"),
        "thr": thr, "mode": fields.get("MODE", "AUTO").upper(), "sil": intval("SIL"),
    }


def derive_state(r, thr):
    t = r["t"]
    if t is None:
        return "FAIL-SAFE"
    if r["occ"] and r["lock"]:
        if r["mode"] == "VENT":
            return "MANUAL VENT"
        if r["fan"]:
            return "CRITICAL" if t >= thr else "HYSTERESIS"
        if r["buz"] or r["sil"]:
            return "ALERT"
        return "SECURE"  # occupied + locked, still inside the 10 s grace period
    if r["mode"] == "VENT":
        return "MANUAL VENT"
    return "SECURE"


RANK = {"SECURE": 0, "MANUAL VENT": 1, "HYSTERESIS": 1, "ALERT": 2, "CRITICAL": 3, "FAIL-SAFE": 3}


class Hub:
    def __init__(self):
        self.lock = threading.RLock()
        self.buf = deque(maxlen=600)
        self.events = deque(maxlen=300)
        self._seq = 0
        self.source = "sim"          # "sim" | "serial"
        self.port = None
        self.status = "idle"
        self.last_packet = 0.0       # time.monotonic()
        self.threshold = 32.0
        self.state = "SECURE"
        self.link_lost_flag = True
        self.pending = []            # [cmd, predicate, sent_monotonic]
        self.board = Board()
        self._ser = None
        self._thread = None
        self._stop = threading.Event()
        self._log("sys", "Hub created")

    # ---- events -----------------------------------------------------
    def _log(self, kind, text):
        with self.lock:
            self._seq += 1
            self.events.appendleft({"seq": self._seq, "ts": datetime.now(), "kind": kind, "text": text})

    # ---- source control --------------------------------------------
    def configure(self, source, port=None):
        with self.lock:
            if source == self.source and port == self.port and self._thread and self._thread.is_alive():
                return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._stop = threading.Event()
        with self.lock:
            self.source, self.port = source, port
            self.last_packet = 0.0
            self.status = "starting"
            self.pending.clear()
        target = self._run_serial if source == "serial" else self._run_sim
        self._thread = threading.Thread(target=target, args=(self._stop,), daemon=True)
        self._thread.start()
        self._log("sys", f"Source -> {source.upper()}" + (f" on {port}" if port else ""))

    def _run_sim(self, stop):
        self.status = "simulator running"
        while not stop.is_set():
            self._ingest(self.board.step())
            stop.wait(1.0)

    def _run_serial(self, stop):
        while not stop.is_set():
            if not self.port:
                self.status = "no port selected"
                stop.wait(1.0)
                continue
            try:
                self.status = f"opening {self.port}"
                ser = serial.Serial(self.port, BAUD, timeout=1)
                self._ser = ser
                stop.wait(2.0)  # Uno resets when the port opens
                ser.reset_input_buffer()
                self.status = f"connected {self.port} @ {BAUD}"
                self._log("sys", f"Serial open {self.port} @ {BAUD}")
                while not stop.is_set():
                    raw = ser.readline().decode("ascii", errors="ignore")
                    if raw:
                        self._ingest(raw)
            except (serial.SerialException, OSError) as e:
                self.status = f"error: {str(e)[:60]}"
                self._log("sys", f"Serial error: {str(e)[:80]}")
                stop.wait(2.0)
            finally:
                if self._ser:
                    try:
                        self._ser.close()
                    except Exception:
                        pass
                    self._ser = None

    # ---- ingest -----------------------------------------------------
    def _ingest(self, line):
        p = parse_packet(line)
        if p is None:
            return
        with self.lock:
            if p["thr"] is None:
                p["thr"] = self.threshold
            self.threshold = p["thr"]
            state = derive_state(p, p["thr"])
            row = dict(p, ts=datetime.now(), state=state, failsafe=p["t"] is None)
            self.buf.append(row)
            self.last_packet = time.monotonic()
            if self.link_lost_flag:
                self.link_lost_flag = False
                self._log("link", "LINK RESTORED")
            if state != self.state:
                kind = "alert" if RANK[state] > RANK[self.state] and RANK[state] >= 2 else "state"
                T = "NaN" if p["t"] is None else f"{p['t']:.1f}C"
                self._log(kind, f"STATE {self.state} -> {state} (T: {T})")
                self.state = state
            now = time.monotonic()
            for item in list(self.pending):
                cmd, pred, sent = item
                if pred(p):
                    self.pending.remove(item)
                    self._log("ack", f"CMD {cmd} ACK ({now - sent:.1f}s)")
                elif now - sent > 3.0:
                    self.pending.remove(item)
                    self._log("nack", f"CMD {cmd} NO ACK")

    # ---- commands ---------------------------------------------------
    def send(self, cmd):
        cmd = cmd.strip().upper()
        if cmd.startswith("SET:"):
            want = float(cmd[4:])
            pred = lambda p: p["thr"] is not None and abs(p["thr"] - want) < 0.01
            self.threshold = want
        elif cmd == "VENT":
            pred = lambda p: p["mode"] == "VENT"
        elif cmd == "SILENCE":
            pred = lambda p: p["sil"] == 1
        elif cmd == "AUTO":
            pred = lambda p: p["mode"] == "AUTO" and p["sil"] == 0
        else:
            return False
        with self.lock:
            self.pending.append([cmd, pred, time.monotonic()])
            self._log("cmd", f"CMD {cmd} sent (PC -> Arduino)")
        if self.source == "sim":
            self._ingest(self.board.command(cmd))
            return True
        try:
            if self._ser and self._ser.is_open:
                self._ser.write((cmd + "\n").encode())
                return True
        except (serial.SerialException, OSError):
            pass
        self._log("nack", f"CMD {cmd} not sent: no serial link")
        return False

    # ---- read side --------------------------------------------------
    def snapshot(self):
        with self.lock:
            age = time.monotonic() - self.last_packet if self.last_packet else None
            lost = age is None or age > LINK_TIMEOUT
            if lost and not self.link_lost_flag and self.last_packet:
                self.link_lost_flag = True
                self._log("alert", "LINK LOST - stale data")
            rows = list(self.buf)
            return {
                "rows": rows, "last": rows[-1] if rows else None, "lost": lost, "age": age,
                "state": "LINK LOST" if lost else self.state, "threshold": self.threshold,
                "events": list(self.events), "source": self.source, "port": self.port,
                "status": self.status,
            }
