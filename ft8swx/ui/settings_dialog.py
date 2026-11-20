"""Dialogo de configuracao."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from ..audio import list_devices
from ..cat import BACKENDS, CatConfig, CatController, CatError
from ..config import Settings
from .theme import C, THEMES
from ..ptt import PttController, PttError, list_serial_ports


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuracoes")
        self.setMinimumWidth(560)
        self.s = settings
        self.result_settings: Settings | None = None

        tabs = QTabWidget()
        tabs.addTab(self._station_tab(), "Estacao")
        tabs.addTab(self._audio_tab(), "Audio")
        tabs.addTab(self._ptt_tab(), "PTT / FTDI")
        tabs.addTab(self._cat_tab(), "CAT / Radio")
        tabs.addTab(self._advanced_tab(), "Avancado")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                               QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    # -- abas ----------------------------------------------------------
    def _station_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.ed_call = QLineEdit(self.s.my_call)
        self.ed_call.setPlaceholderText("PY2ABC")
        self.ed_grid = QLineEdit(self.s.my_grid)
        self.ed_grid.setPlaceholderText("GG66AA")
        self.bt_log = QPushButton("Escolher...")
        self.ed_log = QLineEdit(str(self.s.ensure_log()))
        self.bt_log.clicked.connect(self._pick_log)
        row = QHBoxLayout()
        row.addWidget(self.ed_log)
        row.addWidget(self.bt_log)
        f.addRow("Indicativo:", self.ed_call)
        self.cb_theme = QComboBox()
        for key, (label, _) in THEMES.items():
            self.cb_theme.addItem(label, key)
        self.cb_theme.setCurrentIndex(max(0, self.cb_theme.findData(self.s.theme)))
        f.addRow("Tema:", self.cb_theme)
        f.addRow("Grid locator:", self.ed_grid)
        f.addRow("Arquivo de log (ADIF):", row)
        return w

    def _audio_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.cb_in = QComboBox()
        self.cb_out = QComboBox()
        self.cb_in_rate = QComboBox()
        self.cb_out_rate = QComboBox()
        for r in (12000, 24000, 44100, 48000, 96000):
            self.cb_in_rate.addItem(f"{r} Hz", r)
            self.cb_out_rate.addItem(f"{r} Hz", r)
        self._fill_devices()
        self.sp_gain = QDoubleSpinBox()
        self.sp_gain.setRange(0.05, 1.0)
        self.sp_gain.setSingleStep(0.05)
        self.sp_gain.setValue(self.s.tx_gain)
        f.addRow("Entrada (radio -> PC):", self.cb_in)
        f.addRow("Taxa de entrada:", self.cb_in_rate)
        f.addRow("Saida (PC -> radio):", self.cb_out)
        f.addRow("Taxa de saida:", self.cb_out_rate)
        f.addRow("Ganho de TX:", self.sp_gain)
        return w

    def _fill_devices(self) -> None:
        devs = list_devices()
        self.cb_in.addItem("Padrao do sistema", None)
        self.cb_out.addItem("Padrao do sistema", None)
        for d in devs:
            label = f"[{d['index']}] {d['name']} ({d['hostapi']})"
            if d["in"] > 0:
                self.cb_in.addItem(label, d["index"])
            if d["out"] > 0:
                self.cb_out.addItem(label, d["index"])
        for combo, value in ((self.cb_in, self.s.input_device),
                             (self.cb_out, self.s.output_device)):
            i = combo.findData(value)
            combo.setCurrentIndex(i if i >= 0 else 0)
        for combo, value in ((self.cb_in_rate, self.s.input_rate),
                             (self.cb_out_rate, self.s.output_rate)):
            i = combo.findData(value)
            combo.setCurrentIndex(i if i >= 0 else 0)

    def _ptt_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        box = QGroupBox("Porta serial / cabo FTDI")
        f = QFormLayout(box)
        self.cb_port = QComboBox()
        self.cb_port.addItem("(desligado - usar VOX)", "")
        self._fill_ports()
        self.bt_refresh = QPushButton("Atualizar")
        self.bt_refresh.clicked.connect(self._fill_ports)
        row = QHBoxLayout()
        row.addWidget(self.cb_port)
        row.addWidget(self.bt_refresh)

        self.cb_line = QComboBox()
        for name, val in (("DTR", "DTR"), ("RTS", "RTS"), ("DTR + RTS", "BOTH")):
            self.cb_line.addItem(name, val)
        self.cb_baud = QComboBox()
        for b in (1200, 9600, 19200, 38400, 57600, 115200):
            self.cb_baud.addItem(str(b), b)

        self.chk_invert = QCheckBox("Inverter polaridade (chaveia em nivel alto)")
        self.chk_invert.setChecked(self.s.ptt.invert)
        self.sp_delay = QSpinBox()
        self.sp_delay.setRange(0, 2000)
        self.sp_delay.setSuffix(" ms")
        self.sp_delay.setValue(self.s.ptt.tx_delay_ms)
        self.sp_hang = QSpinBox()
        self.sp_hang.setRange(0, 2000)
        self.sp_hang.setSuffix(" ms")
        self.sp_hang.setValue(self.s.ptt.hang_ms)

        f.addRow("Porta:", row)
        f.addRow("Linha de PTT:", self.cb_line)
        f.addRow("Baud (irrelevante p/ PTT):", self.cb_baud)
        f.addRow("", self.chk_invert)
        f.addRow("Atraso de TX (PTT -> audio):", self.sp_delay)
        f.addRow("Hang time (audio -> PTT off):", self.sp_hang)

        hint = QLabel(
            "Se o radio transmitir ao contrario do esperado, marque "
            "\"Inverter polaridade\". Use \"Testar PTT\" para descobrir: "
            "o radio deve entrar em TX enquanto o botao estiver pressionado."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{C['text_dim']};")

        self.bt_test = QPushButton("Testar PTT (1 s)")
        self.bt_test.clicked.connect(self._test_ptt)

        v.addWidget(box)
        v.addWidget(hint)
        v.addWidget(self.bt_test)
        v.addStretch(1)

        i = self.cb_port.findData(self.s.ptt.port)
        self.cb_port.setCurrentIndex(max(0, i))
        i = self.cb_line.findData(self.s.ptt.line)
        self.cb_line.setCurrentIndex(max(0, i))
        i = self.cb_baud.findData(self.s.ptt.baud)
        self.cb_baud.setCurrentIndex(max(0, i))
        return w

    def _cat_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        c = self.s.cat
        self.chk_cat = QCheckBox("Ativar controle CAT do radio")
        self.chk_cat.setChecked(c.enabled)
        v.addWidget(self.chk_cat)

        box = QGroupBox("Conexao")
        f = QFormLayout(box)
        self.cb_cat_backend = QComboBox()
        for key, label in BACKENDS.items():
            self.cb_cat_backend.addItem(label, key)
        self.cb_cat_backend.setCurrentIndex(max(0, self.cb_cat_backend.findData(c.backend)))
        self.cb_cat_port = QComboBox()
        self.bt_cat_refresh = QPushButton("Atualizar")
        self.bt_cat_refresh.clicked.connect(self._fill_cat_ports)
        prow = QHBoxLayout()
        prow.addWidget(self.cb_cat_port)
        prow.addWidget(self.bt_cat_refresh)
        self.cb_cat_baud = QComboBox()
        for b in (4800, 9600, 19200, 38400, 57600, 115200):
            self.cb_cat_baud.addItem(str(b), b)
        self.cb_cat_baud.setCurrentIndex(max(0, self.cb_cat_baud.findData(c.baud)))
        self.ed_cat_addr = QLineEdit(f"{c.civ_addr:02X}")
        self.ed_cat_addr.setMaximumWidth(60)
        self.ed_cat_addr.setToolTip("Endereco CI-V em hexadecimal. IC-7300: 94, IC-705: A4, IC-7610: 98")
        self.ed_cat_host = QLineEdit(c.host)
        self.sp_cat_tcp = QSpinBox()
        self.sp_cat_tcp.setRange(1, 65535)
        self.sp_cat_tcp.setValue(c.tcp_port)
        self._fill_cat_ports(select=c.port)
        f.addRow("Tipo:", self.cb_cat_backend)
        f.addRow("Porta serial:", prow)
        f.addRow("Baud:", self.cb_cat_baud)
        f.addRow("Endereco CI-V (hex):", self.ed_cat_addr)
        f.addRow("rigctld - host:", self.ed_cat_host)
        f.addRow("rigctld - porta TCP:", self.sp_cat_tcp)
        v.addWidget(box)

        self.chk_cat_mode = QCheckBox("Colocar o radio em USB-DATA ao trocar de banda")
        self.chk_cat_mode.setChecked(c.set_mode)
        self.chk_cat_rts = QCheckBox("Manter RTS ligado na porta CAT (Yaesu: se o menu 'CAT RTS' estiver ENABLE)")
        self.chk_cat_rts.setChecked(c.rts_high)
        self.chk_cat_rts.setToolTip("Alguns radios so respondem com RTS alto. NAO marque em radios "
                                    "cujo RTS chaveia o PTT (ex.: IC-7300 com USB SEND = RTS).")
        self.chk_cat_ptt = QCheckBox("Usar CAT para PTT (em vez de DTR/RTS)")
        self.chk_cat_ptt.setChecked(c.ptt_via_cat)
        v.addWidget(self.chk_cat_mode)
        v.addWidget(self.chk_cat_rts)
        v.addWidget(self.chk_cat_ptt)

        hint = QLabel(
            "Com CAT ativo, a discagem do FT8SWX acompanha o VFO do radio (e vice-versa: "
            "clicar numa banda sintoniza o radio) e o log grava a frequencia real. "
            "Se o seu radio usa a MESMA porta para CAT e PTT por DTR/RTS, marque "
            "\"Usar CAT para PTT\": uma porta serial nao pode ser aberta duas vezes. "
            "Para qualquer radio fora da lista, use o Hamlib (rigctld).")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{C['text_dim']};")
        self.bt_cat_test = QPushButton("Testar CAT (ler frequencia)")
        self.bt_cat_test.clicked.connect(self._test_cat)
        v.addWidget(hint)
        v.addWidget(self.bt_cat_test)
        v.addStretch(1)
        return w

    def _fill_cat_ports(self, *_, select: str | None = None) -> None:
        current = select if select is not None else (
            self.cb_cat_port.currentData() if self.cb_cat_port.count() else "")
        self.cb_cat_port.clear()
        self.cb_cat_port.addItem("(nenhuma)", "")
        for dev, desc in list_serial_ports():
            self.cb_cat_port.addItem(f"{dev} - {desc}", dev)
        i = self.cb_cat_port.findData(current)
        self.cb_cat_port.setCurrentIndex(i if i >= 0 else 0)

    def _collect_cat(self) -> CatConfig:
        try:
            addr = int(self.ed_cat_addr.text().strip() or "94", 16) & 0xFF
        except ValueError:
            addr = 0x94
        return CatConfig(
            enabled=self.chk_cat.isChecked(),
            backend=self.cb_cat_backend.currentData() or "rigctld",
            port=self.cb_cat_port.currentData() or "",
            baud=self.cb_cat_baud.currentData() or 19200,
            host=self.ed_cat_host.text().strip() or "127.0.0.1",
            tcp_port=int(self.sp_cat_tcp.value()),
            civ_addr=addr,
            set_mode=self.chk_cat_mode.isChecked(),
            ptt_via_cat=self.chk_cat_ptt.isChecked(),
            rts_high=self.chk_cat_rts.isChecked(),
            poll_s=self.s.cat.poll_s,
        )

    def _test_cat(self) -> None:
        cfg = self._collect_cat()
        cfg.enabled = True
        # a porta serial so abre uma vez: solta a conexao da janela principal durante o teste
        live = getattr(self.parent(), "cat", None)
        was_live = bool(live and live.connected)
        if was_live:
            live.close()
        ctrl = CatController(cfg)
        try:
            ctrl.open()
            hz = ctrl.read_freq()
            QMessageBox.information(self, "CAT", f"Radio respondeu: {hz / 1e6:.6f} MHz")
        except CatError as exc:
            QMessageBox.warning(self, "CAT", str(exc))
        finally:
            ctrl.close()
            if was_live:
                try:
                    live.open()
                except CatError:
                    pass

    def _fill_ports(self) -> None:
        current = self.cb_port.currentData() if self.cb_port.count() else self.s.ptt.port
        self.cb_port.clear()
        self.cb_port.addItem("(desligado - usar VOX)", "")
        for dev, desc in list_serial_ports():
            self.cb_port.addItem(f"{dev} - {desc}", dev)
        i = self.cb_port.findData(current)
        self.cb_port.setCurrentIndex(i if i >= 0 else 0)

    def _advanced_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.cb_parity = QComboBox()
        self.cb_parity.addItem("Automatico (alterna com o DX)", "auto")
        self.cb_parity.addItem("Sempre em slots pares", "even")
        self.cb_parity.addItem("Sempre em slots impares", "odd")
        i = self.cb_parity.findData(self.s.tx_parity)
        self.cb_parity.setCurrentIndex(max(0, i))
        self.sp_offset = QDoubleSpinBox()
        self.sp_offset.setRange(0.0, 5.0)
        self.sp_offset.setSingleStep(0.1)
        self.sp_offset.setDecimals(2)
        self.sp_offset.setSuffix(" s")
        self.sp_offset.setValue(self.s.tx_offset_s)
        self.sp_report = QSpinBox()
        self.sp_report.setRange(-24, 20)
        self.sp_report.setValue(self.s.tx_report)
        self.sp_repeats = QSpinBox()
        self.sp_repeats.setRange(1, 10)
        self.sp_repeats.setValue(self.s.max_repeats)
        self.chk_ntp = QCheckBox("Sincronizar relogio por NTP ao iniciar")
        self.chk_ntp.setChecked(self.s.ntp_sync)
        self.chk_auto = QCheckBox("Responder automaticamente a quem me chama")
        self.chk_auto.setChecked(self.s.auto_seq)
        self.chk_auto_cq = QCheckBox("Repetir CQ sozinho apos cada QSO")
        self.chk_auto_cq.setChecked(self.s.auto_cq)
        self.chk_hunt = QCheckBox("Modo AUTO: chamar quem esta em CQ")
        self.chk_hunt.setChecked(self.s.auto_call_cq)
        self.sp_auto_snr = QDoubleSpinBox()
        self.sp_auto_snr.setRange(-24.0, 0.0)
        self.sp_auto_snr.setSingleStep(1.0)
        self.sp_auto_snr.setSuffix(" dB")
        self.sp_auto_snr.setValue(self.s.auto_min_snr)
        self.chk_skip_worked = QCheckBox("Nao chamar quem ja esta no log")
        self.chk_skip_worked.setChecked(self.s.auto_skip_worked)
        self.chk_skip_dx = QCheckBox('Ignorar "CQ DX"')
        self.chk_skip_dx.setChecked(self.s.auto_skip_cq_dx)
        f.addRow("Slots de transmissao (par/ impar):", self.cb_parity)
        f.addRow("", QLabel("FT8 exige slots alternados: quem chama usa um,\n"
                            "quem responde usa o outro. Deixe em Automatico."))
        f.addRow("Inicio da TX no slot:", self.sp_offset)
        f.addRow("Relatorio enviado (dB):", self.sp_report)
        f.addRow("Max. repeticoes:", self.sp_repeats)
        f.addRow("", self.chk_ntp)
        f.addRow("", self.chk_auto)
        f.addRow("", self.chk_auto_cq)
        f.addRow("--- modo AUTO ---", QWidget())
        f.addRow("", self.chk_hunt)
        f.addRow("SNR minimo para chamar:", self.sp_auto_snr)
        f.addRow("", self.chk_skip_worked)
        f.addRow("", self.chk_skip_dx)
        return w

    # -- acoes ---------------------------------------------------------
    def _pick_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Log ADIF", self.ed_log.text(),
                                              "ADIF (*.adi *.adif)")
        if path:
            self.ed_log.setText(path)

    def _test_ptt(self) -> None:
        cfg = self._collect_ptt()
        # a janela principal ja mantem a porta aberta; so uma abertura por porta no Windows
        live = getattr(self.parent(), "ptt", None)
        was_live = bool(live is not None and type(live) is PttController and live.connected)
        if was_live:
            live.close()
        ctrl = PttController(cfg)
        try:
            ctrl.open()
            if not ctrl.connected:
                QMessageBox.information(self, "PTT", "Selecione uma porta serial primeiro.")
                return
            ctrl.test_pulse(1000)
        except PttError as exc:
            QMessageBox.warning(self, "PTT", str(exc))
        finally:
            ctrl.close()
            if was_live:
                try:
                    live.open()
                except PttError:
                    pass

    def _collect_ptt(self):
        from ..ptt import PttConfig

        return PttConfig(
            port=self.cb_port.currentData() or "",
            baud=self.cb_baud.currentData() or 38400,
            line=self.cb_line.currentData() or "DTR",
            invert=self.chk_invert.isChecked(),
            tx_delay_ms=self.sp_delay.value(),
            hang_ms=self.sp_hang.value(),
            enabled=bool(self.cb_port.currentData()),
        )

    def _accept(self) -> None:
        cat = self._collect_cat()
        ptt = self._collect_ptt()
        if (cat.enabled and cat.uses_serial and not cat.ptt_via_cat and cat.port
                and cat.port == ptt.port):
            QMessageBox.warning(
                self, "Porta em conflito",
                f"{cat.port} esta selecionada para CAT e para PTT por DTR/RTS. "
                "Uma porta serial nao pode ser aberta duas vezes.\n\n"
                "Marque \"Usar CAT para PTT\" ou escolha outra porta.")
            return
        s = self.s
        s.my_call = self.ed_call.text().strip().upper()
        s.my_grid = self.ed_grid.text().strip().upper()[:6]
        s.log_path = self.ed_log.text().strip()
        s.input_device = self.cb_in.currentData()
        s.output_device = self.cb_out.currentData()
        s.input_rate = self.cb_in_rate.currentData()
        s.output_rate = self.cb_out_rate.currentData()
        s.tx_gain = float(self.sp_gain.value())
        s.ptt = ptt
        s.cat = cat
        s.theme = self.cb_theme.currentData() or "dark"
        s.tx_parity = self.cb_parity.currentData() or "auto"
        s.tx_offset_s = float(self.sp_offset.value())
        s.tx_report = int(self.sp_report.value())
        s.max_repeats = int(self.sp_repeats.value())
        s.ntp_sync = self.chk_ntp.isChecked()
        s.auto_seq = self.chk_auto.isChecked()
        s.auto_cq = self.chk_auto_cq.isChecked()
        s.auto_call_cq = self.chk_hunt.isChecked()
        s.auto_min_snr = float(self.sp_auto_snr.value())
        s.auto_skip_worked = self.chk_skip_worked.isChecked()
        s.auto_skip_cq_dx = self.chk_skip_dx.isChecked()
        self.result_settings = s
        s.save()
        self.accept()
