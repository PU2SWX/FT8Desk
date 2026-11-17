"""Dialogo de exportacao do log em ADIF (QRZ, LoTW, generico)."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from ..adif import AdifLog, filter_records
from ..config import BANDS
from .theme import C


class ExportDialog(QDialog):
    def __init__(self, log: AdifLog, parent=None):
        super().__init__(parent)
        self.log = log
        self.setWindowTitle("Exportar log (ADIF)")
        self.setMinimumWidth(560)
        self.exported_path: Path | None = None
        self.exported_count = 0

        form = QFormLayout()
        form.setSpacing(10)

        # -- destino --
        default_name = time.strftime("ft8swx-%Y%m%d-%H%M.adi")
        base = log.path.parent if log.path else Path.home()
        self.ed_path = QLineEdit(str(base / default_name))
        browse = QPushButton("Escolher...")
        browse.clicked.connect(self._pick_file)
        row = QHBoxLayout()
        row.addWidget(self.ed_path, 1)
        row.addWidget(browse)
        form.addRow("Arquivo:", row)

        # -- formato --
        self.cb_format = QComboBox()
        self.cb_format.addItem("QRZ Logbook / geral  (MODE=FT8)", "qrz")
        self.cb_format.addItem("LoTW (legado)  (MODE=MFSK + SUBMODE=FT8)", "lotw")
        form.addRow("Formato:", self.cb_format)

        # -- filtros --
        self.chk_since = QCheckBox("Somente a partir de")
        self.date_since = QDateEdit(QDate.currentDate().addDays(-1))
        self.date_since.setCalendarPopup(True)
        self.date_since.setDisplayFormat("dd/MM/yyyy")
        self.date_since.setEnabled(False)
        self.chk_since.toggled.connect(self.date_since.setEnabled)
        row2 = QHBoxLayout()
        row2.addWidget(self.chk_since)
        row2.addWidget(self.date_since)
        row2.addStretch(1)
        form.addRow("Data:", row2)

        self.cb_band = QComboBox()
        self.cb_band.addItem("Todas as bandas", "")
        for name, _ in BANDS:
            self.cb_band.addItem(name, name)
        form.addRow("Banda:", self.cb_band)

        self.cb_mode = QComboBox()
        self.cb_mode.addItem("Todos os modos", "")
        self.cb_mode.addItem("FT8", "FT8")
        self.cb_mode.addItem("FT4", "FT4")
        form.addRow("Modo:", self.cb_mode)

        self.chk_dedupe = QCheckBox(
            "Remover duplicados (mesmo indicativo, dia e hora)")
        form.addRow("", self.chk_dedupe)

        self.lbl_preview = QLabel()
        self.lbl_preview.setStyleSheet(f"color:{C['accent']}; font-weight:600;")

        hint = QLabel(
            "O QRZ aceita o arquivo direto em Logbook → Import/Export Tools → "
            "Import from ADI File. Ele exige CALL, QSO_DATE, BAND e MODE em "
            "cada registro — todos incluídos."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{C['text_faint']}; font-size:11px;")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.lbl_preview)
        lay.addWidget(hint)
        lay.addWidget(buttons)

        for sig in (self.cb_format.currentIndexChanged, self.cb_band.currentIndexChanged,
                    self.cb_mode.currentIndexChanged, self.chk_since.toggled,
                    self.chk_dedupe.toggled):
            sig.connect(self._update_preview)
        self.date_since.dateChanged.connect(self._update_preview)
        self._update_preview()

    # -- helpers -------------------------------------------------------
    def _selected(self):
        since = ""
        if self.chk_since.isChecked():
            since = self.date_since.date().toString("yyyyMMdd")
        return filter_records(self.log.records, since=since,
                              band=self.cb_band.currentData() or "",
                              mode=self.cb_mode.currentData() or "",
                              dedupe=self.chk_dedupe.isChecked())

    def _update_preview(self) -> None:
        n = len(self._selected())
        total = len(self.log.records)
        self.lbl_preview.setText(f"{n} de {total} QSOs serao exportados")

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Salvar ADIF", self.ed_path.text(), "ADIF (*.adi *.adif)")
        if path:
            self.ed_path.setText(path)

    def _save(self) -> None:
        recs = self._selected()
        if not recs:
            self.lbl_preview.setText("Nenhum QSO para exportar com esses filtros")
            return
        path = Path(self.ed_path.text().strip())
        if path.suffix.lower() not in (".adi", ".adif"):
            path = path.with_suffix(".adi")
        try:
            n = self.log.export(path, recs, self.cb_format.currentData() or "qrz")
        except OSError as exc:
            self.lbl_preview.setText(f"Falha ao gravar: {exc}")
            return
        self.exported_path = path
        self.exported_count = n
        self.accept()
