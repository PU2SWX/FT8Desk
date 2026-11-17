"""Tema visual do FT8SWX: paleta e folha de estilo (QSS)."""

from __future__ import annotations

# Paleta tipo "painel de instrumento": fundo profundo, acentos contidos
C = {
    "bg": "#0b0e13",
    "panel": "#12161f",
    "panel2": "#181e29",
    "panel3": "#1f2633",
    "border": "#242c3a",
    "border2": "#2f394b",
    "text": "#dbe3ee",
    "text_dim": "#8b97ab",
    "text_faint": "#5d6879",
    "accent": "#19d39b",      # verde FT8 (RX / ok)
    "accent_dim": "#0f7d5d",
    "blue": "#4a9eff",        # informacao / dirigido a mim
    "amber": "#ffb224",       # atencao / CQ DX
    "red": "#ff5d5d",         # TX / erro
    "violet": "#a78bfa",
}

FONT_UI = '"Segoe UI", "Inter", "DejaVu Sans", sans-serif'
FONT_MONO = '"Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace'


def stylesheet() -> str:
    return f"""
* {{
    font-family: {FONT_UI};
    font-size: 12px;
    color: {C['text']};
    selection-background-color: {C['accent_dim']};
    selection-color: #ffffff;
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
    color: #1a0f00;
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
QPushButton:pressed {{ background: #0d1119; }}
QPushButton:disabled {{ color: {C['text_faint']}; border-color: {C['border']}; }}
QPushButton:checked {{
    background: {C['accent_dim']};
    border-color: {C['accent']};
    color: #ffffff;
    font-weight: 600;
}}

QPushButton#Primary {{
    background: {C['accent_dim']};
    border: 1px solid {C['accent']};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: #12a67a; }}
QPushButton#Danger {{
    background: transparent;
    border: 1px solid {C['red']};
    color: {C['red']};
}}
QPushButton#Danger:hover {{ background: #3a1518; }}

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
    color: #ffffff;
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
    color: #04121f;
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
    selection-background-color: #1b3242;
    selection-color: #ffffff;
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
QMenu::item:selected {{ background: {C['accent_dim']}; color: #ffffff; }}

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
