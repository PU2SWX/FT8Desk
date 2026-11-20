"""Tema visual do FT8SWX: paleta e folha de estilo (QSS)."""

from __future__ import annotations

# Paletas. 'dark' e' o padrao; 'C' e' mutado no lugar por set_theme() (quem importou C ve a troca).
THEMES: dict[str, tuple[str, dict[str, str]]] = {
    'dark': ('Escuro (padrao)', {
        'bg': '#0b0e13',
        'panel': '#12161f',
        'panel2': '#181e29',
        'panel3': '#1f2633',
        'border': '#242c3a',
        'border2': '#2f394b',
        'text': '#dbe3ee',
        'text_dim': '#8b97ab',
        'text_faint': '#5d6879',
        'accent': '#19d39b',
        'accent_dim': '#0f7d5d',
        'blue': '#4a9eff',
        'amber': '#ffb224',
        'red': '#ff5d5d',
        'violet': '#a78bfa',
        'on_accent': '#ffffff',
        'on_red': '#1a0f00',
        'on_blue': '#04121f',
        'pressed': '#0d1119',
        'accent_hover': '#12a67a',
        'danger_hover': '#3a1518',
        'sel_bg': '#1b3242',
        'sel_text': '#ffffff',
        'row_me': '#781b3242',
        'map_sea': '#0b0e13',
        'map_land': '#1f2633',
        'map_coast': '#2f394b',
    }),
    'light': ('Claro', {
        'bg': '#eef1f6',
        'panel': '#ffffff',
        'panel2': '#f4f6fa',
        'panel3': '#e6eaf1',
        'border': '#d5dbe6',
        'border2': '#c2cad8',
        'text': '#1b2431',
        'text_dim': '#4f5b6f',
        'text_faint': '#6b778a',
        'accent': '#0a7d5c',
        'accent_dim': '#0b7f5f',
        'blue': '#1a5fc0',
        'amber': '#9a5b00',
        'red': '#c62828',
        'violet': '#6b46d1',
        'on_accent': '#ffffff',
        'on_red': '#ffffff',
        'on_blue': '#ffffff',
        'pressed': '#dfe4ee',
        'accent_hover': '#096b4f',
        'danger_hover': '#fde8e8',
        'sel_bg': '#cfe3f7',
        'sel_text': '#0b1b2b',
        'row_me': '#80bfdcff',
        'map_sea': '#d9e6f2',
        'map_land': '#f6f3ea',
        'map_coast': '#b3bfcc',
    }),
    'dial': ('Dial ambar (painel de radio antigo)', {
        'bg': '#14100b',
        'panel': '#1b1610',
        'panel2': '#221b13',
        'panel3': '#2b2318',
        'border': '#3a2f20',
        'border2': '#4d3f2a',
        'text': '#eadcc0',
        'text_dim': '#a8977a',
        'text_faint': '#7a6d54',
        'accent': '#e8a33d',
        'accent_dim': '#8a5a12',
        'blue': '#7fb8c4',
        'amber': '#f2d16b',
        'red': '#e5654f',
        'violet': '#b79ad6',
        'on_accent': '#fff4dc',
        'on_red': '#1a0a05',
        'on_blue': '#08171b',
        'pressed': '#0e0b07',
        'accent_hover': '#8f5d10',
        'danger_hover': '#3a1a12',
        'sel_bg': '#3a2d18',
        'sel_text': '#fff4dc',
        'row_me': '#783a2d18',
        'map_sea': '#14100b',
        'map_land': '#2b2318',
        'map_coast': '#4d3f2a',
    }),
    'paper': ('Papel (cartao QSL)', {
        'bg': '#f2ead8',
        'panel': '#fbf6e9',
        'panel2': '#f6efdc',
        'panel3': '#ebe2cb',
        'border': '#d8cdb0',
        'border2': '#c4b794',
        'text': '#2a2118',
        'text_dim': '#5e5440',
        'text_faint': '#7d725a',
        'accent': '#1f6f6b',
        'accent_dim': '#1f6f6b',
        'blue': '#24508f',
        'amber': '#8f5a00',
        'red': '#b3261e',
        'violet': '#6b4a8f',
        'on_accent': '#fffaf0',
        'on_red': '#fffaf0',
        'on_blue': '#fffaf0',
        'pressed': '#e2d8bf',
        'accent_hover': '#175754',
        'danger_hover': '#f6d9d4',
        'sel_bg': '#e3d6b4',
        'sel_text': '#2a2118',
        'row_me': '#80c9d8e8',
        'map_sea': '#dde5e0',
        'map_land': '#f7f0dc',
        'map_coast': '#b8aa86',
    }),
}

# O waterfall/espectro ficam sempre escuros: o mapa de cores (preto->azul->amarelo->vermelho)
# so faz sentido sobre fundo escuro.
DARK: dict[str, str] = dict(THEMES["dark"][1])
C: dict[str, str] = dict(DARK)


def set_theme(name: str) -> str:
    if name not in THEMES:
        name = "dark"
    C.clear()
    C.update(THEMES[name][1])
    return name


def fade(key: str, alpha: int):
    """QColor da paleta atual com transparencia (0-255)."""
    from PySide6.QtGui import QColor

    c = QColor(C[key])
    c.setAlpha(alpha)
    return c


FONT_UI = '"Segoe UI", "Inter", "DejaVu Sans", sans-serif'
FONT_MONO = '"Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace'


def stylesheet() -> str:
    return f"""
* {{
    font-family: {FONT_UI};
    font-size: 12px;
    color: {C['text']};
    selection-background-color: {C['accent_dim']};
    selection-color: {C['on_accent']};
}}

QMainWindow, QWidget {{
    background: {C['bg']};
}}

QToolTip {{
    background: {C['panel3']};
    color: {C['text']};
    border: 1px solid {C['border2']};
    padding: 4px 6px;
}}

/* ---------- painel de cabecalho ---------- */
QFrame#Header {{
    background: {C['panel']};
    border: 1px solid {C['border']};
    border-radius: 8px;
}}
QLabel#Logo {{
    font-size: 17px;
    font-weight: 700;
    color: {C['accent']};
    letter-spacing: 1px;
}}
QLabel#LogoSub {{
    font-size: 10px;
    color: {C['text_faint']};
    letter-spacing: 2px;
}}
QLabel#Clock {{
    font-family: {FONT_MONO};
    font-size: 22px;
    font-weight: 600;
    color: {C['text']};
    letter-spacing: 1px;
}}
QLabel#ClockSub {{
    font-size: 10px;
    color: {C['text_faint']};
    letter-spacing: 2px;
}}
QLabel#FieldLabel {{
    font-size: 10px;
    color: {C['text_faint']};
    text-transform: uppercase;
    letter-spacing: 1px;
}}

QLabel {{ background: transparent; }}   /* rotulos nao ganham 'caixa' sobre paineis */

/* ---------- chips ---------- */
QLabel.Chip {{
    font-size: 10px;
    font-family: {FONT_MONO};
    padding: 3px 8px;
    border-radius: 9px;
    background: {C['panel3']};
    color: {C['text_dim']};
    border: 1px solid {C['border2']};
}}
QLabel#ChipOk {{ color: {C['accent']}; border-color: {C['accent_dim']}; }}
QLabel#ChipWarn {{ color: {C['amber']}; }}
QLabel#ChipErr {{ color: {C['red']}; }}
QLabel#ChipTx {{
    color: {C['on_red']};
    background: {C['red']};
    border: 1px solid {C['red']};
    font-weight: 700;
}}

/* ---------- botoes ---------- */
QPushButton {{
    background: {C['panel2']};
    border: 1px solid {C['border2']};
    border-radius: 6px;
    padding: 6px 12px;
    color: {C['text']};
}}
QPushButton:hover {{ background: {C['panel3']}; border-color: {C['text_faint']}; }}
QPushButton:pressed {{ background: {C['pressed']}; }}
QPushButton:disabled {{ color: {C['text_faint']}; border-color: {C['border']}; }}
QPushButton:checked {{
    background: {C['accent_dim']};
    border-color: {C['accent']};
    color: {C['on_accent']};
    font-weight: 600;
}}

QPushButton#Primary {{
    background: {C['accent_dim']};
    border: 1px solid {C['accent']};
    color: {C['on_accent']};
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {C['accent_hover']}; }}
QPushButton#Danger {{
    background: transparent;
    border: 1px solid {C['red']};
    color: {C['red']};
}}
QPushButton#Danger:hover {{ background: {C['danger_hover']}; }}

QPushButton#Band {{
    background: transparent;
    border: 1px solid {C['border']};
    border-radius: 5px;
    padding: 4px 9px;
    font-size: 11px;
    font-family: {FONT_MONO};
    color: {C['text_dim']};
    min-width: 34px;
}}
QPushButton#Band:hover {{ border-color: {C['text_faint']}; color: {C['text']}; }}
QPushButton#Band:checked {{
    background: {C['accent_dim']};
    border-color: {C['accent']};
    color: {C['on_accent']};
}}

QPushButton#TxSeq {{
    font-family: {FONT_MONO};
    font-size: 11px;
    padding: 5px 10px;
    min-width: 76px;
}}
QPushButton#TxSeq:checked {{
    background: {C['blue']};
    border-color: {C['blue']};
    color: {C['on_blue']};
    font-weight: 700;
}}

/* ---------- campos ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {C['panel2']};
    border: 1px solid {C['border2']};
    border-radius: 5px;
    padding: 5px 8px;
    font-family: {FONT_MONO};
    selection-background-color: {C['accent_dim']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {C['accent']};
}}
QLineEdit#Call {{
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 1px;
    color: {C['accent']};
}}
QLineEdit#Grid {{ color: {C['text']}; }}
QComboBox::drop-down {{ border: 0; width: 16px; }}
QComboBox QAbstractItemView {{
    background: {C['panel2']};
    border: 1px solid {C['border2']};
    selection-background-color: {C['accent_dim']};
    outline: 0;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 14px; background: {C['panel3']}; border: 0;
}}

/* ---------- abas ---------- */
QTabWidget::pane {{
    border: 1px solid {C['border']};
    border-radius: 8px;
    background: {C['panel']};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {C['text_faint']};
    padding: 7px 16px;
    border: 0;
    border-bottom: 2px solid transparent;
    font-size: 11px;
    letter-spacing: 1px;
}}
QTabBar::tab:selected {{
    color: {C['text']};
    border-bottom: 2px solid {C['accent']};
}}
QTabBar::tab:hover {{ color: {C['text']}; }}

/* ---------- tabelas ---------- */
QTableWidget {{
    background: {C['panel']};
    alternate-background-color: {C['panel2']};
    border: 0;
    gridline-color: {C['border']};
    font-family: {FONT_MONO};
    font-size: 11px;
    selection-background-color: {C['sel_bg']};
    selection-color: {C['sel_text']};
}}
QTableWidget::item {{ padding: 3px 6px; border: 0; }}
QHeaderView::section {{
    background: {C['panel3']};
    color: {C['text_faint']};
    border: 0;
    border-bottom: 1px solid {C['border2']};
    padding: 5px 6px;
    font-size: 10px;
    font-family: {FONT_UI};
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QTableCornerButton::section {{ background: {C['panel3']}; border: 0; }}

/* ---------- barras ---------- */
QMenuBar {{
    background: {C['panel']};
    border-bottom: 1px solid {C['border']};
    padding: 2px;
}}
QMenuBar::item {{ padding: 5px 12px; background: transparent; border-radius: 5px; }}
QMenuBar::item:selected {{ background: {C['panel3']}; }}
QMenu {{
    background: {C['panel2']};
    border: 1px solid {C['border2']};
    padding: 4px;
}}
QMenu::item {{ padding: 6px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: {C['accent_dim']}; color: {C['on_accent']}; }}

QStatusBar {{
    background: {C['panel']};
    border-top: 1px solid {C['border']};
    color: {C['text_dim']};
}}
QStatusBar::item {{ border: 0; }}

QScrollBar:vertical {{
    background: {C['panel']}; width: 10px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {C['border2']}; border-radius: 5px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {C['text_faint']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: {C['panel']}; height: 10px; }}
QScrollBar::handle:horizontal {{
    background: {C['border2']}; border-radius: 5px; min-width: 24px;
}}

QGroupBox {{
    border: 1px solid {C['border']};
    border-radius: 8px;
    margin-top: 10px;
    padding: 10px 8px 8px 8px;
    background: {C['panel']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: {C['text_faint']};
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QSplitter::handle {{ background: {C['bg']}; width: 6px; height: 6px; }}
QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {C['border2']};
    border-radius: 3px;
    background: {C['panel2']};
}}
QCheckBox::indicator:checked {{
    background: {C['accent']};
    border-color: {C['accent']};
}}
"""


def tint(color: str, alpha: int) -> str:
    """Converte '#rrggbb' + alpha em rgba()."""
    c = color.lstrip("#")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"
