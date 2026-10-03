"""Data sources for the live pipeline.

Every source yields data-contract dicts (docs/data_contract.md), one per window,
so the rest of the backend never cares where the data came from.

    SimSource      the motor simulator, paced in real time, faults switchable live
    ReplaySource   plays a recorded CSV (data/sim/*.csv) in a loop - the demo safety net
    SerialSource   the ESP32 over USB serial (JSON lines at 921600 baud)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from simulator.motor_sim import CONDITIONS, WINDOW_SEC, MotorSimulator, read_recording

ROOT = Path(__file__).resolve().parent.parent
SIM_DIR = ROOT / "data" / "sim"
DATA_DIR = ROOT / "data"


class SourceError(RuntimeError):
    """Raised when a source can't deliver data (unplugged ESP32, missing file...)."""


class Source:
    kind = "base"
    name = "base"
    can_inject_faults = False

    def read(self) -> dict:
        """Block until the next window is ready and return it."""
        raise NotImplementedError

    def close(self):
        pass

    def describe(self) -> dict:
        return {"kind": self.kind, "name": self.name, "can_inject_faults": self.can_inject_faults}


class _Paced(Source):
    """Releases one window every WINDOW_SEC / speed seconds of wall time."""

    def __init__(self, speed=1.0):
        self.speed = max(0.1, float(speed))
        self._next = time.monotonic()

    def _wait(self):
        self._next += WINDOW_SEC / self.speed
        delay = self._next - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:                       # fell behind (slow laptop) - don't try to catch up
            self._next = time.monotonic()


class SimSource(_Paced):
    kind = "sim"
    can_inject_faults = True

    def __init__(self, rpm=5000, seed=None, speed=1.0, ramp_seconds=120.0):
        super().__init__(speed)
        self.rpm = float(rpm)
        self.seed = seed
        self.ramp_seconds = ramp_seconds
        self.sim = MotorSimulator("healthy", self.rpm, seed=seed, ramp_seconds=ramp_seconds,
                                  wall_clock=True)
        self.name = f"Simulator @ {int(self.rpm)} rpm"

    def read(self) -> dict:
        self._wait()
        return self.sim.next_window()

    def set_condition(self, condition: str, severity: float | None = None):
        if condition not in CONDITIONS:
            raise ValueError(f"unknown condition {condition!r}; choose from {CONDITIONS}")
        if severity is not None:
            self.sim.fixed_severity = float(np.clip(severity, 0.05, 1.0))
        self.sim.set_condition(condition)

    def describe(self) -> dict:
        d = super().describe()
        d.update(rpm=self.rpm, condition=self.sim.condition,
                 severity=round(self.sim.severity(), 2), conditions=list(CONDITIONS))
        return d


class ReplaySource(_Paced):
    kind = "replay"

    def __init__(self, path, speed=1.0, loop=True):
        super().__init__(speed)
        self.path = Path(path)
        if not self.path.is_absolute():
            # "events/x.csv" -> data/events (alert black-box files); anything else -> data/sim
            self.path = (DATA_DIR / self.path) if str(path).replace("\\", "/").startswith("events/") \
                else SIM_DIR / self.path
        try:
            self.path.resolve().relative_to(DATA_DIR.resolve())
        except ValueError:
            raise SourceError("recordings must be inside the data/ folder") from None
        if not self.path.exists():
            raise SourceError(f"recording not found: {self.path.name}")
        self.loop = loop
        self.name = f"Replay: {self.path.name}"
        self._it = read_recording(self.path)
        self.position = 0

    def read(self) -> dict:
        self._wait()
        try:
            rec = next(self._it)
        except StopIteration:
            if not self.loop:
                raise SourceError("replay finished")
            self._it = read_recording(self.path)
            self.position = 0
            rec = next(self._it)
        self.position += 1
        rec["vib"] = rec["vib"].tolist() if hasattr(rec["vib"], "tolist") else rec["vib"]
        rec["source"] = f"replay:{self.path.stem}"
        rec["ts"] = time.time()          # replay "now", so trends and TTF behave
        rec.pop("label", None)           # ground truth is never a model input
        return rec


class SerialSource(Source):
    """ESP32 over USB. Keeps going on its own: if the cable is pulled or the board
    resets, every read tries to reopen the port, so live data resumes by itself
    as soon as the sensor is back. port="auto" picks the first USB serial port."""
    kind = "serial"

    def __init__(self, port: str, baud: int = 921600, timeout: float = 3.0):
        try:
            import serial  # pyserial
        except ImportError as e:
            raise SourceError("pyserial is not installed: pip install pyserial") from e
        self._serial = serial
        self.want_port, self.baud, self.timeout = port, baud, timeout
        self.ser = None
        self.port = None
        self._open()                      # fail fast on the first open, like before
        self.name = f"ESP32 on {self.port}"

    def _pick_port(self):
        if self.want_port and self.want_port.lower() != "auto":
            return self.want_port
        ports = list_serial_ports()
        if not ports:
            raise SourceError("no serial ports found - is the ESP32 plugged in?")
        return ports[0]

    def _open(self):
        port = self._pick_port()
        try:
            self.ser = self._serial.Serial(port, self.baud, timeout=self.timeout)
        except Exception as e:  # noqa: BLE001 - any open failure means "not connected"
            self.ser = None
            raise SourceError(f"cannot open {port}: {e}") from e
        self.port = port

    def _drop(self, why):
        self.close()
        self.ser = None
        raise SourceError(why)

    def read(self) -> dict:
        if self.ser is None:
            self._open()                  # reconnect attempt; engine retries every second
        for _ in range(20):               # skip boot messages / partial lines
            try:
                line = self.ser.readline()
            except Exception as e:  # noqa: BLE001
                self._drop(f"serial read failed: {e}")
            if not line:
                self._drop("no data from ESP32 (timeout) - reconnecting")
            try:
                rec = json.loads(line.decode("utf-8", "ignore"))
            except json.JSONDecodeError:
                continue
            if {"rpm", "fs", "vib"} <= rec.keys():
                rec.setdefault("ts", time.time())
                rec.setdefault("source", "esp32")
                return rec
        raise SourceError("ESP32 is sending lines that don't match the data contract")

    def close(self):
        try:
            if self.ser is not None:
                self.ser.close()
        except Exception:  # noqa: BLE001
            pass


def list_recordings() -> list[dict]:
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    out = [{"file": p.name, "size_kb": round(p.stat().st_size / 1024)} for p in sorted(SIM_DIR.glob("*.csv"))]
    ev = DATA_DIR / "events"
    if ev.exists():   # black-box files saved around alerts - newest first
        out += [{"file": f"events/{p.name}", "size_kb": round(p.stat().st_size / 1024)}
                for p in sorted(ev.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)]
    return out


def list_serial_ports() -> list[str]:
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:  # noqa: BLE001
        return []
