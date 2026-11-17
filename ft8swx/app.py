"""Ponto de entrada da aplicacao."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    except Exception as exc:  # pragma: no cover
        print("PySide6 nao instalado:", exc)
        print("Instale com: pip install PySide6")
        return 1

    from .config import Settings, app_dir
    from .native import load_library

    from .ui.theme import stylesheet

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("FT8SWX")
    app.setOrganizationName("FT8SWX")
    app.setStyle("Fusion")          # base neutra; o QSS define a identidade
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
