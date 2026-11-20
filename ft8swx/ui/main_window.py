"""Janela principal: cabecalho de estacao, waterfall, decodes, sequenciador TX."""

from __future__ import annotations

import math
import time
import traceback

import numpy as np
from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QSizePolicy, QSplitter, QStatusBar, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from ..adif import AdifLog, QsoRecord, band_from_mhz, is_recent_duplicate
from ..auto import CqCandidate, pick_cq
from ..audio import (
    FT8_RATE, SLOT_SECONDS, AudioConfig, AudioEngine, SlotCollector,
    backend_available, resample,
)
from ..cat import CatController, CatError, CatPtt
from ..clock import SlotClock
from ..config import BANDS, Settings
from ..grid import compass_point, distance_bearing
from ..levels import FLOOR_DB, LevelMeter, block_levels, tx_envelope
from ..native import Decoder
from ..parse import parse_message
from ..ptt import PttController, PttError
from ..qso import Phase, QsoEngine, fmt_report
from ..schedule import next_tx_slot, parity_name, tx_parity_for
from ..waterfall_model import WaterfallModel
from .export_dialog import ExportDialog
from .level_bar import LevelBar
from .map_view import MapPanel, MapWindow
from .settings_dialog import SettingsDialog
from .theme import C, THEMES, set_theme, stylesheet
from .waterfall import CompassWidget, SlotBar, SpectrumWidget, WaterfallWidget

SHORT_BANDS = ["160m", "80m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"]


class DecodeJob(QThread):
    done = Signal(float, object)   # (slot_start, [Result])
    failed = Signal(str)

    def __init__(self, decoder: Decoder, window: np.ndarray, slot_start: float):
        super().__init__()
        self.decoder = decoder
        self.window = window
        self.slot_start = slot_start

    def run(self) -> None:
        try:
            self.decoder.reset()
            n = self.decoder.frame_len
            pos = 0
            while pos + n <= self.window.size:
                self.decoder.feed(self.window[pos:pos + n])
                pos += n
            self.done.emit(self.slot_start, self.decoder.decode())
        except Exception:
            self.failed.emit(traceback.format_exc())


class TxJob(QThread):
    started_tx = Signal(str)
    finished_tx = Signal(bool, str)

    def __init__(self, ptt: PttController, audio: AudioEngine,
                 wave: np.ndarray, target_time: float, clock: SlotClock):
        super().__init__()
        self.ptt = ptt
        self.audio = audio
        self.wave = wave
        self.target_time = target_time
        self.clock = clock
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self.audio.stop_play()

    def run(self) -> None:
        try:
            while not self._cancelled:
                remaining = self.target_time - self.clock.now()
                if remaining <= 0.002:
                    break
                time.sleep(min(remaining, 0.05))
            if self._cancelled:
                self.finished_tx.emit(False, "cancelado")
                return
            with self.ptt.tx():
                self.started_tx.emit("TX")
                self.audio.play_12k(self.wave, blocking=True)
            self.finished_tx.emit(True, "")
        except PttError as exc:
            self.finished_tx.emit(False, f"PTT: {exc}")
        except Exception as exc:  # pragma: no cover
            self.finished_tx.emit(False, str(exc))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.s = settings
        self.clock = SlotClock(SLOT_SECONDS.get(settings.mode, 15.0))
        self.engine = QsoEngine(settings.my_call, settings.my_grid,
                                settings.tx_report, settings.max_repeats)
        self.log = AdifLog(settings.ensure_log())
        self.cat = CatController(settings.cat)
        self.ptt = self._make_ptt()
        self.audio = AudioEngine(AudioConfig(
            input_device=settings.input_device,
            output_device=settings.output_device,
            input_rate=settings.input_rate,
            output_rate=settings.output_rate,
            tx_gain=settings.tx_gain,
        ))
        self.model = WaterfallModel(FT8_RATE, width=600, f_min=200.0, f_max=3000.0)
        self.collector = SlotCollector(FT8_RATE, self.clock.slot_seconds)
        self.decoder = Decoder(200.0, 3000.0, FT8_RATE, settings.mode)
        self.encoder = Decoder(200.0, 3000.0, FT8_RATE, settings.mode)

        self.pending_tx: str | None = None
        self.tx_enabled = False
        self._tx_busy = False
        self._tx_job: TxJob | None = None
        self._decode_busy = False
        self._decode_job: DecodeJob | None = None
        self._last_tx_slot = -1
        self._auto_last_call = ""
        self._auto_last_slot = -999
        self._tx_parity = 0
        self._decodes: list = []
        self._grid_cache: dict[str, str] = {}   # indicativo -> ultimo grid visto
        self._pending_log = False               # loga so' depois de transmitir
        self._cat_hold_until = 0.0              # ignora leitura do VFO logo apos sintonizar
        self.rx_meter, self.tx_meter = LevelMeter(), LevelMeter()
        self._tx_env: list | None = None
        self._tx_t0 = 0.0
        self._inline: list = []                 # (widget, funcao->css) refeitos ao trocar o tema
        set_theme(settings.theme)
        self._map_win: MapWindow | None = None

        self._build_ui()

        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._on_tick)
        self.cat_timer = QTimer(self)
        self.cat_timer.setInterval(400)
        self.cat_timer.timeout.connect(self._cat_poll)

    # ==================================================================
    # construcao da interface
    # ==================================================================
    def _chip(self, text: str = "", name: str = "Chip") -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("class", "Chip")
        lbl.setObjectName(name)
        return lbl

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("FieldLabel")
        lbl.setFixedHeight(13)
        lbl.setContentsMargins(1, 0, 0, 0)
        return lbl

    def _build_ui(self) -> None:
        from .. import __version__

        self.setWindowTitle(f"FT8SWX {__version__}")
        self.resize(1280, 840)
        self.setStyleSheet(stylesheet())

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(self._build_header())

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        self.spectrum = SpectrumWidget()
        self.waterfall = WaterfallWidget()
        self.slotbar = SlotBar()
        self.waterfall.set_model(self.model)
        self.spectrum.set_model(self.model)
        self.spectrum.freqClicked.connect(self._set_tx_freq)
        self.waterfall.freqClicked.connect(self._set_tx_freq)
        lv.addWidget(self.spectrum)
        lv.addWidget(self.waterfall, 1)
        lv.addWidget(self.slotbar)

        right = QTabWidget()
        right.setDocumentMode(True)
        right.addTab(self._build_decode_table(), "DECODES")
        right.addTab(self._build_log_table(), "LOG")
        right.addTab(self._build_qso_panel(), "QSO")
        right.addTab(self._build_map_tab(), "MAPA")

        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([760, 500])
        self._set_tx_freq(self.s.tx_offset_hz)
        root.addWidget(split, 1)
        root.addWidget(self._build_tx_bar())
        self.setCentralWidget(central)

        sb = QStatusBar()
        self.lbl_clock = QLabel("--:--:--")
        self.lbl_slot = QLabel("slot --")
        self.lbl_parity = self._chip("TX: par")
        self.lbl_ntp = self._chip("NTP: --")
        self.lbl_audio = self._chip("audio: --")
        self.lbl_ptt = self._chip("PTT: off")
        self.lbl_cat = self._chip("CAT: off")
        self.lbl_rxcount = self._chip("0 decodes")
        for w in (self.lbl_rxcount, self.lbl_slot, self.lbl_parity,
                  self.lbl_ntp, self.lbl_audio, self.lbl_cat, self.lbl_ptt, self.lbl_clock):
            sb.addPermanentWidget(w)
        self.lbl_clock.setObjectName("ClockSub")
        self.setStatusBar(sb)

        menu = self.menuBar().addMenu("&Estacao")
        act_settings = QAction("Configuracoes...", self)
        act_settings.triggered.connect(self._open_settings)
        menu.addAction(act_settings)
        act_sync = QAction("Sincronizar relogio (NTP)", self)
        act_sync.triggered.connect(lambda: self._sync_clock(async_=False))
        menu.addAction(act_sync)
        menu_log = self.menuBar().addMenu("&Log")
        act_export = QAction("Exportar ADIF (QRZ / LoTW)...", self)
        act_export.triggered.connect(self._export_log)
        menu_log.addAction(act_export)
        act_folder = QAction("Abrir pasta do log", self)
        act_folder.triggered.connect(self._open_log_folder)
        menu_log.addAction(act_folder)

        menu_view = self.menuBar().addMenu("E&xibir")
        menu_tema = menu_view.addMenu("Tema")
        self._theme_group = QActionGroup(self)
        self._theme_acts: dict[str, QAction] = {}
        for name, (label, _) in THEMES.items():
            a = QAction(label, self)
            a.setCheckable(True)
            a.setChecked(name == self.s.theme)
            a.triggered.connect(lambda _=False, n=name: self._pick_theme(n))
            self._theme_group.addAction(a)
            menu_tema.addAction(a)
            self._theme_acts[name] = a

        menu.addSeparator()
        act_quit = QAction("Sair", self)
        act_quit.triggered.connect(self.close)
        menu.addAction(act_quit)

        self._update_parity_label()
        self._sync_auto_button()

    def _sync_auto_button(self) -> None:
        if hasattr(self, "bt_auto"):
            self.bt_auto.setChecked(bool(self.s.auto_call_cq))

    def _build_header(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("Header")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(10)

        # --- linha 1: identidade, bandas, relogio ---
        row1 = QHBoxLayout()
        row1.setSpacing(14)
        logo = QVBoxLayout()
        logo.setSpacing(0)
        lb = QLabel("FT8")
        lb.setObjectName("Logo")
        sub = QLabel("S W X")
        sub.setObjectName("LogoSub")
        logo.addWidget(lb)
        logo.addWidget(sub)
        row1.addLayout(logo)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        self._sty(sep, lambda: f"color: {C['border2']};")
        row1.addWidget(sep)

        bands = QHBoxLayout()
        bands.setSpacing(4)
        self.band_buttons: dict[str, QPushButton] = {}
        for name, mhz in BANDS:
            if name not in SHORT_BANDS:
                continue
            btn = QPushButton(name.replace("m", ""))
            btn.setObjectName("Band")
            btn.setCheckable(True)
            btn.setToolTip(f"{name} - {mhz:.3f} MHz")
            btn.clicked.connect(lambda _=False, n=name: self._select_band(n))
            self.band_buttons[name] = btn
            bands.addWidget(btn)
        row1.addLayout(bands)
        row1.addStretch(1)

        clock_box = QVBoxLayout()
        clock_box.setSpacing(0)
        self.lbl_utc = QLabel("--:--:--")
        self.lbl_utc.setObjectName("Clock")
        self.lbl_utc.setAlignment(Qt.AlignmentFlag.AlignRight)
        utc_lbl = QLabel("U T C")
        utc_lbl.setObjectName("ClockSub")
        utc_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        clock_box.addWidget(self.lbl_utc)
        clock_box.addWidget(utc_lbl)
        row1.addLayout(clock_box)
        outer.addLayout(row1)

        # --- linha 2: frequencia e estacao ---
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        dial_box = QVBoxLayout()
        dial_box.setSpacing(2)
        dial_box.addWidget(self._field_label("discagem"))
        self.ed_dial = QLineEdit(f"{self.s.dial_mhz:.4f}")
        self.ed_dial.setFixedWidth(96)
        self.ed_dial.setToolTip("Frequencia de discagem (informativa - sintonize o radio)")
        self.ed_dial.editingFinished.connect(self._dial_edited)
        dial_box.addWidget(self.ed_dial)
        row2.addLayout(dial_box)

        mhz_lbl = QLabel("MHz")
        self._sty(mhz_lbl, lambda: f"color:{C['text_faint']}; padding-top:16px;")
        row2.addWidget(mhz_lbl, 0, Qt.AlignmentFlag.AlignTop)

        tx_box = QVBoxLayout()
        tx_box.setSpacing(2)
        tx_box.addWidget(self._field_label("frequencia tx"))
        self.sp_freq = QDoubleSpinBox()
        self.sp_freq.setRange(200, 2900)
        self.sp_freq.setDecimals(0)
        self.sp_freq.setSingleStep(10)
        self.sp_freq.setSuffix(" Hz")
        self.sp_freq.setFixedWidth(96)
        self.sp_freq.setValue(self.s.tx_offset_hz)
        self.sp_freq.valueChanged.connect(self._set_tx_freq)
        tx_box.addWidget(self.sp_freq)
        row2.addLayout(tx_box)

        call_box = QVBoxLayout()
        call_box.setSpacing(2)
        call_box.addWidget(self._field_label("indicativo"))
        self.ed_call = QLineEdit(self.s.my_call)
        self.ed_call.setObjectName("Call")
        self.ed_call.setFixedWidth(112)
        self.ed_call.editingFinished.connect(self._callsign_changed)
        call_box.addWidget(self.ed_call)
        row2.addLayout(call_box)

        grid_box = QVBoxLayout()
        grid_box.setSpacing(2)
        grid_box.addWidget(self._field_label("grid"))
        self.ed_grid = QLineEdit(self.s.my_grid)
        self.ed_grid.setObjectName("Grid")
        self.ed_grid.setFixedWidth(86)
        self.ed_grid.editingFinished.connect(self._callsign_changed)
        grid_box.addWidget(self.ed_grid)
        row2.addLayout(grid_box)

        row2.addSpacing(16)
        lv_box = QVBoxLayout()
        lv_box.setSpacing(2)
        lv_box.addWidget(self._field_label("nivel de audio (dBFS)"))
        self.bar_rx = LevelBar("RX", -45.0, -15.0,
            "Entrada (receptor). Verde = bom (-45 a -15 dBFS). Ambar = fraco ou alto demais.\n"
            "LED vermelho = saturando: reduza o volume do radio/placa. Faixas indicativas.")
        self.bar_tx = LevelBar("TX", -40.0, -3.0,
            "Saida (transmissao). O ganho de TX fica em Configuracoes > Audio. "
            "Nao deve saturar nem causar ALC no radio.")
        lv_box.addWidget(self.bar_rx)
        lv_box.addWidget(self.bar_tx)
        row2.addLayout(lv_box)

        row2.addStretch(1)
        self.chip_mode = self._chip(self.s.mode)
        self.chip_qsos = self._chip("0 QSOs")
        row2.addWidget(self.chip_mode, 0, Qt.AlignmentFlag.AlignBottom)
        row2.addWidget(self.chip_qsos, 0, Qt.AlignmentFlag.AlignBottom)
        outer.addLayout(row2)

        self._refresh_band_buttons()
        return frame

    def _build_decode_table(self) -> QWidget:
        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(["UTC", "dB", "DT", "Hz", "Mensagem"])
        hdr = self.tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.verticalHeader().setDefaultSectionSize(21)
        self.tbl.setShowGrid(False)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.cellDoubleClicked.connect(self._on_decode_activated)
        self.tbl.setToolTip("Duplo clique: chamar a estacao")
        return self.tbl

    def _build_log_table(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        bar = QHBoxLayout()
        self.lbl_log_count = QLabel("0 QSOs")
        self._sty(self.lbl_log_count, lambda: f"color:{C['text_dim']};")
        self.bt_export = QPushButton("Exportar ADIF...")
        self.bt_export.setObjectName("Primary")
        self.bt_export.setToolTip("Gerar arquivo ADIF para subir no QRZ / LoTW")
        self.bt_export.clicked.connect(self._export_log)
        self.bt_openlog = QPushButton("Abrir pasta")
        self.bt_openlog.clicked.connect(self._open_log_folder)
        self.bt_clearlog = QPushButton("Limpar log...")
        self.bt_clearlog.setObjectName("Danger")
        self.bt_clearlog.setToolTip("Arquiva o log atual e comeca um novo em branco")
        self.bt_clearlog.clicked.connect(self._clear_log)
        bar.addWidget(self.bt_export)
        bar.addWidget(self.bt_openlog)
        bar.addWidget(self.bt_clearlog)
        bar.addWidget(self.lbl_log_count)
        bar.addStretch(1)
        v.addLayout(bar)

        self.tbl_log = QTableWidget(0, 6)
        self.tbl_log.setHorizontalHeaderLabels(
            ["UTC", "Indicativo", "Grid", "Banda", "Env.", "Rec."])
        hdr = self.tbl_log.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.tbl_log.verticalHeader().setVisible(False)
        self.tbl_log.verticalHeader().setDefaultSectionSize(21)
        self.tbl_log.setShowGrid(False)
        self.tbl_log.setAlternatingRowColors(True)
        self.tbl_log.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        v.addWidget(self.tbl_log, 1)
        self._load_log_table()
        return wrap

    def _build_qso_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)

        self.lbl_qso_state = QLabel("OCIOSO")
        f = QFont()
        f.setBold(True)
        f.setPixelSize(13)
        self.lbl_qso_state.setFont(f)
        self.lbl_qso_state.setStyleSheet(f"color:{C['accent']}; letter-spacing:2px;")

        self.lbl_qso_dx = QLabel("-")
        f2 = QFont("Consolas")
        f2.setPixelSize(26)
        f2.setBold(True)
        self.lbl_qso_dx.setFont(f2)

        top = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(self.lbl_qso_state)
        left.addWidget(self.lbl_qso_dx)
        self.lbl_qso_meta = QLabel("")
        self._sty(self.lbl_qso_meta, lambda: f"color:{C['text_dim']};")
        left.addWidget(self.lbl_qso_meta)
        left.addStretch(1)
        top.addLayout(left, 1)
        self.compass = CompassWidget()
        top.addWidget(self.compass, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(top)

        self.lbl_qso_info = QLabel("-")
        self.lbl_qso_info.setWordWrap(True)
        self._sty(self.lbl_qso_info,
                  lambda: f"color:{C['text_dim']}; font-family:'Consolas'; font-size:11px;")
        v.addWidget(self.lbl_qso_info)
        v.addStretch(1)
        return w

    def _build_tx_bar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("Header")
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(self._field_label("sequencia"))
        self.tx_buttons: list[QPushButton] = []
        for i in range(6):
            btn = QPushButton(f"Tx{i + 1}")
            btn.setObjectName("TxSeq")
            btn.setCheckable(True)
            btn.setEnabled(False)
            btn.clicked.connect(lambda _=False, idx=i: self._select_tx_slot(idx))
            self.tx_buttons.append(btn)
            row1.addWidget(btn)
        row1.addStretch(1)

        self.btn_gen = QPushButton("Gerar")
        self.btn_gen.setToolTip("Gerar as mensagens padrao para o QSO atual")
        self.btn_gen.clicked.connect(self._refresh_tx_seq)
        self.bt_auto = QPushButton("AUTO")
        self.bt_auto.setCheckable(True)
        self.bt_auto.setToolTip("Modo automatico: chama quem esta em CQ e "
                                "responde sozinho ate completar o QSO")
        self.bt_auto.toggled.connect(self._toggle_auto)
        self.bt_cq = QPushButton("CQ")
        self.bt_cq.setObjectName("Primary")
        self.bt_cq.clicked.connect(self._start_cq)
        row1.addWidget(self.btn_gen)
        row1.addWidget(self.bt_auto)
        row1.addWidget(self.bt_cq)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(self._field_label("tx"))
        self.ed_tx = QLineEdit()
        self.ed_tx.setPlaceholderText("mensagem a transmitir (ex.: CQ PY2ABC GG66)")
        self.ed_tx.setFont(QFont("Consolas"))
        self.ed_tx.returnPressed.connect(self._queue_manual)
        row2.addWidget(self.ed_tx, 1)

        self.chk_enable = QCheckBox("Habilitar TX")
        self.chk_enable.setStyleSheet("font-weight:600;")
        self.chk_enable.toggled.connect(self._tx_toggled)
        self.bt_stop = QPushButton("Parar")
        self.bt_stop.setObjectName("Danger")
        self.bt_stop.clicked.connect(self._halt_tx)
        self.bt_test_ptt = QPushButton("Testar PTT")
        self.bt_test_ptt.clicked.connect(self._test_ptt)
        row2.addWidget(self.chk_enable)
        row2.addWidget(self.bt_test_ptt)
        row2.addWidget(self.bt_stop)
        v.addLayout(row2)
        return frame

    # ==================================================================
    # ciclo de vida
    # ==================================================================
    def start(self) -> None:
        ok, err = backend_available()
        if ok:
            try:
                self.audio.start_rx()
                self._set_chip(self.lbl_audio,
                               f"{self.s.input_rate // 1000}k / "
                               f"{self.s.output_rate // 1000}k", "ChipOk")
            except Exception as exc:
                self._set_chip(self.lbl_audio, "audio: erro", "ChipErr")
                QMessageBox.warning(self, "Audio",
                                    f"Nao foi possivel abrir o audio de entrada:\n{exc}")
        else:
            self._set_chip(self.lbl_audio, "audio: off", "ChipErr")
            QMessageBox.warning(self, "Audio",
                                f"Backend de audio indisponivel:\n{err or 'sounddevice ausente'}\n\n"
                                "Instale com: pip install sounddevice")

        self._open_rig()
        self.cat_timer.start()

        if self.s.ntp_sync:
            self._sync_clock(async_=True)
        self.timer.start()

    def closeEvent(self, ev) -> None:  # noqa: N802
        self.timer.stop()
        self.cat_timer.stop()
        if self._map_win is not None:
            self._map_win.close()
        if self._tx_job and self._tx_job.isRunning():
            self._tx_job.cancel()
            self._tx_job.wait(1500)
        # a thread de decode usa memoria nativa do decoder: ela precisa terminar ANTES do close()
        job = self._decode_job
        decode_done = True
        if job is not None and job.isRunning():
            decode_done = job.wait(8000)
        self.audio.close()
        self.ptt.close()
        self.cat.close()
        if decode_done:
            try:
                self.decoder.close()
                self.encoder.close()
            except Exception:
                pass
        super().closeEvent(ev)

    def _set_chip(self, label: QLabel, text: str, name: str = "Chip") -> None:
        label.setText(text)
        label.setObjectName(name)
        label.style().unpolish(label)
        label.style().polish(label)

    def _sync_clock(self, async_: bool = True) -> None:
        if async_:
            import threading

            def work():
                st = self.clock.sync_ntp()
                self._ntp_done(st)
            threading.Thread(target=work, daemon=True).start()
        else:
            self._ntp_done(self.clock.sync_ntp())

    def _ntp_done(self, st) -> None:
        if st.synced:
            self._set_chip(self.lbl_ntp, f"NTP {st.offset * 1000:+.0f} ms", "ChipOk")
            self.lbl_ntp.setToolTip(
                f"fonte: {st.source}  estrato: {st.stratum}  "
                f"precisao: {st.precision}")
        else:
            self._set_chip(self.lbl_ntp, "NTP falhou", "ChipErr")
            self.lbl_ntp.setToolTip(st.error)

    # ==================================================================
    # loop principal
    # ==================================================================
    def _update_meters(self) -> None:
        now = time.monotonic()
        if self.rx_meter._t is None or now - self.rx_meter._t > 0.25:
            self.rx_meter.decay(now)                  # sem audio chegando: a barra cai
        self.bar_rx.set_state(self.rx_meter.level, self.rx_meter.peak, self.rx_meter.clip(now))
        env = self._tx_env
        idx = int((now - self._tx_t0) / 0.05) if env else -1
        if env and 0 <= idx < len(env):
            self.tx_meter.push(*env[idx], now)
        else:
            self.tx_meter.decay(now)
        self.bar_tx.set_state(self.tx_meter.level, self.tx_meter.peak, self.tx_meter.clip(now))

    def _on_tick(self) -> None:
        self._update_meters()
        utc = self.clock.utc_string()
        self.lbl_utc.setText(utc)
        self.lbl_clock.setText(utc)
        elapsed = self.clock.elapsed_in_slot()
        self.slotbar.set_state(elapsed / self.clock.slot_seconds,
                               self.s.tx_offset_s, self.clock.slot_seconds,
                               self._tx_parity)
        self.waterfall.set_elapsed(elapsed, self._decode_busy)
        self.lbl_slot.setText(f"{self.clock.time_to_next_slot():4.1f} s")
        self._pump_audio()
        self._maybe_tx()
        self._watchdog()
        self._update_qso_panel()

    def _watchdog(self) -> None:
        """QSO sem nenhum sinal de vida (TX nem RX) por 2 minutos e' abandonado."""
        st = self.engine.state
        if not st.active or st.phase == Phase.CQ:
            return
        now = self.clock.now()
        ref = st.progress_at or st.started_at or now
        if now - ref > 120.0:
            self.engine.abort("sem progresso")
            self.pending_tx = None
            self.statusBar().showMessage(
                "QSO sem progresso por 2 min - abandonado, AUTO retomado", 6000)
            self._refresh_tx_seq()

    def _pump_audio(self) -> None:
        blocks = self.audio.drain()
        if not blocks:
            return
        total = sum(b.size for b in blocks)
        t = self.clock.now() - total / float(self.s.input_rate)
        now = time.monotonic()
        for b in blocks:
            self.rx_meter.push(*block_levels(b), now)
            t += b.size / float(self.s.input_rate)
            x = resample(b, self.s.input_rate, FT8_RATE)
            self.model.add_audio(x)
            for slot_start, window in self.collector.push(x, t):
                self._start_decode(window, slot_start)
        self.waterfall.update()
        self.spectrum.update()

    def _start_decode(self, window: np.ndarray, slot_start: float) -> None:
        if self._decode_busy:
            return
        self._decode_busy = True
        job = DecodeJob(self.decoder, window, slot_start)
        job.done.connect(self._on_decoded)
        job.failed.connect(self._on_decode_failed)
        job.finished.connect(self._on_decode_finished)
        self._decode_job = job
        job.start()

    def _on_decode_finished(self) -> None:
        self._decode_busy = False

    def _on_decode_failed(self, msg: str) -> None:
        self.statusBar().showMessage("Falha ao decodificar: " + msg.splitlines()[-1], 5000)

    def _on_decoded(self, slot_start: float, results: list) -> None:
        utc = time.strftime("%H:%M:%S", time.gmtime(slot_start))
        slot_idx = int(round(slot_start / self.clock.slot_seconds))
        markers: list[tuple[float, str, float]] = []
        worked = self.log.worked_calls(self.s.band)

        for r in sorted(results, key=lambda r: r.freq_hz):
            text = r.text.decode("ascii", "replace").strip()
            p = parse_message(text, self.s.my_call)
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)
            dt = r.time_s - 0.16
            vals = [utc, f"{r.snr:+.0f}", f"{dt:+.1f}", f"{r.freq_hz:.0f}", text]

            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 4:
                    item.setData(Qt.ItemDataRole.UserRole, text)
                item.setData(Qt.ItemDataRole.UserRole + 1, slot_idx)
                ckey = None
                if c == 4:
                    if p.is_cq:
                        ckey = "accent"
                    elif p.call_to and p.call_to.upper() == self.s.my_call:
                        ckey = "blue"
                    elif p.token in ("73", "RR73"):
                        ckey = "text_faint"
                    elif p.call_from.upper() in worked:
                        ckey = "text_dim"
                elif c == 1:
                    ckey = ("accent" if r.snr > -6
                            else "amber" if r.snr > -16 else "text_faint")
                if ckey is not None:
                    item.setForeground(QColor(C[ckey]))
                    item.setData(Qt.ItemDataRole.UserRole + 2, ckey)
                if p.call_to and p.call_to.upper() == self.s.my_call:
                    item.setBackground(QColor(C["row_me"]))
                    item.setData(Qt.ItemDataRole.UserRole + 3, True)
                self.tbl.setItem(row, c, item)

            if p.call_from and not p.is_cq:
                markers.append((r.freq_hz, p.call_from, dt))
            elif p.is_cq:
                markers.append((r.freq_hz, p.call_from, dt))
            self._process_single(text, r, slot_idx)

        self.tbl.scrollToBottom()
        self.waterfall.set_markers(markers)
        self.lbl_rxcount.setText(f"{len(results)} decodes")

        # ---- modo AUTO: escolher uma estacao chamando CQ ----
        if self.s.auto_call_cq and not self.engine.state.active \
                and not self.pending_tx and self.tx_enabled:
            cands = []
            for r in results:
                txt = r.text.decode("ascii", "replace").strip()
                pp = parse_message(txt, self.s.my_call)
                if not pp.is_cq or not pp.call_from:
                    continue
                cands.append(CqCandidate(
                    call=pp.call_from, grid=pp.grid, snr=float(r.snr),
                    freq_hz=float(r.freq_hz), dt=float(r.time_s - 0.16),
                    slot_index=slot_idx, cq_modifier=pp.cq_modifier, raw=txt))
            cand = pick_cq(cands, worked, min_snr=self.s.auto_min_snr,
                           skip_worked=self.s.auto_skip_worked,
                           skip_cq_dx=self.s.auto_skip_cq_dx)
            if cand is not None:
                self._auto_call(cand)
            elif cands:
                self._auto_explain(cands)

    def _auto_explain(self, cands: list) -> None:
        """Diz POR QUE nenhum CQ foi chamado -- silencio sem motivo confunde."""
        low = [c for c in cands if c.snr < self.s.auto_min_snr]
        dx = [c for c in cands if c.is_cq_dx]
        if len(low) == len(cands):
            motivo = f"todos abaixo de {self.s.auto_min_snr:.0f} dB"
        elif len(dx) == len(cands) and self.s.auto_skip_cq_dx:
            motivo = 'todos sao "CQ DX" (ignorado nas opcoes)'
        elif self.s.auto_skip_worked:
            motivo = f"todos ja estao no log em {self.s.band}"
        else:
            motivo = "filtros ativos em Configuracoes > Avancado"
        self.statusBar().showMessage(
            f"AUTO: {len(cands)} CQ(s) ouvido(s), nenhum chamado - {motivo}", 5000)

    def _auto_call(self, cand: CqCandidate) -> None:
        """Chama automaticamente uma estacao em CQ (modo AUTO)."""
        if cand.call == self._auto_last_call and \
                cand.slot_index - self._auto_last_slot < 10:
            return   # evitou insistir na mesma estacao
        self._auto_last_call = cand.call
        self._auto_last_slot = cand.slot_index
        self.engine.configure(self.s.my_call, self.s.my_grid, self.s.tx_report)
        self._tx_parity = tx_parity_for(cand.slot_index)
        self._update_parity_label()
        self._queue(self.engine.call(cand.call, cand.grid, they_cq=True,
                                     now=self.clock.now()))
        self.statusBar().showMessage(
            f"AUTO: chamando {cand.call} ({cand.snr:+.0f} dB)", 4000)

    def _process_single(self, text: str, r, slot_idx: int = 0) -> None:
        p = parse_message(text, self.s.my_call)

        # memoria de grid: quase toda estacao aparece antes num CQ com grid
        if p.grid and p.call_from:
            self._grid_cache[p.call_from.upper()] = p.grid.upper()

        was_active = self.engine.state.active
        action = self.engine.on_message(p, snr=int(round(r.snr)), now=self.clock.now(),
                                        auto_reply=self.s.auto_seq)

        # QSO novo iniciado por chamada direta: usa a paridade OPOSTA a do DX.
        # Sem isso transmitiamos no mesmo slot dele e ele nunca nos ouvia --
        # dai a sequencia recomecar e o log repetir o mesmo indicativo.
        if not was_active and self.engine.state.active and self.s.tx_parity == "auto":
            self._tx_parity = tx_parity_for(slot_idx)
            self._update_parity_label()
            if not self.engine.state.dx_grid:
                cached = self._grid_cache.get(self.engine.state.dx_call, "")
                if cached:
                    self.engine.state.dx_grid = cached

        if action.tx_message:
            self._queue(action.tx_message)
        if action.log:
            self._pending_log = True      # efetiva quando a transmissao concluir
        if action.note:
            self.statusBar().showMessage(action.note, 4000)

    # ==================================================================
    # TX
    # ==================================================================
    def _queue(self, message: str) -> None:
        message = message.strip()
        if not message:
            return
        ok, normalized = self.encoder.check_text(message)
        if not ok:
            self.statusBar().showMessage(f"Mensagem invalida para FT8: {message!r}", 6000)
            return
        if normalized != message:
            self.statusBar().showMessage(f"Mensagem normalizada: {normalized}", 3000)
        self.pending_tx = normalized
        self.ed_tx.setText(normalized)
        self._refresh_tx_seq()

    def _queue_manual(self) -> None:
        self._queue(self.ed_tx.text())
        if not self.chk_enable.isChecked():
            self.chk_enable.setChecked(True)

    def _maybe_tx(self) -> None:
        if not self.pending_tx or self._tx_busy or not self.tx_enabled:
            return

        slot = self.clock.slot_seconds
        now = self.clock.now()
        offset = float(self.s.tx_offset_s)

        target_slot, tx_at = next_tx_slot(
            now, slot, offset, self._tx_parity,
            self._last_tx_slot if self._last_tx_slot >= 0 else None)
        if tx_at - now > 0.9:
            return
        if self._decode_busy:
            self.statusBar().showMessage(
                "Decode em andamento - transmissao adiada um slot", 2500)
            return

        message = self.pending_tx
        self._last_tx_slot = target_slot
        try:
            wave = self.encoder.encode(message, float(self.sp_freq.value()))
        except ValueError as exc:
            self.pending_tx = None
            self.statusBar().showMessage(str(exc), 6000)
            return

        self._tx_busy = True
        self.pending_tx = None
        self.engine.state.progress_at = now
        job = TxJob(self.ptt, self.audio, wave, tx_at, self.clock)
        job.started_tx.connect(self._on_tx_started)
        job.finished_tx.connect(self._on_tx_finished)
        self._tx_job = job
        self.ed_tx.setText(message)
        job.start()

    def _on_tx_started(self, _: str) -> None:
        self.cat.paused = True          # RF no ar: nada de polling CAT durante o TX
        if self._tx_job is not None:
            self._tx_env = tx_envelope(self._tx_job.wave, self.audio.cfg.tx_gain)
            self._tx_t0 = time.monotonic()
        self._set_chip(self.lbl_ptt, "PTT TX", "ChipTx")
        self.lbl_qso_state.setStyleSheet(f"color:{C['red']}; letter-spacing:2px;")
        self._refresh_tx_seq()

    def _on_tx_finished(self, ok: bool, err: str) -> None:
        self._tx_busy = False
        self.cat.paused = False
        self._tx_env = None
        self._set_chip(self.lbl_ptt, *self._ptt_idle_label())
        self.lbl_qso_state.setStyleSheet(f"color:{C['accent']}; letter-spacing:2px;")
        if not ok and err:
            self.statusBar().showMessage(f"TX: {err}", 6000)
            self._pending_log = False     # nao loga QSO que nao foi transmitido
            # mesmo com erro a maquina avanca: senao o estado ficaria "ativo"
            # para sempre e o modo AUTO nunca mais chamaria ninguem
            self.engine.state.repeats += 1
            if self.engine.state.repeats > self.engine.max_repeats:
                self.engine.abort()
                self.pending_tx = None
                self.statusBar().showMessage(
                    "TX falhou repetidamente - QSO cancelado, AUTO retomado", 6000)
            else:
                self.pending_tx = self.engine.state.tx_message
            self._refresh_tx_seq()
            return
        if self._pending_log:
            self._pending_log = False
            self._log_qso()

        # a maquina de estados decide se repete; RR73/73 nunca se repetem
        if self.engine.after_tx():
            self.pending_tx = self.engine.state.tx_message
        else:
            self.pending_tx = None
        self._refresh_tx_seq()

    def _tx_toggled(self, on: bool) -> None:
        self.tx_enabled = on
        if not on:
            self.pending_tx = None
            self._select_tx_slot(-1)

    def _halt_tx(self) -> None:
        self.pending_tx = None
        if self._tx_job and self._tx_job.isRunning():
            self._tx_job.cancel()
        self.audio.stop_play()
        try:
            self.ptt.unkey()
        except PttError:
            pass
        self.engine.reset()
        self._select_tx_slot(-1)
        self._set_chip(self.lbl_ptt, *self._ptt_idle_label())
        self.statusBar().showMessage("TX interrompido", 3000)

    def _test_ptt(self) -> None:
        try:
            if not self.ptt.connected:
                self.ptt.open()
            self.ptt.test_pulse(800)
        except PttError as exc:
            QMessageBox.warning(self, "PTT", str(exc))

    # ==================================================================
    # sequenciador
    # ==================================================================
    def _std_messages(self) -> list[str]:
        me = self.s.my_call
        grid = self.s.my_grid
        st = self.engine.state
        dx = st.dx_call
        rpt = fmt_report(st.tx_report)
        if not me:
            return ["", "", "", "", "", ""]
        cq = f"CQ {me} {grid}".strip()
        if not dx:
            return [cq, "", "", "", "", ""]
        return [
            cq,
            f"{dx} {me} {grid}".strip(),
            f"{dx} {me} {rpt}",
            f"{dx} {me} R{rpt}",
            f"{dx} {me} RR73",
            f"{dx} {me} 73",
        ]

    def _refresh_tx_seq(self) -> None:
        msgs = self._std_messages()
        current = (self.ed_tx.text() or "").strip()
        for i, btn in enumerate(self.tx_buttons):
            msg = msgs[i] if i < len(msgs) else ""
            if msg:
                short = msg if len(msg) <= 16 else msg[:15] + "…"
                btn.setText(f"Tx{i + 1}  {short}")
                btn.setEnabled(True)
            else:
                btn.setText(f"Tx{i + 1}")
                btn.setEnabled(False)
            btn.setChecked(bool(msg) and msg == current)

    def _select_tx_slot(self, idx: int) -> None:
        if idx < 0:
            for b in self.tx_buttons:
                b.setChecked(False)
            return
        msgs = self._std_messages()
        if idx >= len(msgs) or not msgs[idx]:
            return
        self.ed_tx.setText(msgs[idx])
        for i, b in enumerate(self.tx_buttons):
            b.setChecked(i == idx)
        self.pending_tx = msgs[idx]
        if not self.chk_enable.isChecked():
            self.chk_enable.setChecked(True)

    # ==================================================================
    # acoes
    # ==================================================================
    def _toggle_auto(self, on: bool) -> None:
        self.s.auto_call_cq = on
        self.s.auto_seq = on or self.s.auto_seq
        try:
            self.s.save()
        except OSError:
            pass
        if on:
            self.chk_enable.setChecked(True)
            self.statusBar().showMessage(
                "AUTO ligado: chamando CQs automaticamente", 5000)
        else:
            self.statusBar().showMessage("AUTO desligado", 3000)

    def _start_cq(self) -> None:
        self._callsign_changed()
        if not self.s.my_call or not self.s.my_grid:
            QMessageBox.information(self, "CQ", "Preencha indicativo e grid antes de chamar CQ.")
            return
        if self.s.tx_parity == "even":
            self._tx_parity = 0
        elif self.s.tx_parity == "odd":
            self._tx_parity = 1
        else:
            self._tx_parity = (self._slot_index() + 1) % 2
        self._update_parity_label()
        self._queue(self.engine.start_cq(now=self.clock.now()))
        self.chk_enable.setChecked(True)

    def _on_decode_activated(self, row: int, _col: int) -> None:
        item = self.tbl.item(row, 4)
        if not item:
            return
        text = item.data(Qt.ItemDataRole.UserRole) or item.text()
        p = parse_message(text, self.s.my_call)
        if not p.call_from or p.call_from.upper() == self.s.my_call:
            return
        if not self.s.my_call or not self.s.my_grid:
            QMessageBox.information(self, "QSO", "Preencha indicativo e grid.")
            return
        self.engine.configure(self.s.my_call, self.s.my_grid, self.s.tx_report)
        if self.s.tx_parity == "auto":
            dx_slot = item.data(Qt.ItemDataRole.UserRole + 1)
            if dx_slot is not None:
                self._tx_parity = tx_parity_for(int(dx_slot))
                self._update_parity_label()
        self._queue(self.engine.call(p.call_from, p.grid, they_cq=p.is_cq,
                                     now=self.clock.now()))
        self.chk_enable.setChecked(True)

    def _export_log(self) -> None:
        dlg = ExportDialog(self.log, self)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.exported_path is None:
            return
        self.statusBar().showMessage(
            f"{dlg.exported_count} QSOs exportados para {dlg.exported_path}", 8000)
        QMessageBox.information(
            self, "Log exportado",
            f"{dlg.exported_count} QSOs gravados em:\n{dlg.exported_path}\n\n"
            "No QRZ: Logbook -> Import/Export Tools -> Import from ADI File.")

    def _clear_log(self) -> None:
        n = len(self.log.records)
        if n == 0:
            QMessageBox.information(self, "Limpar log", "O log ja esta vazio.")
            return
        resp = QMessageBox.question(
            self, "Limpar log",
            f"Isso vai arquivar os {n} QSOs atuais e comecar um log em branco.\n\n"
            "O arquivo NAO e apagado: ele fica na pasta com data e hora no nome "
            "(backup).\n\nDeseja continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if resp != QMessageBox.StandardButton.Yes:
            return
        try:
            backup = self.log.archive()
        except OSError as exc:
            QMessageBox.warning(self, "Limpar log", f"Falha ao arquivar: {exc}")
            return
        self._load_log_table()
        self.chip_qsos.setText("0 QSOs")
        self.statusBar().showMessage(f"Log zerado - backup em {backup.name}", 8000)

    def _open_log_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        folder = self.log.path.parent if self.log.path else None
        if folder is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _log_qso(self) -> None:
        st = self.engine.state
        if not st.dx_call:
            return
        grid = st.dx_grid or self._grid_cache.get(st.dx_call.upper(), "")
        rec = QsoRecord(
            call=st.dx_call,
            grid=grid,
            freq_mhz=float(self.s.dial_mhz),
            mode=self.s.mode,
            rst_sent=fmt_report(st.tx_report),
            rst_rcvd=fmt_report(st.rx_report if st.rx_report is not None else 0),
            qso_date=time.strftime("%Y%m%d", time.gmtime(self.clock.now())),
            time_on=time.strftime("%H%M%S", time.gmtime(self.clock.now())),
            band=band_from_mhz(float(self.s.dial_mhz)),
            my_call=self.s.my_call,
            my_grid=self.s.my_grid,
        )
        if is_recent_duplicate(self.log.records, rec, window_minutes=10.0):
            st.logged = True
            self.statusBar().showMessage(
                f"{rec.call}: QSO repetido em menos de 10 min - nao registrado "
                "(o outro lado provavelmente nao copiou o RR73)", 7000)
            return

        self.log.append(rec)
        st.logged = True
        st.dx_grid = grid
        self.engine.mark_worked(rec.call, self.clock.now())
        self._load_log_table()
        self.chip_qsos.setText(f"{len(self.log.records)} QSOs")
        self.statusBar().showMessage(f"QSO registrado: {rec.call}", 5000)

        # terminou: ou volta a chamar CQ, ou fica livre para o modo AUTO
        if self.s.auto_cq:
            self._tx_parity = (self._slot_index() + 1) % 2
            self._update_parity_label()
            self._queue(self.engine.start_cq(now=self.clock.now()))

    # ==================================================================
    # UI reativa
    # ==================================================================
    def _update_qso_panel(self) -> None:
        st = self.engine.state
        if not st.active:
            self.lbl_qso_state.setText("OCIOSO")
            self.lbl_qso_dx.setText("-")
            self.lbl_qso_meta.setText("")
            if self.s.auto_call_cq and self.tx_enabled:
                txt = (f"AUTO ativo: procurando CQ (SNR >= {self.s.auto_min_snr:.0f} dB"
                       + (", ignorando ja trabalhados" if self.s.auto_skip_worked else "")
                       + (", ignorando CQ DX" if self.s.auto_skip_cq_dx else "") + ")")
            elif self.s.auto_call_cq and not self.tx_enabled:
                txt = "AUTO ligado, mas TX esta desabilitado."
            else:
                txt = "Duplo clique num decode para chamar. CQ inicia a chamada."
            self.lbl_qso_info.setText(txt)
            self.compass.set_bearing(None)
            self._refresh_tx_seq()
            return

        labels = {
            Phase.CQ: "CHAMANDO CQ",
            Phase.CALLING: "CHAMANDO DX",
            Phase.REPORT: "ENVIANDO RELATORIO",
            Phase.FINAL: "FINALIZANDO",
            Phase.DONE: "CONCLUIDO",
        }
        self.lbl_qso_state.setText(labels.get(st.phase, st.phase.value))
        self.lbl_qso_dx.setText(st.dx_call or "CQ")
        self.lbl_qso_meta.setText(f"grid {st.dx_grid or '--'}")

        lines = [f"proxima:  {st.tx_message or '-'}",
                 f"repeticao: {st.repeats}"]
        if st.rx_report is not None:
            lines.append(f"recebido: {fmt_report(st.rx_report)} dB")
        db = distance_bearing(self.s.my_grid, st.dx_grid) if st.dx_grid else None
        if db:
            lines.append(f"distancia: {db[0]:.0f} km   azimute: {db[1]:.0f}° "
                         f"({compass_point(db[1])})")
            self.compass.set_bearing(db[1])
        else:
            self.compass.set_bearing(None)
        self.lbl_qso_info.setText("\n".join(lines))
        self._refresh_tx_seq()

    def _load_log_table(self) -> None:
        self.log.reload()
        rows = self.log.records[-300:]
        self.tbl_log.setRowCount(0)
        for r in reversed(rows):
            i = self.tbl_log.rowCount()
            self.tbl_log.insertRow(i)
            t = r.time_on
            utc = f"{t[0:2]}:{t[2:4]}:{t[4:6]}" if len(t) >= 6 else t
            for c, v in enumerate([utc, r.call, r.grid, r.band, r.rst_sent, r.rst_rcvd]):
                item = QTableWidgetItem(v)
                if c == 1:
                    item.setForeground(QColor(C["accent"]))
                self.tbl_log.setItem(i, c, item)
        if hasattr(self, "chip_qsos"):
            self.chip_qsos.setText(f"{len(self.log.records)} QSOs")
        if hasattr(self, "lbl_log_count"):
            self.lbl_log_count.setText(f"{len(self.log.records)} QSOs no log")
        self._refresh_map()

    def _refresh_band_buttons(self) -> None:
        for name, btn in self.band_buttons.items():
            btn.setChecked(name == self.s.band)

    def _select_band(self, name: str) -> None:
        for band, mhz in BANDS:
            if band == name:
                self.s.band = name
                self.s.dial_mhz = mhz
                self.ed_dial.setText(f"{mhz:.4f}")
                break
        self._refresh_band_buttons()
        self._cat_apply(set_mode=True)

    def _slot_index(self, t: float | None = None) -> int:
        return int(math.floor((self.clock.now() if t is None else t)
                              / self.clock.slot_seconds))

    def _update_parity_label(self) -> None:
        self.lbl_parity.setText("TX: " + parity_name(self._tx_parity))

    def _dial_edited(self) -> None:
        try:
            val = float(self.ed_dial.text().replace(",", "."))
        except ValueError:
            self.ed_dial.setText(f"{self.s.dial_mhz:.4f}")
            return
        if abs(val - round(self.s.dial_mhz, 4)) < 1e-9:
            return                      # nada mudou (o campo mostra 4 casas)
        self.s.dial_mhz = val
        self._cat_apply(set_mode=False)

    def _set_tx_freq(self, hz: float) -> None:
        hz = min(2900.0, max(200.0, float(hz)))
        self.s.tx_offset_hz = hz
        if abs(self.sp_freq.value() - hz) > 0.5:
            self.sp_freq.setValue(hz)
        wf = getattr(self, "waterfall", None)
        sp = getattr(self, "spectrum", None)
        if wf is not None:
            wf.set_tx_freq(hz)
        if sp is not None:
            sp.set_tx_freq(hz)

    def _callsign_changed(self) -> None:
        self.s.my_call = self.ed_call.text().strip().upper()
        self.s.my_grid = self.ed_grid.text().strip().upper()[:6]
        self.engine.configure(self.s.my_call, self.s.my_grid, self.s.tx_report)
        self._refresh_tx_seq()
        self._refresh_map()

    # ==================================================================
    # CAT e mapa
    # ==================================================================
    def _make_ptt(self) -> PttController:
        c = self.s.cat
        if c.enabled and c.ptt_via_cat:
            return CatPtt(self.cat, self.s.ptt)
        return PttController(self.s.ptt)

    def _ptt_idle_label(self) -> tuple[str, str]:
        c = self.s.cat
        if c.enabled and c.ptt_via_cat:
            return "PTT CAT", "ChipOk"
        if self.s.ptt.port:
            return f"PTT {self.s.ptt.port}", "ChipOk"
        return "PTT off", "Chip"

    def _open_rig(self) -> None:
        try:
            self.cat.open()
        except CatError as exc:
            QMessageBox.warning(self, "CAT", str(exc))
        try:
            self.ptt.open()
        except PttError as exc:
            QMessageBox.warning(self, "PTT", str(exc))
        self._set_chip(self.lbl_ptt, *self._ptt_idle_label())
        self._cat_hold_until = 0.0
        self._cat_chip()

    def _cat_chip(self) -> None:
        c = self.cat
        if not self.s.cat.enabled:
            self._set_chip(self.lbl_cat, "CAT: off", "Chip")
        elif not c.connected:
            self._set_chip(self.lbl_cat, "CAT: erro", "ChipErr")
        elif c.healthy:
            self._set_chip(self.lbl_cat, f"CAT {c.freq_hz / 1e6:.4f}", "ChipOk")
        else:
            self._set_chip(self.lbl_cat, "CAT: sem resposta", "ChipErr")
            if c.last_error:
                self.lbl_cat.setToolTip(c.last_error)

    def _cat_poll(self) -> None:
        """Acompanha o VFO do radio: a discagem do app segue o que esta no radio."""
        if not self.s.cat.enabled:
            return
        self._cat_chip()
        c = self.cat
        if not c.healthy or self._tx_busy or time.monotonic() < self._cat_hold_until:
            return
        mhz = c.freq_hz / 1e6
        if abs(mhz - self.s.dial_mhz) < 1e-5:
            return
        self.s.dial_mhz = mhz
        self.ed_dial.setText(f"{mhz:.4f}")
        self.s.band = band_from_mhz(mhz).lower()    # "" fora das bandas conhecidas
        self._refresh_band_buttons()

    def _cat_apply(self, set_mode: bool) -> None:
        """Envia a discagem do app para o radio (e, se pedido, coloca em USB-DATA)."""
        if not (self.s.cat.enabled and self.cat.connected):
            return
        if self._tx_busy or self.cat.keyed:
            self.statusBar().showMessage("CAT: aguarde o fim da transmissao", 3000)
            return
        self._cat_hold_until = time.monotonic() + 1.5
        try:
            self.cat.set_freq(round(self.s.dial_mhz * 1e6))
            if set_mode and self.s.cat.set_mode:
                self.cat.set_mode_data()
        except CatError as exc:
            self.statusBar().showMessage(f"CAT: {exc}", 6000)

    def _build_map_tab(self) -> QWidget:
        self._map_getters = (lambda: self.log.records,
                             lambda: self.s.my_grid,
                             lambda: self.s.my_call)
        self.map_panel = MapPanel(*self._map_getters)
        self.map_panel.detachRequested.connect(self._open_map_window)
        self.map_panel.refresh()
        return self.map_panel

    def _refresh_map(self) -> None:
        if not hasattr(self, "map_panel"):
            return
        self.map_panel.refresh()
        if self._map_win is not None and self._map_win.isVisible():
            self._map_win.panel.refresh()

    def _open_map_window(self) -> None:
        if self._map_win is None:
            self._map_win = MapWindow(*self._map_getters)
        self._map_win.panel.refresh()
        self._map_win.show()
        self._map_win.raise_()
        self._map_win.activateWindow()

    # ==================================================================
    # tema
    # ==================================================================
    def _sty(self, widget, fn) -> None:
        widget.setStyleSheet(fn())
        self._inline.append((widget, fn))

    def _pick_theme(self, name: str) -> None:
        self.s.theme = name
        try:
            self.s.save()
        except OSError:
            pass
        self._apply_theme()

    def _apply_theme(self) -> None:
        self.s.theme = set_theme(self.s.theme)
        css = stylesheet()
        from PySide6.QtWidgets import QApplication

        QApplication.instance().setStyleSheet(css)
        self.setStyleSheet(css)
        for w, fn in self._inline:
            w.setStyleSheet(fn())
        self.lbl_qso_state.setStyleSheet(
            f"color:{C['red' if self._tx_busy else 'accent']}; letter-spacing:2px;")
        for r in range(self.tbl.rowCount()):             # recolore decodes ja listados
            for c in range(self.tbl.columnCount()):
                it = self.tbl.item(r, c)
                if it is None:
                    continue
                key = it.data(Qt.ItemDataRole.UserRole + 2)
                if key:
                    it.setForeground(QColor(C[key]))
                if it.data(Qt.ItemDataRole.UserRole + 3):
                    it.setBackground(QColor(C["row_me"]))
        self._load_log_table()
        if hasattr(self, "map_panel"):
            self.map_panel.restyle()
            if self._map_win is not None:
                self._map_win.panel.restyle()
        for w in self.findChildren(QWidget):
            w.update()
        if self.s.theme in getattr(self, "_theme_acts", {}):
            self._theme_acts[self.s.theme].setChecked(True)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.s, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_settings:
            self.s = dlg.result_settings
            self.engine.configure(self.s.my_call, self.s.my_grid, self.s.tx_report)
            self.ed_call.setText(self.s.my_call)
            self.ed_grid.setText(self.s.my_grid)
            self.log = AdifLog(self.s.ensure_log())
            self._load_log_table()
            self.ptt.close()
            self.cat.close()
            self.cat = CatController(self.s.cat)
            self.ptt = self._make_ptt()
            self._open_rig()
            self._apply_theme()
            self.audio.cfg.tx_gain = self.s.tx_gain
            self._refresh_band_buttons()
            self._sync_auto_button()
            self.statusBar().showMessage("Configuracoes salvas", 4000)
