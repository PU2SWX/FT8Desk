"""Mapa de conexoes: estacoes do log ligadas a voce por arcos de circulo maximo."""

from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout,
    QWidget,
)

from ..adif import QsoRecord, band_from_mhz
from ..grid import compass_point, grid_to_latlon
from ..mapdata import (
    PERIODS, Link, build_links, great_circle, load_world, since_for_days, summarize,
    valid_grid,
)
from .theme import C

# faixas de distancia -> cor
DIST_STEPS = [(1000.0, C["accent"]), (5000.0, C["blue"]), (10000.0, C["amber"])]
DIST_FAR = C["red"]


def fmt_km(km: float) -> str:
    return f"{km:,.0f}".replace(",", ".") + " km"


def dist_color(km: float) -> QColor:
    for limit, col in DIST_STEPS:
        if km < limit:
            return QColor(col)
    return QColor(DIST_FAR)


def _world_polygons() -> list[QPolygonF]:
    polys = []
    for ring in load_world():
        polys.append(QPolygonF([QPointF(ring[i], -ring[i + 1])
                                for i in range(0, len(ring) - 1, 2)]))
    return polys


class MapWidget(QWidget):
    stationClicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 180)
        self.setMouseTracking(True)
        self._world = _world_polygons()
        self._links: list[Link] = []
        self._arcs: dict[str, list[QPolygonF]] = {}
        self._me: tuple[float, float] | None = None
        self._me_call = ""
        self._cx, self._cy, self._s = 0.0, 10.0, 1.0
        self._drag: QPointF | None = None
        self._moved = False
        self._selected = ""
        self._user_view = False      # True depois de zoom/arrasto manual

    # -- dados ---------------------------------------------------------
    def set_data(self, links: list[Link], my_grid: str, my_call: str = "") -> None:
        self._links = links
        self._me_call = my_call
        self._me = grid_to_latlon(my_grid) if valid_grid(my_grid) else None
        self._arcs = {}
        if self._me:
            for lk in links:
                segs = great_circle(self._me[0], self._me[1], lk.lat, lk.lon)
                self._arcs[lk.call] = [QPolygonF([QPointF(x, -y) for x, y in sg])
                                       for sg in segs]
        if not self._user_view:
            self.fit()
        self.update()

    def select(self, call: str) -> None:
        self._selected = call
        self.update()

    # -- vista ---------------------------------------------------------
    def _min_scale(self) -> float:
        return max(0.5, min(self.width() / 360.0, self.height() / 180.0) * 0.95)

    def fit(self) -> None:
        w, h = max(1, self.width()), max(1, self.height())
        pts: list[tuple[float, float]] = []
        if self._me:
            pts.append((self._me[1], self._me[0]))
        for lk in self._links:
            pts.append((lk.lon, lk.lat))
            for poly in self._arcs.get(lk.call, []):
                pts.extend((p.x(), -p.y()) for p in poly)
        if len(pts) < 2:
            self._cx, self._cy = (pts[0] if pts else (0.0, 10.0))
            self._s = self._min_scale() if not pts else 6.0
        else:
            lons = [p[0] for p in pts]
            lats = [p[1] for p in pts]
            dlon = max(10.0, max(lons) - min(lons))
            dlat = max(6.0, max(lats) - min(lats))
            self._cx = (max(lons) + min(lons)) / 2
            self._cy = (max(lats) + min(lats)) / 2
            self._s = min(w / (dlon * 1.3), h / (dlat * 1.3))
        self._s = min(12.0, max(self._min_scale(), self._s))
        self._user_view = False
        self.update()

    def _to_screen(self, lon: float, lat: float, k: int = 0) -> QPointF:
        return QPointF(self.width() / 2 + (lon + 360 * k - self._cx) * self._s,
                       self.height() / 2 - (lat - self._cy) * self._s)

    def _to_geo(self, p: QPointF) -> tuple[float, float]:
        return (self._cx + (p.x() - self.width() / 2) / self._s,
                self._cy - (p.y() - self.height() / 2) / self._s)

    def _clamp(self) -> None:
        self._cy = max(-85.0, min(85.0, self._cy))
        self._cx = (self._cx + 180.0) % 360.0 - 180.0

    # -- pintura -------------------------------------------------------
    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(C["bg"]))

        world = QTransform()
        world.translate(self.width() / 2, self.height() / 2)
        world.scale(self._s, self._s)
        world.translate(-self._cx, self._cy)

        # fundo: continentes e grade
        p.save()
        p.setTransform(world)
        land_pen = QPen(QColor(C["border2"]), 1)
        land_pen.setCosmetic(True)
        grid_pen = QPen(QColor(C["border"]), 1, Qt.PenStyle.DotLine)
        grid_pen.setCosmetic(True)
        for k in (-1, 0, 1):
            off = 360.0 * k
            p.setPen(grid_pen)
            for lon in range(-180, 181, 30):
                p.drawLine(QPointF(lon + off, -90), QPointF(lon + off, 90))
            if k == 0:
                for lat in range(-60, 61, 30):
                    p.drawLine(QPointF(-540, -lat), QPointF(540, -lat))
            p.setPen(land_pen)
            p.setBrush(QColor(C["panel3"]))
            p.translate(off, 0)
            for poly in self._world:
                p.drawPolygon(poly)
            p.translate(-off, 0)
        p.restore()

        if self._me:
            self._paint_links(p, world)
        else:
            p.setPen(QColor(C["text_dim"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Defina seu grid em Configuracoes para ver as conexoes")
        self._paint_legend(p)
        p.end()

    def _paint_links(self, p: QPainter, world: QTransform) -> None:
        # arcos (transformacao do mundo; linha de 1 px na tela)
        p.save()
        p.setTransform(world)
        order = sorted(self._links, key=lambda x: x.call == self._selected)
        for lk in order:
            col = dist_color(lk.km)
            sel = lk.call == self._selected
            col.setAlpha(255 if sel else 150)
            pen = QPen(col, 2.6 if sel else 1.3)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for k in (-1, 0, 1):
                p.translate(360.0 * k, 0)
                for poly in self._arcs.get(lk.call, []):
                    p.drawPolyline(poly)
                p.translate(-360.0 * k, 0)
        p.restore()

        # estacoes e rotulos (tamanho fixo em pixels)
        font = QFont(p.font())
        font.setPointSizeF(8.0)
        p.setFont(font)
        fm = p.fontMetrics()
        many = len(self._links) > 25
        for rank, lk in enumerate(self._links):          # ja vem do mais longe ao mais perto
            sel = lk.call == self._selected
            for k in (-1, 0, 1):
                pt = self._to_screen(lk.lon, lk.lat, k)
                if not (-40 <= pt.x() <= self.width() + 40 and -20 <= pt.y() <= self.height() + 20):
                    continue
                col = dist_color(lk.km)
                p.setPen(QPen(QColor(C["bg"]), 1.5))
                p.setBrush(col)
                p.drawEllipse(pt, 5.0 if sel else 3.5, 5.0 if sel else 3.5)
                if sel or not many or rank < 5:
                    text = f"{lk.call}  {fmt_km(lk.km)}"
                    r = QRectF(pt.x() + 7, pt.y() - fm.height() / 2 - 1,
                               fm.horizontalAdvance(text) + 8, fm.height() + 2)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(11, 14, 19, 200))
                    p.drawRoundedRect(r, 3, 3)
                    p.setPen(QColor(C["text"]))
                    p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

        # minha estacao
        for k in (-1, 0, 1):
            pt = self._to_screen(self._me[1], self._me[0], k)
            if not (-40 <= pt.x() <= self.width() + 40):
                continue
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.setBrush(QColor(C["violet"]))
            p.drawEllipse(pt, 6.0, 6.0)
            if self._me_call:
                p.setPen(QColor("#ffffff"))
                p.drawText(QPointF(pt.x() + 9, pt.y() - 8), self._me_call)

    def _paint_legend(self, p: QPainter) -> None:
        font = QFont(p.font())
        font.setPointSizeF(8.0)
        p.setFont(font)
        items = [("< 1.000 km", C["accent"]), ("1.000-5.000", C["blue"]),
                 ("5.000-10.000", C["amber"]), ("> 10.000 km", C["red"])]
        x, y = 8, self.height() - 10
        for label, col in items:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(col))
            p.drawEllipse(QPointF(x + 4, y - 4), 3.5, 3.5)
            p.setPen(QColor(C["text_dim"]))
            p.drawText(QPointF(x + 12, y), label)
            x += p.fontMetrics().horizontalAdvance(label) + 24

    # -- interacao -----------------------------------------------------
    def _nearest(self, pos: QPointF, radius: float = 10.0) -> Link | None:
        best, best_d = None, radius
        for lk in self._links:
            for k in (-1, 0, 1):
                pt = self._to_screen(lk.lon, lk.lat, k)
                d = math.hypot(pt.x() - pos.x(), pt.y() - pos.y())
                if d < best_d:
                    best, best_d = lk, d
        return best

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag = ev.position()
            self._moved = False

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._drag is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            d = ev.position() - self._drag
            if abs(d.x()) + abs(d.y()) > 3:
                self._moved = True
            if self._moved:
                self._user_view = True
                self._cx -= d.x() / self._s
                self._cy += d.y() / self._s
                self._drag = ev.position()
                self._clamp()
                self.update()
            return
        lk = self._nearest(ev.position())
        if lk is None:
            QToolTip.hideText()
            return
        txt = (f"{lk.call}  [{lk.grid}]\n{fmt_km(lk.km)}  -  {lk.bearing:.0f}° "
               f"{compass_point(lk.bearing)}\n{lk.qsos} QSO(s)  {', '.join(lk.bands)}\n"
               "(distancia ate o centro do grid)")
        QToolTip.showText(ev.globalPosition().toPoint(), txt, self)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton and not self._moved:
            lk = self._nearest(ev.position())
            if lk is not None:
                self._selected = lk.call
                self.stationClicked.emit(lk.call)
                self.update()
        self._drag = None

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        self.fit()

    def wheelEvent(self, ev) -> None:  # noqa: N802
        steps = ev.angleDelta().y() / 120.0
        if steps == 0:
            return
        self._user_view = True
        lon, lat = self._to_geo(ev.position())
        self._s = min(60.0, max(self._min_scale(), self._s * (1.25 ** steps)))
        self._cx = lon - (ev.position().x() - self.width() / 2) / self._s
        self._cy = lat + (ev.position().y() - self.height() / 2) / self._s
        self._clamp()
        self.update()

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        if not self._user_view:
            self.fit()


class MapPanel(QWidget):
    """Mapa + filtros + estatisticas + tabela ordenada por distancia."""

    detachRequested = Signal()

    def __init__(self, get_records: Callable[[], list[QsoRecord]],
                 get_my_grid: Callable[[], str], get_my_call: Callable[[], str],
                 detachable: bool = True, parent=None):
        super().__init__(parent)
        self._get_records = get_records
        self._get_grid = get_my_grid
        self._get_call = get_my_call
        self._links: list[Link] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        bar = QHBoxLayout()
        self.cb_band = QComboBox()
        self.cb_band.addItem("Todas as bandas", "")
        self.cb_period = QComboBox()
        for name, days in PERIODS:
            self.cb_period.addItem(name, days)
        self.cb_band.currentIndexChanged.connect(self._filter_changed)
        self.cb_period.currentIndexChanged.connect(self._filter_changed)
        self.bt_fit = QPushButton("Ajustar")
        self.bt_fit.setToolTip("Enquadrar todas as conexoes (ou duplo clique no mapa)")
        self.bt_save = QPushButton("Salvar imagem...")
        bar.addWidget(self.cb_band)
        bar.addWidget(self.cb_period)
        bar.addWidget(self.bt_fit)
        bar.addWidget(self.bt_save)
        if detachable:
            self.bt_win = QPushButton("Janela")
            self.bt_win.setToolTip("Abrir o mapa em uma janela maior")
            self.bt_win.clicked.connect(self.detachRequested)
            bar.addWidget(self.bt_win)
        bar.addStretch(1)
        v.addLayout(bar)

        self.lbl_stats = QLabel("")
        self.lbl_stats.setWordWrap(True)
        self.lbl_stats.setStyleSheet(f"color:{C['text_dim']};")
        v.addWidget(self.lbl_stats)

        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        self.map = MapWidget()
        split.addWidget(self.map)
        self.tbl = QTableWidget(0, 7)
        self.tbl.setHorizontalHeaderLabels(
            ["Indicativo", "Grid", "Dist.", "Az.", "QSOs", "Bandas", "UTC"])
        hdr = self.tbl.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.verticalHeader().setDefaultSectionSize(21)
        self.tbl.setShowGrid(False)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        split.addWidget(self.tbl)
        split.setSizes([360, 160])
        v.addWidget(split, 1)

        self.bt_fit.clicked.connect(self.map.fit)
        self.bt_save.clicked.connect(self._save_image)
        self.tbl.itemSelectionChanged.connect(self._row_selected)
        self.map.stationClicked.connect(self._select_call)

    # -- dados ---------------------------------------------------------
    def _filter_changed(self) -> None:
        self.map._user_view = False
        self.refresh()

    def refresh(self) -> None:
        records = self._get_records()
        self._refill_bands(records)
        band = self.cb_band.currentData() or ""
        since = since_for_days(int(self.cb_period.currentData() or 0))
        grid = self._get_grid()
        links, skipped = build_links(records, grid, band=band, since=since)
        self._links = links
        self.map.set_data(links, grid, self._get_call())
        self._fill_table(links)
        if not valid_grid(grid):
            self.lbl_stats.setText("Defina seu grid em Estacao > Configuracoes.")
            return
        sm = summarize(links)
        if not links:
            txt = "Nenhuma conexao com grid no filtro atual."
        else:
            far = sm["farthest"]
            txt = (f"{sm['stations']} estacoes ({sm['qsos']} QSOs)  -  "
                   f"mais distante: {far.call} {fmt_km(far.km)}  -  "
                   f"media {fmt_km(sm['avg_km'])}")
        if skipped:
            txt += f"  -  {skipped} QSO(s) sem grid ignorados"
        self.lbl_stats.setText(txt)

    def _refill_bands(self, records: list[QsoRecord]) -> None:
        present = sorted({(r.band or band_from_mhz(r.freq_mhz)).upper()
                          for r in records if (r.band or band_from_mhz(r.freq_mhz))},
                         key=lambda b: (len(b), b))
        have = [self.cb_band.itemData(i) for i in range(1, self.cb_band.count())]
        if have == present:
            return
        cur = self.cb_band.currentData() or ""
        self.cb_band.blockSignals(True)
        self.cb_band.clear()
        self.cb_band.addItem("Todas as bandas", "")
        for b in present:
            self.cb_band.addItem(b, b)
        i = self.cb_band.findData(cur)
        self.cb_band.setCurrentIndex(max(0, i))
        self.cb_band.blockSignals(False)

    def _fill_table(self, links: list[Link]) -> None:
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)
        for lk in links:
            i = self.tbl.rowCount()
            self.tbl.insertRow(i)
            last = lk.last.split()
            t = last[1] if len(last) > 1 else ""
            when = (f"{last[0][6:8]}/{last[0][4:6]} {t[0:2]}:{t[2:4]}"
                    if last and len(last[0]) == 8 and len(t) >= 4 else lk.last)
            vals = [lk.call, lk.grid, fmt_km(lk.km),
                    f"{lk.bearing:.0f}° {compass_point(lk.bearing)}",
                    str(lk.qsos), ", ".join(lk.bands), when]
            for c, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if c == 0:
                    item.setForeground(QColor(C["accent"]))
                    item.setData(Qt.ItemDataRole.UserRole, lk.call)
                if c == 2:
                    item.setForeground(dist_color(lk.km))
                self.tbl.setItem(i, c, item)
        self.tbl.blockSignals(False)

    # -- selecao -------------------------------------------------------
    def _row_selected(self) -> None:
        rows = self.tbl.selectionModel().selectedRows()
        if rows:
            item = self.tbl.item(rows[0].row(), 0)
            self.map.select(item.data(Qt.ItemDataRole.UserRole) if item else "")

    def _select_call(self, call: str) -> None:
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            if it and it.data(Qt.ItemDataRole.UserRole) == call:
                self.tbl.blockSignals(True)
                self.tbl.selectRow(r)
                self.tbl.blockSignals(False)
                self.tbl.scrollToItem(it)
                break

    def _save_image(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Salvar mapa", "mapa-ft8swx.png",
                                              "PNG (*.png)")
        if path:
            self.map.grab().save(path, "PNG")


class MapWindow(QWidget):
    """Janela independente com o mesmo painel (para ver o mapa em tela maior)."""

    def __init__(self, get_records, get_my_grid, get_my_call, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("FT8SWX - Mapa de conexoes")
        self.resize(1000, 680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.panel = MapPanel(get_records, get_my_grid, get_my_call, detachable=False)
        lay.addWidget(self.panel)
