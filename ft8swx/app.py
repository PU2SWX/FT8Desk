"""Ponto de entrada da aplicacao."""

from __future__ import annotations

import sys


_crash_file = None


def _enable_faulthandler(folder) -> None:
    """Escreve a pilha Python em crash.log quando uma DLL derruba o processo (segfault/access violation).
    Heap corruption (0xC0000374) e' fast-fail do Windows e NAO passa por aqui: veja o Visualizador de Eventos."""
    global _crash_file
    import faulthandler

    try:
        _crash_file = open(folder / "crash.log", "a", encoding="utf-8")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except Exception:
        pass


def _setup_logging(folder) -> None:
    """Log rotativo em <pasta de dados>/ft8swx.log (PTT, CAT e erros de porta)."""
    import logging
    import logging.handlers

    try:
        h = logging.handlers.RotatingFileHandler(
            folder / "ft8swx.log", maxBytes=200_000, backupCount=2, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger("ft8swx")
        root.setLevel(logging.INFO)
        root.addHandler(h)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    except Exception as exc:  # pragma: no cover
        print("PySide6 nao instalado:", exc)
        print("Instale com: pip install PySide6")
        return 1

    from .config import Settings, app_dir
    from .native import load_library

    from .ui.theme import set_theme, stylesheet

    _setup_logging(app_dir())
    _enable_faulthandler(app_dir())
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("FT8SWX")
    app.setOrganizationName("FT8SWX")
    app.setStyle("Fusion")          # base neutra; o QSS define a identidade
    set_theme(Settings.load().theme)
    app.setStyleSheet(stylesheet())

    try:
        load_library()
    except RuntimeError as exc:
        QMessageBox.critical(
            None, "Biblioteca nativa ausente",
            f"{exc}\n\nRode uma vez:\n    python build_native.py",
        )
        return 2

    try:
        from PySide6.QtGui import QIcon

        from .native import resource_path

        icon = resource_path("native", "ft8swx.png")
        if icon.exists():
            app.setWindowIcon(QIcon(str(icon)))
    except Exception:
        pass

    from .ui.main_window import MainWindow
    from .ui.settings_dialog import SettingsDialog

    settings = Settings.load()
    if not settings.my_call or not settings.my_grid:
        dlg = SettingsDialog(settings)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return 0
        settings = Settings.load()

    win = MainWindow(settings)
    win.show()
    win.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
