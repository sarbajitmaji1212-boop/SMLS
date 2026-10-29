from __future__ import annotations

import atexit
import logging
import os
import sys
import zlib
from pathlib import Path
from typing import Any

import psutil
from PySide6.QtCore import Qt, QTimer, QPoint, QSize, QThread, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QBrush, QLinearGradient, QPolygon, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton, QToolButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget, QScrollArea, QSizePolicy,
    QMessageBox, QFileDialog, QComboBox, QCheckBox, QSlider, QProgressBar, QTextEdit,
    QLineEdit, QSpacerItem, QSystemTrayIcon, QMenu
)

from services import (
    APP_NAME, APP_VERSION, Telemetry, PresentMonFPS, NvidiaFanControl, clean_user_temp, resource_path, configure_logging,
    detect_games, load_settings, save_settings, app_data_dir, launch_path,
    set_high_performance_power_plan, open_uri, system_report, SystemMetrics
)

ACCENT = "#ff343f"
ACCENT_2 = "#ff5a44"
BG = "#080a10"
PANEL = "rgba(18, 21, 31, 232)"
TEXT = "#f4f5fa"
MUTED = "#969eaf"
BORDER = "rgba(255, 75, 84, 82)"


def format_gb(value: float | None) -> str:
    return f"{value:.1f} GB" if value is not None else "—"


def format_percent(value: float | None) -> str:
    return f"{value:.0f}%" if value is not None else "—"


class Background(QWidget):
    """Paint a low-cost atmospheric red/black background with geometric light trails."""
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.phase = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(240)

    def _tick(self) -> None:
        self.phase = (self.phase + 1) % 500
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        grad = QLinearGradient(0, 0, rect.width(), rect.height())
        grad.setColorAt(0.0, QColor("#070910"))
        grad.setColorAt(0.48, QColor("#11131d"))
        grad.setColorAt(1.0, QColor("#08070c"))
        p.fillRect(rect, QBrush(grad))
        # Atmospheric red light bloom kept intentionally subtle for low GPU overhead.
        glow_x = int(rect.width() * (0.72 + 0.04 * __import__("math").sin(self.phase / 65)))
        glow = QLinearGradient(glow_x - 240, 0, glow_x + 240, rect.height())
        glow.setColorAt(0.0, QColor(255, 35, 55, 0))
        glow.setColorAt(0.5, QColor(255, 25, 40, 24))
        glow.setColorAt(1.0, QColor(255, 35, 55, 0))
        p.fillRect(rect, QBrush(glow))
        pen = QPen(QColor(255, 64, 74, 18), 1)
        p.setPen(pen)
        offset = self.phase % 90
        for x in range(-rect.height(), rect.width(), 90):
            p.drawLine(x + offset, 0, x - rect.height() + offset, rect.height())
        p.end()


class HeroArtwork(QWidget):
    """Original SG geometric artwork; inspired by game-launcher layouts without copying game characters."""
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(220, 170)
        self.setMaximumWidth(300)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(3, 4, -3, -4)
        bg = QLinearGradient(r.topLeft(), r.bottomRight())
        bg.setColorAt(0, QColor(36, 22, 35, 215))
        bg.setColorAt(1, QColor(10, 14, 24, 210))
        p.setPen(QPen(QColor(255, 72, 86, 100), 1))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(r, 16, 16)
        p.setPen(QPen(QColor(255, 70, 85, 40), 1))
        for radius in (35, 55, 75):
            p.drawEllipse(r.center(), radius, radius)
        w, h = r.width(), r.height()
        p.setPen(Qt.PenStyle.NoPen)
        poly1 = QPolygon([QPoint(int(w*.18), int(h*.18)), QPoint(int(w*.74), int(h*.08)), QPoint(int(w*.92), int(h*.33)), QPoint(int(w*.38), int(h*.44))])
        p.setBrush(QColor(255, 48, 64, 65))
        p.drawPolygon(poly1)
        poly2 = QPolygon([QPoint(int(w*.48), int(h*.2)), QPoint(int(w*.92), int(h*.36)), QPoint(int(w*.77), int(h*.88)), QPoint(int(w*.55), int(h*.68))])
        p.setBrush(QColor(255, 50, 66, 95))
        p.drawPolygon(poly2)
        p.setPen(QPen(QColor(255, 66, 79, 170), 2))
        p.drawLine(int(w*.08), int(h*.73), int(w*.48), int(h*.57))
        p.drawLine(int(w*.52), int(h*.17), int(w*.91), int(h*.1))
        p.setPen(QColor(255, 255, 255, 245))
        p.setFont(QFont("Bahnschrift", 46, QFont.Weight.Bold))
        p.drawText(r.adjusted(0, -4, 0, -8), Qt.AlignmentFlag.AlignCenter, "SG")
        p.setPen(QColor(255, 110, 121, 230))
        p.setFont(QFont("Bahnschrift", 8, QFont.Weight.Bold))
        p.drawText(r.adjusted(0, 0, -12, -12), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, "SARBA / READY")
        p.end()


class GameCover(QWidget):
    """Small generated geometric cover art keeps the launcher card-based without copying game art."""
    def __init__(self, name: str, category: str, compact: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.category = category
        self.compact = compact
        self.setMinimumHeight(34 if compact else 66)
        self.setMaximumHeight(38 if compact else 72)
        self._palette = ["#ff3748", "#bc2945", "#843047", "#d14b32"]
        self._accent = QColor(self._palette[zlib.crc32(name.encode("utf-8")) % len(self._palette)])

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        base = QLinearGradient(r.topLeft(), r.bottomRight())
        base.setColorAt(0, QColor("#171a26"))
        base.setColorAt(1, self._accent.darker(190))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(base))
        p.drawRoundedRect(r, 8, 8)
        w, h = r.width(), r.height()
        p.setBrush(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 90))
        p.drawPolygon(QPolygon([QPoint(int(w*.30), 0), QPoint(int(w*.75), 0), QPoint(int(w*.48), h), QPoint(int(w*.10), h)]))
        p.setPen(QPen(QColor(255, 255, 255, 35), 1))
        step = max(14, int(w / 12))
        for x in range(0, w, step):
            p.drawLine(x, 0, x + int(h*.8), h)
        p.setPen(QPen(self._accent.lighter(135), 2))
        p.drawLine(0, h - 3, int(w*.45), h - 3)
        if not self.compact:
            p.setPen(QColor(255, 255, 255, 230))
            p.setFont(QFont("Bahnschrift", 8, QFont.Weight.Bold))
            p.drawText(r.adjusted(10, 0, -8, -3), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, self.category.upper()[:24])
        p.end()


class GlassCard(QFrame):
    def __init__(self, parent: QWidget | None = None, object_name: str = "glassCard") -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setProperty("glass", True)
        self.setFrameShape(QFrame.Shape.NoFrame)


class StatCard(GlassCard):
    def __init__(self, title: str, symbol: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, "statCard")
        self.setMinimumHeight(120)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        top = QHBoxLayout()
        icon = QLabel(symbol)
        icon.setObjectName("statSymbol")
        top.addWidget(icon)
        name = QLabel(title.upper())
        name.setObjectName("microLabel")
        top.addWidget(name)
        top.addStretch(1)
        self.status = QLabel("LIVE")
        self.status.setObjectName("liveTag")
        top.addWidget(self.status)
        layout.addLayout(top)
        self.value = QLabel("—")
        self.value.setObjectName("statValue")
        layout.addWidget(self.value)
        self.detail = QLabel("Waiting for telemetry")
        self.detail.setObjectName("muted")
        layout.addWidget(self.detail)

    def set_data(self, value: str, detail: str) -> None:
        self.value.setText(value)
        self.detail.setText(detail)


class OverlayWindow(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("SARBA GUI Performance Overlay")
        self.resize(590, 82)
        self._drag_offset: QPoint | None = None
        self.setStyleSheet("""
            QWidget { color: #f7f7fb; font-family: 'Bahnschrift','Segoe UI'; }
            QFrame#overlayPanel { background-color: rgba(8, 10, 16, 220); border: 1px solid rgba(255, 55, 67, 190); border-radius: 13px; }
            QLabel#ovLabel { color: #9ea8b8; font-size: 9px; font-weight: 700; }
            QLabel#ovValue { color: #ffffff; font-size: 17px; font-weight: 800; }
            QLabel#ovFPS { color: #ff424b; font-size: 20px; font-weight: 900; }
        """)
        self.panel = QFrame(self)
        self.panel.setObjectName("overlayPanel")
        row = QHBoxLayout(self.panel)
        row.setContentsMargins(14, 9, 14, 8)
        row.setSpacing(15)
        self.values: dict[str, QLabel] = {}
        for key in ("FPS", "GPU", "CPU", "RAM", "TEMP", "VRAM"):
            col = QVBoxLayout()
            lab = QLabel(key)
            lab.setObjectName("ovLabel")
            val = QLabel("—")
            val.setObjectName("ovFPS" if key == "FPS" else "ovValue")
            col.addWidget(lab)
            col.addWidget(val)
            row.addLayout(col)
            self.values[key] = val
        self.close_button = QToolButton()
        self.close_button.setText("×")
        self.close_button.setToolTip("Hide overlay")
        self.close_button.setStyleSheet("QToolButton { color:#ff5962; font-size:20px; border:0; padding:2px; }")
        self.close_button.clicked.connect(self.hide)
        row.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.panel)
        self.move(20, 60)

    def update_metrics(self, m: SystemMetrics) -> None:
        self.values["FPS"].setText(f"{m.fps:.0f}" if m.fps is not None else "N/A")
        self.values["GPU"].setText(format_percent(m.gpu_percent))
        self.values["CPU"].setText(format_percent(m.cpu_percent))
        self.values["RAM"].setText(format_percent(m.ram_percent))
        self.values["TEMP"].setText(f"{m.gpu_temp_c:.0f}°C" if m.gpu_temp_c is not None else "—")
        if m.gpu_mem_used_mb is not None and m.gpu_mem_total_mb and m.gpu_mem_total_mb > 0:
            self.values["VRAM"].setText(f"{m.gpu_mem_used_mb / m.gpu_mem_total_mb * 100:.0f}%")
        else:
            self.values["VRAM"].setText("—")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        event.accept()


class DragBar(QWidget):
    """Small custom title strip so the frameless window can be dragged."""
    def __init__(self, owner: QMainWindow) -> None:
        super().__init__(owner.centralWidget() if owner.centralWidget() else owner)
        self.owner = owner
        self._offset: QPoint | None = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._offset = event.globalPosition().toPoint() - self.owner.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.owner.move(event.globalPosition().toPoint() - self._offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._offset = None
        event.accept()


class TempCleanupWorker(QThread):
    completed = Signal(object)

    def __init__(self, max_age_hours: float) -> None:
        super().__init__()
        self.max_age_hours = max_age_hours

    def run(self) -> None:
        try:
            result = clean_user_temp(max_age_hours=self.max_age_hours)
            self.completed.emit(result)
        except Exception:
            logging.exception("Temporary-file cleanup failed")
            self.completed.emit(None)


class SARBAGUI(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} • Gaming Command Center")
        self.setMinimumSize(1080, 700)
        self.resize(1380, 860)
        self.setWindowIcon(QIcon(str(resource_path("assets/SG.ico"))))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.settings = load_settings()
        self.telemetry = Telemetry()
        self.fps = PresentMonFPS()
        self.fan = NvidiaFanControl()
        self.metrics = self.telemetry.sample()
        self.overlay = OverlayWindow()
        self.game_items: list[dict[str, str]] = []
        self.nav_buttons: dict[str, QPushButton] = {}
        self._drag_offset: QPoint | None = None
        self._refreshing = False
        self._cleanup_worker: TempCleanupWorker | None = None
        self._setup_ui()
        self._load_games()
        self._metrics_timer = QTimer(self)
        self._metrics_timer.timeout.connect(self.refresh_metrics)
        self._metrics_timer.start(1000)
        self._process_timer = QTimer(self)
        self._process_timer.timeout.connect(self.refresh_process_list)
        self._process_timer.start(4000)
        self.refresh_metrics()
        if self.settings.get("auto_clean_temp"):
            self._start_temp_cleanup(max_age_hours=24, startup=True)
        if self.settings.get("show_overlay_on_start"):
            self.overlay.show()
        atexit.register(self._safe_restore_fan)

    def _setup_ui(self) -> None:
        self.bg = Background(self)
        self.setCentralWidget(self.bg)
        outer = QVBoxLayout(self.bg)
        outer.setContentsMargins(14, 10, 14, 12)
        outer.setSpacing(10)
        outer.addWidget(self._build_titlebar())
        body = QHBoxLayout()
        body.setSpacing(12)
        self.sidebar = self._build_sidebar()
        body.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        self.pages: dict[str, QWidget] = {}
        for name, builder in [
            ("Dashboard", self._page_dashboard),
            ("Game Library", self._page_library),
            ("Performance", self._page_performance),
            ("Optimization", self._page_optimization),
            ("Utilities", self._page_utilities),
            ("Settings", self._page_settings),
        ]:
            page = builder()
            self.pages[name] = page
            self.stack.addWidget(page)
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)
        self.toast = QLabel("")
        self.toast.setObjectName("toast")
        self.toast.setMinimumHeight(19)
        outer.addWidget(self.toast)
        self._apply_styles()
        self.navigate("Dashboard")

    def _build_titlebar(self) -> QWidget:
        bar = DragBar(self)
        bar.setObjectName("titlebar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(5, 1, 4, 1)
        row.setSpacing(11)
        logo = QLabel("SG")
        logo.setObjectName("logoBadge")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(42, 42)
        row.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        title = QLabel("SARBA GUI")
        title.setObjectName("brandName")
        sub = QLabel("GAMING COMMAND CENTER  /  BUILD 1.0")
        sub.setObjectName("brandSub")
        names.addWidget(title)
        names.addWidget(sub)
        row.addLayout(names)
        row.addStretch(1)
        self.system_pill = QLabel("●  SYSTEM ONLINE")
        self.system_pill.setObjectName("systemPill")
        row.addWidget(self.system_pill)
        self.min_btn = QToolButton()
        self.min_btn.setText("—")
        self.min_btn.setObjectName("windowControl")
        self.min_btn.clicked.connect(self.showMinimized)
        row.addWidget(self.min_btn)
        self.close_btn = QToolButton()
        self.close_btn.setText("×")
        self.close_btn.setObjectName("closeControl")
        self.close_btn.clicked.connect(self.close)
        row.addWidget(self.close_btn)
        return bar

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(183)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 18, 10, 12)
        layout.setSpacing(6)
        category = QLabel("MAIN MENU")
        category.setObjectName("sideSection")
        layout.addWidget(category)
        entries = [
            ("Dashboard", "⌂"), ("Game Library", "▣"), ("Performance", "◈"),
            ("Optimization", "⚡"), ("Utilities", "⌘"), ("Settings", "⚙"),
        ]
        for name, glyph in entries:
            btn = QPushButton(f"{glyph}   {name}")
            btn.setObjectName("navButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False, n=name: self.navigate(n))
            layout.addWidget(btn)
            self.nav_buttons[name] = btn
        layout.addStretch(1)
        info = GlassCard(object_name="sidebarInfo")
        il = QVBoxLayout(info)
        il.setContentsMargins(12, 13, 12, 13)
        lbl = QLabel("SG / STATUS")
        lbl.setObjectName("microLabel")
        il.addWidget(lbl)
        txt = QLabel("Frame generation\nremoved by design.\n\nNative telemetry\nwith honest status.")
        txt.setObjectName("mutedSmall")
        txt.setWordWrap(True)
        il.addWidget(txt)
        layout.addWidget(info)
        build = QLabel("SARBA LABS  •  TEST BUILD")
        build.setObjectName("sideFoot")
        build.setWordWrap(True)
        layout.addWidget(build)
        return sidebar

    def _scroll_page(self, contents: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(contents)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; } QScrollArea > QWidget > QWidget { background: transparent; }")
        return scroll

    def _page_dashboard(self) -> QWidget:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(8, 6, 8, 6)
        l.setSpacing(15)
        hero = GlassCard(object_name="heroCard")
        hero.setMinimumHeight(240)
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(25, 19, 25, 20)
        tags = QHBoxLayout()
        pill = QLabel("SG  /  READY ROOM")
        pill.setObjectName("redPill")
        tags.addWidget(pill)
        tags.addStretch(1)
        tags_info = QLabel("WINDOWS 10/11  •  PERFORMANCE  •  GAME LAUNCHER")
        tags_info.setObjectName("sectionSub")
        tags.addWidget(tags_info)
        hl.addLayout(tags)
        hero_body = QHBoxLayout()
        hero_body.setSpacing(20)
        left = QVBoxLayout()
        left.setSpacing(9)
        h = QLabel("YOUR GAMES.\nYOUR RULES.")
        h.setObjectName("heroTitle")
        h.setWordWrap(True)
        left.addWidget(h)
        desc = QLabel("Launch faster. Track real system telemetry. Keep your setup clean.")
        desc.setObjectName("heroDesc")
        desc.setWordWrap(True)
        left.addWidget(desc)
        buttons = QHBoxLayout()
        launch = QPushButton("▶   LAUNCH MSI APP PLAYER")
        launch.setObjectName("primaryButton")
        launch.clicked.connect(self.launch_msi)
        buttons.addWidget(launch)
        lib = QPushButton("OPEN GAME LIBRARY   ↗")
        lib.setObjectName("secondaryButton")
        lib.clicked.connect(lambda: self.navigate("Game Library"))
        buttons.addWidget(lib)
        buttons.addStretch(1)
        left.addLayout(buttons)
        left.addStretch(1)
        hero_body.addLayout(left, 1)
        hero_body.addWidget(HeroArtwork())
        hl.addLayout(hero_body, 1)
        l.addWidget(hero)

        section = self._section_header("SYSTEM OVERVIEW", "LIVE TELEMETRY  /  REFRESHES EVERY SECOND")
        l.addWidget(section)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.stat_cpu = StatCard("Processor", "CPU")
        self.stat_gpu = StatCard("Graphics", "GPU")
        self.stat_ram = StatCard("Memory", "RAM")
        self.stat_fps = StatCard("Game FPS", "FPS")
        for i, card in enumerate((self.stat_cpu, self.stat_gpu, self.stat_ram, self.stat_fps)):
            grid.addWidget(card, 0, i)
        l.addLayout(grid)

        quick = self._section_header("QUICK LAUNCH", "YOUR DETECTED GAMES AND EMULATORS")
        l.addWidget(quick)
        self.quick_grid = QGridLayout()
        self.quick_grid.setSpacing(10)
        l.addLayout(self.quick_grid)

        util_header = self._section_header("UTILITY CORE", "COMMON TOOLS, ONE CLICK AWAY")
        l.addWidget(util_header)
        utils = QGridLayout()
        utils.setSpacing(10)
        shortcuts = [
            ("SYSTEM CHECK", "Run hardware and telemetry checks", self.run_system_check),
            ("CLEAN TEMP", "Remove available user temp files", self.clean_temp_now),
            ("GAME MODE", "Open Windows Game Mode settings", lambda: self.open_tool("Game Mode", "ms-settings:gaming-gamemode")),
        ]
        for i, (title, sub, call) in enumerate(shortcuts):
            utils.addWidget(self._utility_tile(title, sub, call), 0, i)
        l.addLayout(utils)
        l.addStretch(1)
        return self._scroll_page(page)

    def _page_library(self) -> QWidget:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(8, 6, 8, 6)
        header = QHBoxLayout()
        header.addWidget(self._section_header("GAME LIBRARY", "AUTO-DETECTED + CUSTOM LAUNCH TARGETS"), 1)
        add = QPushButton("＋  ADD GAME")
        add.setObjectName("primaryButton")
        add.clicked.connect(self.add_game)
        header.addWidget(add)
        l.addLayout(header)
        self.library_grid = QGridLayout()
        self.library_grid.setSpacing(12)
        library_container = QWidget()
        library_container.setLayout(self.library_grid)
        l.addWidget(self._scroll_page(library_container), 1)
        note = QLabel("Games launch through their installed executable or shortcut. SARBA GUI does not inject into games.")
        note.setObjectName("mutedSmall")
        l.addWidget(note)
        return page

    def _page_performance(self) -> QWidget:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(8, 6, 8, 6)
        l.addWidget(self._section_header("PERFORMANCE MONITOR", "NATIVE FPS CAPTURE • REAL GPU / CPU / RAM READINGS"))
        grid = QGridLayout()
        grid.setSpacing(10)
        self.perf_cpu = StatCard("CPU Load", "CPU")
        self.perf_gpu = StatCard("GPU Load", "GPU")
        self.perf_ram = StatCard("System Memory", "RAM")
        self.perf_fps = StatCard("Presented FPS", "FPS")
        for i, card in enumerate((self.perf_cpu, self.perf_gpu, self.perf_ram, self.perf_fps)):
            grid.addWidget(card, 0, i)
        l.addLayout(grid)

        target_card = GlassCard()
        tl = QVBoxLayout(target_card)
        tl.setContentsMargins(20, 18, 20, 18)
        tl.addWidget(self._inner_heading("FRAME RATE TRACKING", "FPS comes from PresentMon frame-present events, not an invented estimate."))
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target process"))
        self.target_combo = QComboBox()
        self.target_combo.setEditable(True)
        self.target_combo.setMinimumWidth(280)
        self.target_combo.addItems(["HD-Player.exe", "FreeFire.exe", "FreeFireIndia.exe", "game.exe"])
        saved_target = str(self.settings.get("fps_process_name", "HD-Player.exe"))
        self.target_combo.setCurrentText(saved_target)
        target_row.addWidget(self.target_combo)
        self.start_fps_btn = QPushButton("▶  START FPS CAPTURE")
        self.start_fps_btn.setObjectName("primaryButton")
        self.start_fps_btn.clicked.connect(self.start_fps_capture)
        target_row.addWidget(self.start_fps_btn)
        target_row.addStretch(1)
        tl.addLayout(target_row)
        self.fps_status_label = QLabel(self.fps.status)
        self.fps_status_label.setObjectName("statusLine")
        self.fps_status_label.setWordWrap(True)
        tl.addWidget(self.fps_status_label)
        overlay_row = QHBoxLayout()
        self.overlay_check = QCheckBox("Show always-on-top performance overlay")
        self.overlay_check.setChecked(bool(self.settings.get("show_overlay_on_start")))
        self.overlay_check.toggled.connect(self.toggle_overlay)
        overlay_row.addWidget(self.overlay_check)
        overlay_row.addStretch(1)
        overlay_row.addWidget(QLabel("Drag overlay to move • × to hide"))
        tl.addLayout(overlay_row)
        l.addWidget(target_card)

        fan_card = GlassCard()
        fl = QVBoxLayout(fan_card)
        fl.setContentsMargins(20, 18, 20, 18)
        fl.addWidget(self._inner_heading("GPU FAN CONTROL", "NVAPI cooler control • only applies if the driver and card accept it."))
        fan_row = QHBoxLayout()
        self.fan_value_label = QLabel("50%")
        self.fan_value_label.setObjectName("fanValue")
        fan_row.addWidget(self.fan_value_label)
        self.fan_slider = QSlider(Qt.Orientation.Horizontal)
        self.fan_slider.setRange(35, 100)
        self.fan_slider.setValue(50)
        self.fan_slider.valueChanged.connect(lambda v: self.fan_value_label.setText(f"{v}%"))
        fan_row.addWidget(self.fan_slider, 1)
        apply_fan = QPushButton("APPLY FAN SPEED")
        apply_fan.setObjectName("primaryButton")
        apply_fan.clicked.connect(self.apply_fan_speed)
        fan_row.addWidget(apply_fan)
        auto_fan = QPushButton("RESTORE AUTO")
        auto_fan.setObjectName("secondaryButton")
        auto_fan.clicked.connect(self.restore_fan_auto)
        fan_row.addWidget(auto_fan)
        fl.addLayout(fan_row)
        self.fan_actual_label = QLabel("Current fan telemetry: waiting for driver data")
        self.fan_actual_label.setObjectName("statusLine")
        fl.addWidget(self.fan_actual_label)
        self.fan_status_label = QLabel(self.fan.status)
        self.fan_status_label.setObjectName("mutedSmall")
        self.fan_status_label.setWordWrap(True)
        fl.addWidget(self.fan_status_label)
        hint = QLabel("Manual speed is limited to 35–100%. Keep temperatures visible and restore automatic control before closing your gaming session.")
        hint.setObjectName("mutedSmall")
        hint.setWordWrap(True)
        fl.addWidget(hint)
        l.addWidget(fan_card)
        l.addStretch(1)
        return self._scroll_page(page)

    def _page_optimization(self) -> QWidget:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(8, 6, 8, 6)
        l.addWidget(self._section_header("OPTIMIZATION", "SAFE, REVERSIBLE WINDOWS MAINTENANCE"))
        temp_card = GlassCard()
        tl = QVBoxLayout(temp_card)
        tl.setContentsMargins(20, 18, 20, 18)
        tl.addWidget(self._inner_heading("TEMP FILE CLEANER", "Only targets the current user's TEMP folder; locked files are skipped."))
        self.auto_clean_check = QCheckBox("Automatically remove temp files older than 24 hours when SARBA GUI starts")
        self.auto_clean_check.setChecked(bool(self.settings.get("auto_clean_temp")))
        self.auto_clean_check.toggled.connect(self.save_preferences)
        tl.addWidget(self.auto_clean_check)
        row = QHBoxLayout()
        clean = QPushButton("CLEAN AVAILABLE TEMP FILES NOW")
        clean.setObjectName("primaryButton")
        clean.clicked.connect(self.clean_temp_now)
        row.addWidget(clean)
        open_temp = QPushButton("OPEN TEMP FOLDER")
        open_temp.setObjectName("secondaryButton")
        open_temp.clicked.connect(lambda: self.open_tool("Temp folder", os.environ.get("TEMP", str(Path.home()))))
        row.addWidget(open_temp)
        row.addStretch(1)
        tl.addLayout(row)
        self.cleanup_status = QLabel("No cleanup run in this session.")
        self.cleanup_status.setObjectName("statusLine")
        tl.addWidget(self.cleanup_status)
        l.addWidget(temp_card)

        power = GlassCard()
        pl = QVBoxLayout(power)
        pl.setContentsMargins(20, 18, 20, 18)
        pl.addWidget(self._inner_heading("GAME PERFORMANCE", "Use Windows features instead of killing services or changing hidden registry values."))
        pr = QHBoxLayout()
        high = QPushButton("ENABLE HIGH PERFORMANCE POWER PLAN")
        high.setObjectName("primaryButton")
        high.clicked.connect(self.set_power_plan)
        pr.addWidget(high)
        mode = QPushButton("OPEN WINDOWS GAME MODE")
        mode.setObjectName("secondaryButton")
        mode.clicked.connect(lambda: self.open_tool("Game Mode", "ms-settings:gaming-gamemode"))
        pr.addWidget(mode)
        graphics = QPushButton("GRAPHICS SETTINGS")
        graphics.setObjectName("secondaryButton")
        graphics.clicked.connect(lambda: self.open_tool("Graphics settings", "ms-settings:display-advancedgraphics"))
        pr.addWidget(graphics)
        pl.addLayout(pr)
        note = QLabel("Power plans change system power behavior and may increase heat or power use. Select Balanced in Windows Settings to undo if preferred.")
        note.setObjectName("mutedSmall")
        note.setWordWrap(True)
        pl.addWidget(note)
        l.addWidget(power)

        process = GlassCard()
        xl = QVBoxLayout(process)
        xl.setContentsMargins(20, 18, 20, 18)
        xl.addWidget(self._inner_heading("GAME SESSION", "Useful when switching into a game without disabling Windows security protections."))
        rr = QHBoxLayout()
        task = QPushButton("OPEN TASK MANAGER")
        task.setObjectName("utilityButton")
        task.clicked.connect(lambda: self.open_tool("Task Manager", "taskmgr.exe"))
        rr.addWidget(task)
        startup = QPushButton("STARTUP APPS")
        startup.setObjectName("utilityButton")
        startup.clicked.connect(lambda: self.open_tool("Startup apps", "ms-settings:startupapps"))
        rr.addWidget(startup)
        rr.addStretch(1)
        xl.addLayout(rr)
        l.addWidget(process)
        l.addStretch(1)
        return self._scroll_page(page)

    def _page_utilities(self) -> QWidget:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(8, 6, 8, 6)
        l.addWidget(self._section_header("UTILITY DECK", "WINDOWS TOOLS AND HARDWARE SHORTCUTS"))
        grid = QGridLayout()
        grid.setSpacing(12)
        tools = [
            ("TASK MANAGER", "Monitor processes and startup", "taskmgr.exe"),
            ("DEVICE MANAGER", "Drivers and device status", "devmgmt.msc"),
            ("DIRECTX DIAGNOSTICS", "Display, audio and DirectX info", "dxdiag.exe"),
            ("EVENT VIEWER", "Review application and system errors", "eventvwr.msc"),
            ("DISK CLEANUP", "Windows temporary file utility", "cleanmgr.exe"),
            ("NVIDIA CONTROL PANEL", "GPU driver display settings", "nvcplui.exe"),
            ("WINDOWS GAME MODE", "Gaming options in Windows Settings", "ms-settings:gaming-gamemode"),
            ("DISPLAY SETTINGS", "Resolution and monitor settings", "ms-settings:display"),
            ("SOUND SETTINGS", "Audio output and input", "ms-settings:sound"),
            ("NETWORK SETTINGS", "Network connection settings", "ms-settings:network"),
            ("WINDOWS UPDATE", "Review driver and system updates", "ms-settings:windowsupdate"),
            ("SYSTEM INFORMATION", "System Information utility", "msinfo32.exe"),
        ]
        for i, (title, sub, command) in enumerate(tools):
            tile = self._utility_tile(title, sub, lambda t=title, c=command: self.open_tool(t, c))
            grid.addWidget(tile, i // 3, i % 3)
        l.addLayout(grid)
        support = GlassCard()
        sl = QVBoxLayout(support)
        sl.setContentsMargins(18, 15, 18, 15)
        sl.addWidget(self._inner_heading("SUPPORT & DIAGNOSTICS", "Export a report to share a precise description of detected issues."))
        row = QHBoxLayout()
        report = QPushButton("SAVE SYSTEM REPORT")
        report.setObjectName("primaryButton")
        report.clicked.connect(self.save_report)
        row.addWidget(report)
        appdata = QPushButton("OPEN SARBA CONFIG FOLDER")
        appdata.setObjectName("secondaryButton")
        appdata.clicked.connect(lambda: self.open_tool("SARBA config folder", str(app_data_dir())))
        row.addWidget(appdata)
        row.addStretch(1)
        sl.addLayout(row)
        l.addWidget(support)
        l.addStretch(1)
        return self._scroll_page(page)

    def _page_settings(self) -> QWidget:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(8, 6, 8, 6)
        l.addWidget(self._section_header("SETTINGS", "APP BEHAVIOR AND DIAGNOSTIC STATUS"))
        card = GlassCard()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 18, 20, 18)
        cl.addWidget(self._inner_heading("PREFERENCES", "Changes are saved to your Windows user profile."))
        self.pref_overlay_check = QCheckBox("Show overlay when SARBA GUI starts")
        self.pref_overlay_check.setChecked(bool(self.settings.get("show_overlay_on_start")))
        self.pref_overlay_check.toggled.connect(self._sync_overlay_preference)
        cl.addWidget(self.pref_overlay_check)
        self.pref_clean_check = QCheckBox("Automatically clean older user temp files on app start")
        self.pref_clean_check.setChecked(bool(self.settings.get("auto_clean_temp")))
        self.pref_clean_check.toggled.connect(self._sync_clean_preference)
        cl.addWidget(self.pref_clean_check)
        self.settings_note = QLabel("No frame generation is included. The FPS meter reads PresentMon data when the game and driver permit capture.")
        self.settings_note.setObjectName("mutedSmall")
        self.settings_note.setWordWrap(True)
        cl.addWidget(self.settings_note)
        l.addWidget(card)

        about = GlassCard()
        al = QVBoxLayout(about)
        al.setContentsMargins(20, 18, 20, 18)
        al.addWidget(self._inner_heading("ABOUT SARBA GUI", f"VERSION {APP_VERSION}  /  SG RED EDITION"))
        self.about_text = QLabel(f"Application: {APP_NAME}\nBuild: {APP_VERSION}\nWindows: {os.name}\nData folder: {app_data_dir()}\nFPS helper: {'Available' if self.fps.binary() else 'Not bundled'}\nFan control: {self.fan.status}\n\nThis utility suite does not inject into games, alter game files, or promise unsupported GPU features.")
        self.about_text.setObjectName("mutedSmall")
        self.about_text.setWordWrap(True)
        al.addWidget(self.about_text)
        l.addWidget(about)
        l.addStretch(1)
        return self._scroll_page(page)

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QWidget { color: #f4f5fa; font-family: 'Bahnschrift SemiBold','Bahnschrift','Segoe UI'; font-size: 10pt; }
            QLabel#brandName { color: #ffffff; font-size: 17pt; font-weight: 900; letter-spacing: 1px; }
            QLabel#brandSub { color: #939bad; font-size: 7pt; letter-spacing: 2px; }
            QLabel#logoBadge { color: white; background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #ff6660,stop:1 #bc0b27); border: 1px solid #ff8082; border-radius: 11px; font-size: 14pt; font-weight: 1000; }
            QLabel#systemPill { color: #ff8086; background-color: rgba(255,45,60,26); border: 1px solid rgba(255,65,76,100); border-radius: 11px; padding: 7px 12px; font-size: 8pt; font-weight: 800; }
            QToolButton#windowControl, QToolButton#closeControl { color: #dce0ea; background: rgba(255,255,255,8); border: 1px solid rgba(255,255,255,24); border-radius: 9px; min-width: 34px; min-height: 32px; font-size: 14pt; }
            QToolButton#closeControl:hover { background: #b9162e; }
            QFrame#sidebar { background-color: rgba(13, 15, 23, 224); border: 1px solid rgba(255,70,82,46); border-radius: 17px; }
            QLabel#sideSection { color: #6f7b90; font-size: 8pt; font-weight: 900; letter-spacing: 1px; padding: 5px 9px 9px 9px; }
            QPushButton#navButton { text-align: left; color: #9da5b6; background: transparent; border: 1px solid transparent; border-radius: 10px; padding: 12px 10px; font-weight: 700; }
            QPushButton#navButton:hover { color: #ffffff; background: rgba(255,255,255,7); }
            QPushButton#navButton:checked { color: #ffffff; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 rgba(255,46,63,75),stop:1 rgba(255,46,63,10)); border: 1px solid rgba(255,66,78,100); }
            QLabel#sideFoot { color: #5f687b; font-size: 7pt; letter-spacing: 1px; padding: 5px; }
            QFrame[glass="true"], QFrame#statCard, QFrame#glassCard { background-color: rgba(20, 22, 32, 222); border: 1px solid rgba(255,69,83,70); border-radius: 16px; }
            QFrame#heroCard { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(35,24,36,244),stop:0.54 rgba(18,22,34,236),stop:1 rgba(65,16,28,222)); border: 1px solid rgba(255,70,81,130); border-radius: 20px; }
            QFrame#statCard { background-color: rgba(22,25,35,226); border-color: rgba(255,255,255,19); }
            QLabel#microLabel { color: #8f99ad; font-size: 8pt; font-weight: 900; letter-spacing: 1px; }
            QLabel#statSymbol { color: #ff515b; background: rgba(255,49,63,28); border: 1px solid rgba(255,72,84,65); border-radius: 7px; padding: 4px 7px; font-size: 8pt; font-weight: 900; }
            QLabel#liveTag { color: #ff737b; font-size: 7pt; font-weight: 900; }
            QLabel#statValue { color: #ffffff; font-size: 21pt; font-weight: 900; }
            QLabel#muted { color: #9aa2b3; font-size: 8pt; }
            QLabel#mutedSmall { color: #9aa2b3; font-size: 9pt; }
            QLabel#heroTitle { color: white; font-size: 31pt; font-weight: 1000; letter-spacing: 3px; }
            QLabel#heroDesc { color: #b2bac8; font-size: 11pt; }
            QLabel#redPill { color: #ff6a72; background: rgba(255,40,60,30); border: 1px solid rgba(255,68,80,100); border-radius: 8px; padding: 5px 9px; font-size: 8pt; font-weight: 900; letter-spacing: 1px; }
            QLabel#sectionTitle { color: #ffffff; font-size: 13pt; font-weight: 900; letter-spacing: 1px; }
            QLabel#sectionSub { color: #788398; font-size: 8pt; letter-spacing: 1px; }
            QLabel#toast { color: #ff8b91; font-size: 8pt; padding-left: 4px; }
            QLabel#statusLine { color: #ff9aa0; background: rgba(255,48,63,18); border: 1px solid rgba(255,70,85,46); border-radius: 9px; padding: 9px; }
            QLabel#fanValue { font-size: 18pt; font-weight: 900; color: #ff5962; min-width: 50px; }
            QPushButton#primaryButton { color: white; background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #ff5961,stop:1 #c51531); border: 1px solid #ff717a; border-radius: 9px; padding: 10px 14px; font-weight: 900; }
            QPushButton#primaryButton:hover { background: #ff424e; }
            QPushButton#primaryButton:pressed { background: #9e1125; }
            QPushButton#secondaryButton { color: #eceef5; background: rgba(255,255,255,7); border: 1px solid rgba(188,198,220,60); border-radius: 9px; padding: 10px 14px; font-weight: 800; }
            QPushButton#secondaryButton:hover, QPushButton#utilityButton:hover { background: rgba(255,54,71,22); border-color: rgba(255,74,85,120); }
            QPushButton#utilityTile { text-align:left; background-color: rgba(20,22,32,222); border:1px solid rgba(255,69,83,70); border-radius:16px; padding:0px; }
            QPushButton#utilityTile:hover { background-color: rgba(35,22,31,239); border-color: rgba(255,80,91,150); }
            QPushButton#utilityButton { color: #eff0f6; background: rgba(255,255,255,5); border: 1px solid rgba(255,255,255,26); border-radius: 10px; padding: 12px; font-weight: 800; }
            QComboBox, QLineEdit { color: white; background-color: rgba(5,7,13,190); border: 1px solid rgba(255,75,85,90); border-radius: 8px; padding: 8px 10px; selection-background-color: #a71f31; }
            QComboBox QAbstractItemView { background: #171a23; color: white; selection-background-color: #9e2435; border: 1px solid #303440; }
            QCheckBox { color: #dfe3ec; spacing: 8px; }
            QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #70798a; background: rgba(0,0,0,80); }
            QCheckBox::indicator:checked { background: #e52a3b; border-color: #ff6670; }
            QSlider::groove:horizontal { height: 6px; background: #303342; border-radius: 3px; }
            QSlider::sub-page:horizontal { background: #ff3c48; border-radius: 3px; }
            QSlider::handle:horizontal { width: 16px; margin: -6px 0; border-radius: 8px; background: #fff; border: 2px solid #ff424e; }
            QProgressBar { background: #252936; border: 1px solid #363b4a; border-radius: 5px; text-align: center; color: white; min-height: 9px; max-height: 9px; }
            QProgressBar::chunk { border-radius: 5px; background: #ff3b49; }
            QScrollBar:vertical { background: transparent; width: 8px; margin: 3px; }
            QScrollBar::handle:vertical { background: #414452; border-radius: 4px; min-height: 30px; }
            QScrollBar::handle:vertical:hover { background: #ff424f; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

    def _section_header(self, title: str, subtitle: str) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(1, 0, 1, 0)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("sectionTitle")
        s = QLabel(subtitle)
        s.setObjectName("sectionSub")
        col.addWidget(t)
        col.addWidget(s)
        row.addLayout(col)
        row.addStretch(1)
        return widget

    def _inner_heading(self, title: str, subtitle: str) -> QWidget:
        widget = QWidget()
        col = QVBoxLayout(widget)
        col.setContentsMargins(0, 0, 0, 7)
        col.setSpacing(4)
        t = QLabel(title)
        t.setStyleSheet("font-size:12pt;font-weight:900;letter-spacing:1px;color:#ffffff;")
        s = QLabel(subtitle)
        s.setObjectName("mutedSmall")
        s.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(s)
        return widget

    def _utility_tile(self, title: str, subtitle: str, callback) -> QWidget:
        tile = QPushButton()
        tile.setObjectName("utilityTile")
        tile.setCursor(Qt.CursorShape.PointingHandCursor)
        tile.setMinimumHeight(92)
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        top = QHBoxLayout()
        h = QLabel(title)
        h.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        h.setStyleSheet("color:#ff6b73;font-size:9pt;font-weight:900;letter-spacing:1px;")
        top.addWidget(h)
        top.addStretch(1)
        arrow = QLabel("↗")
        arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        arrow.setStyleSheet("color:#70798c;font-size:13pt;")
        top.addWidget(arrow)
        layout.addLayout(top)
        desc = QLabel(subtitle)
        desc.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        desc.setObjectName("mutedSmall")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        tile.clicked.connect(callback)
        return tile

    def _load_games(self) -> None:
        stored = self.settings.get("games", [])
        if not isinstance(stored, list):
            stored = []
        detected = detect_games()
        combined = []
        seen = set()
        for item in detected + [g for g in stored if isinstance(g, dict)]:
            name, path = str(item.get("name", "Custom game")), str(item.get("path", ""))
            key = path.casefold()
            if path and key not in seen:
                seen.add(key)
                combined.append({"name": name, "path": path, "category": str(item.get("category", "CUSTOM"))})
        self.game_items = combined
        self.settings["games"] = [g for g in combined if g.get("category") == "CUSTOM" or g not in detected]
        self._rebuild_games()

    def _rebuild_games(self) -> None:
        if not hasattr(self, "library_grid") or not hasattr(self, "quick_grid"):
            return
        self._clear_layout(self.library_grid)
        self._clear_layout(self.quick_grid)
        for i, game in enumerate(self.game_items):
            card = self._game_card(game, allow_remove=True)
            self.library_grid.addWidget(card, i // 2, i % 2)
            if i < 4:
                self.quick_grid.addWidget(self._game_card(game, allow_remove=False, compact=True), 0, i)
        if not self.game_items:
            empty = QLabel("No installed game launchers detected yet. Use ADD GAME to add a game or emulator executable/shortcut.")
            empty.setObjectName("mutedSmall")
            empty.setWordWrap(True)
            self.library_grid.addWidget(empty, 0, 0, 1, 2)
            self.quick_grid.addWidget(QLabel("Add a game to begin."), 0, 0)

    def _clear_layout(self, layout: QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _game_card(self, game: dict[str, str], allow_remove: bool, compact: bool = False) -> QWidget:
        card = GlassCard(object_name="gameCard")
        card.setMinimumHeight(166 if compact else 220)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)
        layout.addWidget(GameCover(game.get("name", "Game"), game.get("category", "CUSTOM"), compact=compact))
        cat = QLabel(game.get("category", "CUSTOM").upper())
        cat.setStyleSheet("color:#ff6771;font-size:7pt;font-weight:900;letter-spacing:2px;")
        layout.addWidget(cat)
        name = QLabel(game.get("name", "Game"))
        name.setStyleSheet("font-size:13pt;font-weight:900;color:#ffffff;")
        name.setWordWrap(True)
        layout.addWidget(name)
        path = QLabel(game.get("path", ""))
        path.setObjectName("mutedSmall")
        path.setWordWrap(True)
        path.setMaximumHeight(32 if compact else 38)
        layout.addWidget(path)
        row = QHBoxLayout()
        launch = QPushButton("▶  PLAY" if compact else "LAUNCH GAME")
        launch.setObjectName("primaryButton")
        launch.clicked.connect(lambda checked=False, p=game.get("path", ""), n=game.get("name", "Game"): self.launch_game(p, n))
        row.addWidget(launch)
        if allow_remove:
            remove = QPushButton("REMOVE")
            remove.setObjectName("secondaryButton")
            remove.setMaximumWidth(90)
            remove.clicked.connect(lambda checked=False, p=game.get("path", ""): self.remove_game(p))
            row.addWidget(remove)
        layout.addLayout(row)
        return card

    def navigate(self, name: str) -> None:
        if name not in self.pages:
            return
        self.stack.setCurrentWidget(self.pages[name])
        for n, button in self.nav_buttons.items():
            button.setChecked(n == name)

    def refresh_process_list(self) -> None:
        if not hasattr(self, "target_combo"):
            return
        current = self.target_combo.currentText().strip()
        names = set()
        try:
            for proc in psutil.process_iter(["name"]):
                n = proc.info.get("name")
                if n and n.lower().endswith(".exe"):
                    names.add(n)
        except (psutil.Error, OSError):
            pass
        preferred = ["HD-Player.exe", "FreeFire.exe", "FreeFireIndia.exe", "AndroidEmulatorEx.exe", "GameLoop.exe"]
        choices = [n for n in preferred if n in names] + sorted(n for n in names if any(x in n.lower() for x in ("game", "freefire", "player", "emulator", "minecraft", "valorant", "cs2")))
        unique = list(dict.fromkeys(choices))
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        self.target_combo.addItems(unique or preferred)
        self.target_combo.setCurrentText(current or str(self.settings.get("fps_process_name", "HD-Player.exe")))
        self.target_combo.blockSignals(False)

    def refresh_metrics(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        try:
            fps_value, fps_status = self.fps.read_fps()
            self.metrics = self.telemetry.sample(fps_value, fps_status)
            self.stat_cpu.set_data(format_percent(self.metrics.cpu_percent), f"{psutil.cpu_count(logical=True) or '?'} logical threads")
            gpu_detail = self.metrics.gpu_name if self.metrics.gpu_name else "GPU telemetry unavailable"
            if self.metrics.gpu_temp_c is not None:
                gpu_detail += f"  •  {self.metrics.gpu_temp_c:.0f} °C"
            if self.metrics.gpu_mem_used_mb is not None and self.metrics.gpu_mem_total_mb is not None:
                gpu_detail += f"  •  VRAM {self.metrics.gpu_mem_used_mb / 1024:.1f}/{self.metrics.gpu_mem_total_mb / 1024:.1f} GB"
            self.stat_gpu.set_data(format_percent(self.metrics.gpu_percent), gpu_detail)
            self.stat_ram.set_data(format_percent(self.metrics.ram_percent), f"{format_gb(self.metrics.ram_used_gb)} used of {format_gb(self.metrics.ram_total_gb)}")
            self.stat_fps.set_data(f"{fps_value:.0f} FPS" if fps_value is not None else "N/A", fps_status)
            if hasattr(self, "perf_cpu"):
                self.perf_cpu.set_data(format_percent(self.metrics.cpu_percent), "Windows performance counter")
                self.perf_gpu.set_data(format_percent(self.metrics.gpu_percent), f"{self.metrics.gpu_temp_c:.0f} °C" if self.metrics.gpu_temp_c is not None else self.metrics.gpu_name)
                self.perf_ram.set_data(format_percent(self.metrics.ram_percent), f"{format_gb(self.metrics.ram_used_gb)} used / {format_gb(self.metrics.ram_total_gb)}")
                self.perf_fps.set_data(f"{fps_value:.0f} FPS" if fps_value is not None else "N/A", fps_status)
                if hasattr(self, "fps_status_label"):
                    self.fps_status_label.setText(fps_status)
                    self.fan_status_label.setText(self.fan.status)
                    if self.metrics.gpu_fan_percent is not None:
                        self.fan_actual_label.setText(f"Current NVIDIA fan telemetry: {self.metrics.gpu_fan_percent:.0f}% (driver-reported)")
                    else:
                        self.fan_actual_label.setText("Current fan telemetry: N/A from driver; manual requests may still be rejected")
            if self.overlay.isVisible():
                self.overlay.update_metrics(self.metrics)
        except Exception as exc:
            logging.exception("Telemetry refresh failed")
            self._set_toast(f"Telemetry refresh issue: {exc}")
        finally:
            self._refreshing = False

    def start_fps_capture(self) -> None:
        name = self.target_combo.currentText().strip() if hasattr(self, "target_combo") else "HD-Player.exe"
        self.settings["fps_process_name"] = name
        save_settings(self.settings)
        ok, status = self.fps.start(name)
        self.fps_status_label.setText(status)
        self.start_fps_btn.setText("↻  RESTART FPS CAPTURE" if ok else "▶  RETRY FPS CAPTURE")
        self._set_toast(status)
        self.refresh_metrics()

    def toggle_overlay(self, enabled: bool) -> None:
        self.settings["show_overlay_on_start"] = bool(enabled)
        if enabled:
            self.overlay.update_metrics(self.metrics)
            self.overlay.show()
            self.overlay.raise_()
            self._set_toast("Performance overlay enabled. Drag it to reposition.")
        else:
            self.overlay.hide()
            self._set_toast("Performance overlay hidden.")
        if hasattr(self, "pref_overlay_check"):
            self.pref_overlay_check.blockSignals(True)
            self.pref_overlay_check.setChecked(bool(enabled))
            self.pref_overlay_check.blockSignals(False)
        save_settings(self.settings)

    def _sync_overlay_preference(self, enabled: bool) -> None:
        self.settings["show_overlay_on_start"] = bool(enabled)
        self.overlay_check.blockSignals(True)
        self.overlay_check.setChecked(bool(enabled))
        self.overlay_check.blockSignals(False)
        if enabled:
            self.overlay.update_metrics(self.metrics)
            self.overlay.show()
        else:
            self.overlay.hide()
        save_settings(self.settings)

    def _sync_clean_preference(self, enabled: bool) -> None:
        self.settings["auto_clean_temp"] = bool(enabled)
        if hasattr(self, "auto_clean_check"):
            self.auto_clean_check.blockSignals(True)
            self.auto_clean_check.setChecked(bool(enabled))
            self.auto_clean_check.blockSignals(False)
        if hasattr(self, "pref_clean_check"):
            self.pref_clean_check.blockSignals(True)
            self.pref_clean_check.setChecked(bool(enabled))
            self.pref_clean_check.blockSignals(False)
        save_settings(self.settings)

    def save_preferences(self, *_args) -> None:
        self._sync_clean_preference(self.auto_clean_check.isChecked())

    def _load_games_save(self) -> None:
        self.settings["games"] = self.game_items
        save_settings(self.settings)

    def add_game(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Add game or launcher", str(Path.home()), "Applications and shortcuts (*.exe *.lnk);;All files (*.*)")
        if not path:
            return
        if any(g.get("path", "").casefold() == path.casefold() for g in self.game_items):
            self._set_toast("That game is already in your library.")
            return
        name = Path(path).stem.replace("_", " ")
        self.game_items.append({"name": name, "path": path, "category": "CUSTOM"})
        self._load_games_save()
        self._rebuild_games()
        self._set_toast(f"Added {name} to the library.")

    def remove_game(self, path: str) -> None:
        item = next((g for g in self.game_items if g.get("path") == path), None)
        if not item:
            return
        if item.get("category") != "CUSTOM":
            answer = QMessageBox.question(self, "Remove detected game?", "Remove this detected launcher from the SARBA library list? This does not uninstall it.")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.game_items = [g for g in self.game_items if g.get("path") != path]
        self._load_games_save()
        self._rebuild_games()
        self._set_toast("Removed from SARBA library. The installed game was not deleted.")

    def launch_game(self, path: str, name: str) -> None:
        ok, message = launch_path(path)
        self._set_toast(message)
        if not ok:
            QMessageBox.warning(self, "Could not launch", message + "\n\nUse ADD GAME to select the correct executable or shortcut.")
        else:
            self.settings["fps_process_name"] = self.target_combo.currentText().strip() if hasattr(self, "target_combo") else "HD-Player.exe"
            save_settings(self.settings)

    def launch_msi(self) -> None:
        paths = [g for g in self.game_items if "msi" in g.get("name", "").lower() or "hd-player" in g.get("path", "").lower()]
        if paths:
            self.launch_game(paths[0]["path"], paths[0]["name"])
        else:
            QMessageBox.information(self, "MSI App Player not detected", "SARBA GUI could not find MSI App Player automatically.\n\nOpen Game Library → ADD GAME and select the MSI App Player shortcut or HD-Player.exe.")
            self.navigate("Game Library")

    def clean_temp_now(self) -> None:
        answer = QMessageBox.question(self, "Clean user temporary files", "Remove available files from your current Windows user TEMP folder? Locked or inaccessible files will be skipped. Close active apps first because some apps may rely on temporary files.\n\nThis does not remove Downloads, browser passwords, game data, or Windows system folders.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_temp_cleanup(max_age_hours=0, startup=False)

    def _start_temp_cleanup(self, max_age_hours: float, startup: bool) -> None:
        if self._cleanup_worker is not None and self._cleanup_worker.isRunning():
            self._set_toast("A temp cleanup is already running.")
            return
        self._set_toast("Cleaning user temporary files in the background…")
        if hasattr(self, "cleanup_status"):
            self.cleanup_status.setText("Cleanup running in the background…")
        self._cleanup_worker = TempCleanupWorker(max_age_hours)
        self._cleanup_worker.completed.connect(lambda result, is_startup=startup: self._temp_cleanup_complete(result, is_startup))
        self._cleanup_worker.start()

    def _temp_cleanup_complete(self, result, startup: bool) -> None:
        if result is None:
            message = "Temp cleanup failed; see the SARBA-GUI log for details."
            logging.error(message)
        else:
            prefix = "Startup cleanup" if startup else "Cleanup complete"
            message = f"{prefix}: {result.files_removed} file(s), {self._human_bytes(result.bytes_freed)} recovered; {result.skipped} skipped."
            logging.info("%s Removed=%d bytes=%d skipped=%d root=%s", prefix, result.files_removed, result.bytes_freed, result.skipped, result.root)
        if hasattr(self, "cleanup_status"):
            self.cleanup_status.setText(message)
        self._set_toast(message)

    @staticmethod
    def _human_bytes(value: int) -> str:
        amount = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if amount < 1024 or unit == "GB":
                return f"{amount:.1f} {unit}"
            amount /= 1024
        return f"{amount:.1f} GB"

    def set_power_plan(self) -> None:
        answer = QMessageBox.question(self, "Windows power plan", "Select Windows High Performance power plan? This can increase power use and heat.\n\nYou can switch back to Balanced in Windows Settings.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        ok, message = set_high_performance_power_plan()
        self._set_toast(message)
        if not ok:
            QMessageBox.warning(self, "Power plan unchanged", message)

    def apply_fan_speed(self) -> None:
        value = int(self.fan_slider.value())
        answer = QMessageBox.warning(self, "Manual GPU fan speed", f"Request {value}% GPU fan speed?\n\nNot all NVIDIA cards/drivers allow manual control. Keep temperatures monitored; do not use a low fan speed under load.", QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Apply:
            return
        ok, message = self.fan.set_percent(value)
        self.fan_status_label.setText(message)
        self.fan.status = message
        self._set_toast(message)
        if not ok:
            QMessageBox.information(self, "Fan control not available", message)

    def restore_fan_auto(self) -> None:
        ok, message = self.fan.restore_auto()
        self.fan.status = message
        if hasattr(self, "fan_status_label"):
            self.fan_status_label.setText(message)
        self._set_toast(message)
        if not ok:
            QMessageBox.information(self, "Automatic fan control", message)

    def _safe_restore_fan(self) -> None:
        # Best effort restore avoids leaving the card in a manual fan mode after normal exit.
        try:
            self.fan.restore_auto()
        except Exception:
            pass

    def run_system_check(self) -> None:
        checks: list[tuple[str, str, str]] = []
        checks.append(("Operating system", "PASS" if os.name == "nt" else "WARN", "Windows-only utilities require Windows 10/11." if os.name != "nt" else f"Windows environment detected: {os.environ.get('OS', 'Windows_NT')}"))
        checks.append(("CPU telemetry", "PASS" if self.metrics.cpu_percent is not None else "WARN", f"{self.metrics.cpu_percent:.0f}% load" if self.metrics.cpu_percent is not None else "CPU reading unavailable."))
        checks.append(("Memory telemetry", "PASS" if self.metrics.ram_percent is not None else "WARN", f"{self.metrics.ram_used_gb:.1f}/{self.metrics.ram_total_gb:.1f} GB in use" if self.metrics.ram_used_gb is not None and self.metrics.ram_total_gb is not None else "RAM reading unavailable."))
        gpu_ok = self.metrics.gpu_percent is not None
        checks.append(("NVIDIA telemetry", "PASS" if gpu_ok else "WARN", f"{self.metrics.gpu_name}; usage {format_percent(self.metrics.gpu_percent)}"))
        pm_ok = self.fps.binary() is not None
        checks.append(("FPS provider", "PASS" if pm_ok else "WARN", "PresentMon helper is bundled." if pm_ok else "PresentMon helper is missing; FPS remains N/A until packaged."))
        checks.append(("Game library", "PASS" if self.game_items else "WARN", f"{len(self.game_items)} launcher(s)/game(s) configured."))
        checks.append(("GPU fan controller", "INFO" if "ready" in self.fan.status.lower() else "WARN", self.fan.status))
        lines = ["SARBA GUI SYSTEM CHECK", "=" * 26]
        for name, status, detail in checks:
            lines.append(f"[{status}] {name}: {detail}")
        lines.append("")
        lines.append("FPS is N/A until a running game process is selected and PresentMon captures frames.")
        lines.append("Manual fan control is driver-dependent and must be confirmed by observed fan readings.")
        text = "\n".join(lines)
        logging.info("System check completed: %s", text.replace("\n", " | "))
        QMessageBox.information(self, "SARBA GUI System Check", text)
        self._set_toast("System check completed. Use Save System Report to export detailed readings and logs.")

    def save_report(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        name = f"SARBA-System-Report-{__import__('datetime').datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Save SARBA system report", str(Path.home() / name), "Text report (*.txt)")
        if not path:
            return
        text = system_report(self.metrics, self.fps.status, self.fan.status)
        try:
            Path(path).write_text(text, encoding="utf-8")
            self._set_toast(f"System report saved: {path}")
        except OSError as exc:
            logging.exception("Saving system report failed")
            QMessageBox.critical(self, "Unable to save report", str(exc))

    def open_tool(self, name: str, command: str) -> None:
        try:
            if command.startswith("ms-settings:"):
                if os.name == "nt":
                    os.startfile(command)  # type: ignore[attr-defined]
                else:
                    open_uri(command)
                return
            if command == "nvcplui.exe":
                import shutil
                located = shutil.which(command)
                if located:
                    os.startfile(located) if os.name == "nt" else launch_path(located)
                    return
                # Try the common NVIDIA control panel package launch path.
                candidates = [Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "NVIDIA Corporation" / "Control Panel Client" / "nvcplui.exe"]
                for candidate in candidates:
                    if candidate.exists():
                        os.startfile(str(candidate))
                        return
            if os.name == "nt":
                # Use shell resolution for Windows tools such as .msc and system app names.
                import subprocess
                subprocess.Popen(["cmd.exe", "/c", "start", "", command], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                ok, msg = launch_path(command)
                if not ok:
                    QMessageBox.information(self, name, msg)
        except (OSError, RuntimeError) as exc:
            QMessageBox.warning(self, f"Unable to open {name}", str(exc))

    def _set_toast(self, message: str) -> None:
        if hasattr(self, "toast"):
            self.toast.setText(message)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 60:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:
        if self._cleanup_worker is not None and self._cleanup_worker.isRunning():
            QMessageBox.information(self, "Cleanup still running", "SARBA GUI is still cleaning the user TEMP folder in the background. Please close the app again after the cleanup message appears.")
            event.ignore()
            return
        self._safe_restore_fan()
        self.fps.stop()
        self.telemetry.stop()
        self.overlay.close()
        self.settings["games"] = [g for g in self.game_items if g.get("category") == "CUSTOM"]
        save_settings(self.settings)
        event.accept()


def main() -> int:
    log_path = configure_logging()
    def _exception_hook(exc_type, exc_value, exc_tb):
        logging.critical("Uncaught application exception", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _exception_hook
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("SARBA")
    app.setStyle("Fusion")
    icon_path = resource_path("assets/SG.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = SARBAGUI()
    screen = app.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        target_w = max(920, min(1380, available.width() - 36))
        target_h = max(620, min(860, available.height() - 52))
        window.resize(target_w, target_h)
        window.setMinimumSize(min(920, target_w), min(620, target_h))
        window.move(available.center() - window.rect().center())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
