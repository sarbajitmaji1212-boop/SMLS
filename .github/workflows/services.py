from __future__ import annotations

import csv
import ctypes
import json
import os
import io
import threading
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

import psutil

APP_NAME = "SARBA GUI"
APP_VERSION = "1.0.0-test"


def app_data_dir() -> Path:
    base = Path(os.environ.get("APPDATA", str(Path.home())))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def resource_path(relative: str) -> Path:
    """Find a file beside source or inside a PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def configure_logging() -> Path:
    """Persist runtime diagnostics outside Program Files so install permissions do not block logs."""
    import logging
    log_dir = app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "SARBA-GUI.log"
    logging.basicConfig(filename=str(log_path), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", encoding="utf-8")
    logging.info("Starting %s %s", APP_NAME, APP_VERSION)
    return log_path


def load_settings() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "auto_clean_temp": False,
        "show_overlay_on_start": False,
        "fps_process_name": "HD-Player.exe",
        "games": [],
        "first_run": True,
    }
    try:
        saved = json.loads(settings_path().read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            defaults.update(saved)
    except (OSError, ValueError, TypeError):
        pass
    return defaults


def save_settings(data: dict[str, Any]) -> None:
    path = settings_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _run_text(args: list[str], timeout: float = 3.0) -> str:
    try:
        cp = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            errors="replace")
        if cp.returncode == 0:
            return cp.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


@dataclass
class SystemMetrics:
    cpu_percent: float | None = None
    ram_percent: float | None = None
    ram_used_gb: float | None = None
    ram_total_gb: float | None = None
    gpu_name: str = "GPU unavailable"
    gpu_percent: float | None = None
    gpu_temp_c: float | None = None
    gpu_mem_used_mb: float | None = None
    gpu_mem_total_mb: float | None = None
    gpu_fan_percent: float | None = None
    gpu_driver: str = "Unknown"
    fps: float | None = None
    fps_status: str = "Start FPS capture for a running game"
    time_text: str = ""


def _to_float(raw: str) -> float | None:
    value = raw.strip()
    if not value or value.upper() in {"N/A", "[N/A]", "NOT SUPPORTED", "UNKNOWN"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class Telemetry:
    """Live OS counters; potentially slow GPU-driver polling runs off the UI thread."""
    def __init__(self) -> None:
        psutil.cpu_percent(interval=None)
        self.last = SystemMetrics()
        self._gpu_lock = threading.Lock()
        self._gpu_stop = threading.Event()
        self._gpu_snapshot: dict[str, Any] = {
            "gpu_name": "Checking NVIDIA driver…", "gpu_percent": None, "gpu_temp_c": None,
            "gpu_mem_used_mb": None, "gpu_mem_total_mb": None, "gpu_fan_percent": None, "gpu_driver": "Unknown"
        }
        self._gpu_thread = threading.Thread(target=self._poll_gpu, name="SARBA-GPU-telemetry", daemon=True)
        self._gpu_thread.start()

    def _poll_gpu(self) -> None:
        nvidia_smi = shutil.which("nvidia-smi")
        if not nvidia_smi and os.name == "nt":
            roots = [
                Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
            ]
            nvidia_smi = next((str(p) for p in roots if p.is_file()), "nvidia-smi")
        if not nvidia_smi:
            nvidia_smi = "nvidia-smi"
        query_args = [
            nvidia_smi, "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,fan.speed,driver_version",
            "--format=csv,noheader,nounits"
        ]
        while not self._gpu_stop.is_set():
            query = _run_text(query_args, timeout=2.5)
            snapshot: dict[str, Any]
            if query:
                row = next(csv.reader([query], skipinitialspace=True), [])
                try:
                    if len(row) >= 7:
                        snapshot = {
                            "gpu_name": row[0].strip(),
                            "gpu_percent": _to_float(row[1]),
                            "gpu_mem_used_mb": _to_float(row[2]),
                            "gpu_mem_total_mb": _to_float(row[3]),
                            "gpu_temp_c": _to_float(row[4]),
                            "gpu_fan_percent": _to_float(row[5]),
                            "gpu_driver": row[6].strip(),
                        }
                    else:
                        snapshot = {"gpu_name": "NVIDIA metrics unavailable", "gpu_percent": None,
                                    "gpu_mem_used_mb": None, "gpu_mem_total_mb": None, "gpu_temp_c": None,
                                    "gpu_fan_percent": None, "gpu_driver": "Unknown"}
                except (ValueError, IndexError):
                    snapshot = {"gpu_name": "NVIDIA GPU detected; metrics unavailable", "gpu_percent": None,
                                "gpu_mem_used_mb": None, "gpu_mem_total_mb": None, "gpu_temp_c": None,
                                "gpu_fan_percent": None, "gpu_driver": "Unknown"}
            else:
                snapshot = {"gpu_name": "NVIDIA telemetry unavailable", "gpu_percent": None,
                            "gpu_mem_used_mb": None, "gpu_mem_total_mb": None, "gpu_temp_c": None,
                            "gpu_fan_percent": None, "gpu_driver": "Unknown"}
            with self._gpu_lock:
                self._gpu_snapshot = snapshot
            self._gpu_stop.wait(2.0)

    def sample(self, fps: float | None = None, fps_status: str | None = None) -> SystemMetrics:
        vm = psutil.virtual_memory()
        self.last.cpu_percent = psutil.cpu_percent(interval=None)
        self.last.ram_percent = float(vm.percent)
        self.last.ram_used_gb = vm.used / (1024 ** 3)
        self.last.ram_total_gb = vm.total / (1024 ** 3)
        self.last.time_text = datetime.now().strftime("%H:%M:%S")
        with self._gpu_lock:
            gpu = dict(self._gpu_snapshot)
        for key, value in gpu.items():
            setattr(self.last, key, value)
        self.last.fps = fps
        if fps_status is not None:
            self.last.fps_status = fps_status
        return SystemMetrics(**asdict(self.last))

    def stop(self) -> None:
        self._gpu_stop.set()


class PresentMonFPS:
    """FPS based on PresentMon frame-present data; does not fabricate an FPS estimate."""
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.csv_path: Path | None = None
        self.process_name = ""
        self.status = "FPS capture stopped"
        self.last_fps: float | None = None
        self._started = 0.0

    def binary(self) -> Path | None:
        candidates = [
            resource_path("vendor/PresentMon.exe"),
            Path(sys.executable).resolve().parent / "PresentMon.exe",
            Path(sys.executable).resolve().parent / "vendor" / "PresentMon.exe",
            Path.cwd() / "PresentMon.exe",
        ]
        for path in candidates:
            if path.is_file():
                return path
        return None

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    self.process.kill()
                except OSError:
                    pass
        self.process = None
        self.last_fps = None
        self.status = "FPS capture stopped"

    def start(self, process_name: str) -> tuple[bool, str]:
        self.stop()
        target = process_name.strip()
        if not target:
            self.status = "Choose a running game process first"
            return False, self.status
        binary = self.binary()
        if not binary:
            self.status = "PresentMon helper not bundled; FPS unavailable"
            return False, self.status
        # A target process must be alive before capture starts; this prevents empty captures.
        alive = False
        try:
            for p in psutil.process_iter(["name"]):
                if (p.info.get("name") or "").casefold() == target.casefold():
                    alive = True
                    break
        except (psutil.Error, OSError):
            pass
        if not alive:
            self.status = f"Waiting: {target} is not running"
            return False, self.status
        self.csv_path = app_data_dir() / "fps_capture.csv"
        try:
            self.csv_path.unlink(missing_ok=True)
        except OSError:
            pass
        cmd = [str(binary), "-process_name", target, "-output_file", str(self.csv_path), "-no_console_stats"]
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            self.process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL, creationflags=flags)
        except OSError as exc:
            self.status = f"PresentMon failed to start: {exc}"
            self.process = None
            return False, self.status
        self.process_name = target
        self._started = time.monotonic()
        self.status = f"Capturing frames from {target}"
        return True, self.status

    def read_fps(self) -> tuple[float | None, str]:
        if self.process is not None and self.process.poll() is not None:
            code = self.process.returncode
            self.process = None
            self.last_fps = None
            self.status = f"PresentMon stopped (exit {code}); try running SARBA GUI as administrator"
            return None, self.status
        if not self.csv_path or not self.csv_path.exists():
            return None, self.status
        frame_ms: list[float] = []
        try:
            with self.csv_path.open("rb") as handle:
                header = handle.readline().decode("utf-8-sig", errors="replace")
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                chunk_size = 256 * 1024
                if size > chunk_size:
                    handle.seek(-chunk_size, os.SEEK_END)
                    handle.readline()  # discard a possibly partial first CSV row
                    tail = handle.read().decode("utf-8", errors="replace")
                    csv_text = header + tail
                else:
                    handle.seek(0)
                    csv_text = handle.read().decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(csv_text))
            for row in reader:
                raw = (row.get("MsBetweenDisplayChange") or "").strip()
                if not raw or raw.lower() in {"n/a", "nan"}:
                    raw = (row.get("MsBetweenPresents") or "").strip()
                try:
                    value = float(raw)
                    if value > 0.05 and value < 1000:
                        frame_ms.append(value)
                except ValueError:
                    continue
        except (OSError, csv.Error, UnicodeError):
            return self.last_fps, self.status
        if frame_ms:
            recent = frame_ms[-60:]
            avg_ms = mean(recent)
            if avg_ms > 0:
                self.last_fps = round(1000.0 / avg_ms, 1)
                self.status = f"Live PresentMon capture: {self.process_name}"
        elif time.monotonic() - self._started > 10 and self.process is not None:
            self.status = "Capturing, waiting for frame events from target process"
        return self.last_fps, self.status


class _NvLevel(ctypes.Structure):
    _fields_ = [("level", ctypes.c_int32), ("policy", ctypes.c_int32)]


class _NvLevels(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("levels", _NvLevel * 20)]


class NvidiaFanControl:
    """Best-effort NVIDIA NVAPI fan controller; supports only drivers/cards that accept cooler control."""
    NVAPI_INITIALIZE = 0x0150E828
    NVAPI_ENUM_PHYSICAL_GPUS = 0xE5AC921F
    NVAPI_GPU_SET_COOLER_LEVELS = 0x891FA0AE
    NVAPI_GPU_RESTORE_COOLER_SETTINGS = 0x8F6ED0FB
    NVAPI_COOLER_TARGET_ALL = 0xFFFFFFFF
    COOLER_COUNT = 20
    POLICY_MANUAL = 1

    def __init__(self) -> None:
        self.lib = None
        self.gpu_handles: list[int] = []
        self.status = "Fan control not initialized"
        self._manual_active = False
        self._init()

    def _query(self, function_id: int, restype: Any, argtypes: list[Any]):
        if not self.lib:
            return None
        try:
            query = self.lib.NvAPI_QueryInterface
            query.restype = ctypes.c_void_p
            query.argtypes = [ctypes.c_uint32]
            address = query(ctypes.c_uint32(function_id))
            if not address:
                return None
            return ctypes.CFUNCTYPE(restype, *argtypes)(address)
        except (AttributeError, OSError, TypeError):
            return None

    def _init(self) -> None:
        if os.name != "nt":
            self.status = "NVIDIA fan control is available only on Windows"
            return
        try:
            self.lib = ctypes.WinDLL("nvapi64.dll")
        except OSError:
            self.status = "NVIDIA NVAPI driver library not found"
            return
        init = self._query(self.NVAPI_INITIALIZE, ctypes.c_int, [])
        if not init or init() != 0:
            self.status = "NVIDIA NVAPI initialization failed"
            return
        enum = self._query(self.NVAPI_ENUM_PHYSICAL_GPUS, ctypes.c_int,
                           [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32)])
        if not enum:
            self.status = "This NVIDIA driver does not expose GPU enumeration"
            return
        handles = (ctypes.c_void_p * 64)()
        count = ctypes.c_uint32(0)
        if enum(handles, ctypes.byref(count)) != 0 or count.value == 0:
            self.status = "No NVIDIA physical GPU found through NVAPI"
            return
        self.gpu_handles = [int(handles[i]) for i in range(min(count.value, 64)) if handles[i]]
        self.status = "NVAPI ready; support will be checked when fan control is requested"

    def set_percent(self, percent: int) -> tuple[bool, str]:
        if not self.gpu_handles:
            return False, self.status
        fn = self._query(self.NVAPI_GPU_SET_COOLER_LEVELS, ctypes.c_int,
                         [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_NvLevels)])
        if not fn:
            return False, "This driver does not expose manual cooler control. Fan setting unchanged."
        levels = _NvLevels()
        levels.version = ctypes.sizeof(_NvLevels) | (1 << 16)
        for i in range(self.COOLER_COUNT):
            levels.levels[i].level = int(percent)
            levels.levels[i].policy = self.POLICY_MANUAL
        try:
            status = int(fn(ctypes.c_void_p(self.gpu_handles[0]), self.NVAPI_COOLER_TARGET_ALL, ctypes.byref(levels)))
        except Exception as exc:
            return False, f"NVAPI fan request failed safely: {exc}"
        if status == 0:
            self._manual_active = True
            return True, f"Requested {percent}% fan speed. Verify the reported fan RPM; some cards reject manual control."
        return False, f"NVIDIA driver rejected fan control (NVAPI status {status}). No change confirmed."

    def restore_auto(self) -> tuple[bool, str]:
        if not self._manual_active:
            return True, "No manual fan mode was enabled by SARBA GUI; current automatic/vendor settings were left unchanged."
        if not self.gpu_handles:
            return False, self.status
        fn = self._query(self.NVAPI_GPU_RESTORE_COOLER_SETTINGS, ctypes.c_int,
                         [ctypes.c_void_p, ctypes.c_uint32])
        if not fn:
            return False, "Restore-auto is not exposed by this driver; use the NVIDIA/vendor automatic curve."
        try:
            status = int(fn(ctypes.c_void_p(self.gpu_handles[0]), self.NVAPI_COOLER_TARGET_ALL))
        except Exception as exc:
            return False, f"Could not restore automatic fan control: {exc}"
        if status == 0:
            self._manual_active = False
            return True, "Automatic fan control restored."
        return False, f"NVIDIA driver rejected restore-auto request (NVAPI status {status})."


@dataclass
class CleanupResult:
    files_removed: int = 0
    folders_removed: int = 0
    bytes_freed: int = 0
    skipped: int = 0
    root: str = ""


def clean_user_temp(max_age_hours: float = 0) -> CleanupResult:
    """Delete files in the current user's temp directory only; skips locked/reparse/in-use items."""
    temp = Path(os.environ.get("TEMP", os.environ.get("TMP", str(Path.home() / "AppData" / "Local" / "Temp"))))
    result = CleanupResult(root=str(temp))
    if not temp.exists() or not temp.is_dir():
        return result
    root_resolved = temp.resolve()
    cutoff = time.time() - max(0.0, max_age_hours) * 3600
    for current, dirs, files in os.walk(temp, topdown=False, followlinks=False):
        cur = Path(current)
        try:
            if cur.is_symlink() or root_resolved not in (cur.resolve(), *cur.resolve().parents):
                result.skipped += len(files) + len(dirs)
                continue
        except OSError:
            result.skipped += 1
            continue
        for filename in files:
            path = cur / filename
            try:
                if path.is_symlink() or path.stat().st_mtime > cutoff:
                    if path.is_symlink():
                        result.skipped += 1
                    continue
                size = path.stat().st_size
                path.unlink()
                result.files_removed += 1
                result.bytes_freed += size
            except (OSError, PermissionError):
                result.skipped += 1
        for dirname in dirs:
            path = cur / dirname
            try:
                if path.is_symlink():
                    result.skipped += 1
                    continue
                # Do not remove any directory unless it is empty after old-file removal.
                path.rmdir()
                result.folders_removed += 1
            except OSError:
                pass
    return result


def detect_games() -> list[dict[str, str]]:
    candidates = [
        ("MSI App Player", r"C:\Program Files\MSI App Player\HD-Player.exe", "EMULATOR"),
        ("MSI App Player", r"C:\Program Files\BlueStacks_msi2\HD-Player.exe", "EMULATOR"),
        ("MSI App Player", r"C:\Program Files\BlueStacks_msi5\HD-Player.exe", "EMULATOR"),
        ("MSI App Player", r"C:\Program Files\BlueStacks_nxt\HD-Player.exe", "EMULATOR"),
        ("MSI App Player", r"C:\Program Files\BlueStacks\HD-Player.exe", "EMULATOR"),
        ("MSI App Player", r"C:\Program Files (x86)\BlueStacks\HD-Player.exe", "EMULATOR"),
        ("Steam", r"C:\Program Files (x86)\Steam\steam.exe", "PC GAMES"),
        ("Steam", r"C:\Program Files\Steam\steam.exe", "PC GAMES"),
        ("Epic Games Launcher", r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe", "PC GAMES"),
        ("Minecraft Launcher", str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Minecraft Launcher" / "MinecraftLauncher.exe"), "PC GAMES"),
    ]
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name, path, category in candidates:
        if Path(path).is_file() and (name, path.casefold()) not in seen:
            found.append({"name": name, "path": path, "category": category})
            seen.add((name, path.casefold()))
    return found


def launch_path(path: str) -> tuple[bool, str]:
    candidate = Path(path).expanduser()
    if not candidate.exists():
        return False, f"File or shortcut not found: {candidate}"
    try:
        if os.name == "nt":
            os.startfile(str(candidate))  # type: ignore[attr-defined]
        else:
            subprocess.Popen([str(candidate)])
        return True, f"Launched {candidate.name}"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not launch {candidate.name}: {exc}"


def set_high_performance_power_plan() -> tuple[bool, str]:
    if os.name != "nt":
        return False, "Windows power plans are available only on Windows."
    # powercfg normally prints nothing on success; return code is the reliable signal.
    try:
        cp = subprocess.run(["powercfg", "/setactive", "SCHEME_MIN"], capture_output=True,
                        text=True, timeout=4, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if cp.returncode == 0:
            return True, "High Performance power plan selected. You can switch back to Balanced at any time."
        return False, (cp.stderr or cp.stdout or "Windows rejected the power-plan change.").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def open_uri(uri: str) -> bool:
    try:
        if os.name == "nt":
            os.startfile(uri)  # type: ignore[attr-defined]
        else:
            import webbrowser
            webbrowser.open(uri)
        return True
    except OSError:
        return False


def system_report(metrics: SystemMetrics, fps_status: str, fan_status: str) -> str:
    report = [
        f"{APP_NAME} {APP_VERSION}",
        f"Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"OS: {platform.platform()}",
        f"Machine: {platform.machine()}",
        f"CPU: {platform.processor() or 'Unknown'} ({psutil.cpu_count(logical=True) or '?'} threads)",
        f"CPU usage: {metrics.cpu_percent if metrics.cpu_percent is not None else 'N/A'}%",
        f"RAM: {metrics.ram_used_gb:.2f}/{metrics.ram_total_gb:.2f} GB ({metrics.ram_percent:.1f}%)" if metrics.ram_used_gb is not None and metrics.ram_total_gb is not None and metrics.ram_percent is not None else "RAM: N/A",
        f"GPU: {metrics.gpu_name}",
        f"GPU usage: {metrics.gpu_percent if metrics.gpu_percent is not None else 'N/A'}%",
        f"GPU temperature: {metrics.gpu_temp_c if metrics.gpu_temp_c is not None else 'N/A'} C",
        f"GPU memory: {metrics.gpu_mem_used_mb if metrics.gpu_mem_used_mb is not None else 'N/A'}/{metrics.gpu_mem_total_mb if metrics.gpu_mem_total_mb is not None else 'N/A'} MB",
        f"GPU fan: {metrics.gpu_fan_percent if metrics.gpu_fan_percent is not None else 'N/A'}% (read-only telemetry may be unavailable)",
        f"NVIDIA driver: {metrics.gpu_driver}",
        f"FPS: {metrics.fps if metrics.fps is not None else 'N/A'}",
        f"FPS provider: {fps_status}",
        f"Fan control: {fan_status}",
        "Frame generation: Removed by design in SARBA GUI.",
        f"App log: {app_data_dir() / 'logs' / 'SARBA-GUI.log'}",
        "Note: This report describes measured telemetry; unavailable values are not guessed.",
    ]
    log_path = app_data_dir() / "logs" / "SARBA-GUI.log"
    if log_path.exists():
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
            report.extend(["", "Recent SARBA log (last 60 lines):", *tail])
        except OSError:
            pass
    return "\n".join(report)
