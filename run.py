#!/usr/bin/env python3
"""Inicia o FT8Desk (compila a lib nativa na primeira execucao)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ft8desk.native import is_frozen, load_library  # noqa: E402

if not is_frozen():
    try:
        load_library()
    except RuntimeError:
        print("Compilando a biblioteca nativa (primeira execucao)...")
        import build_native

        build_native.build()

from ft8desk.app import main  # noqa: E402

raise SystemExit(main())
