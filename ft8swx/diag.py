"""Diagnostico do ambiente: `python -m ft8swx.diag`."""

from __future__ import annotations

import platform
import sys
import time


def main() -> int:
    from . import __version__

    print("=" * 62)
    print(f" FT8SWX {__version__} - diagnostico")
    print("=" * 62)
    print(f"Python      : {sys.version.split()[0]} ({platform.system()} {platform.machine()})")

    # --- biblioteca nativa ---
    try:
        from .native import Decoder, SAMPLE_RATE, _lib_filename

        d = Decoder(200.0, 3000.0)
        w = d.encode("CQ PY2ABC GG66", 1200.0)
        print(f"Lib nativa  : OK ({_lib_filename()}) - {w.size} samples de TX")
        import numpy as np

        d.reset()
        n = d.frame_len
        pos = 0
        while pos + n <= w.size:
            d.feed(w[pos:pos + n])
            pos += n
        res = d.decode()
        ok = any(b"CQ PY2ABC GG66" in bytes(r.text) for r in res)
        print(f"Auto-teste  : {'encode/decode OK' if ok else 'FALHOU (decode nao retornou a mensagem)'}")
        d.close()
    except Exception as exc:
        print(f"Lib nativa  : ERRO - {exc}")
        print("              rode: python build_native.py")

    # --- audio ---
    try:
        from .audio import backend_available, list_devices

        ok, err = backend_available()
        if not ok:
            print(f"Audio       : INDISPONIVEL - {err}")
        else:
            devs = list_devices()
            ins = [d for d in devs if d["in"] > 0]
            outs = [d for d in devs if d["out"] > 0]
            print(f"Audio       : {len(ins)} entradas, {len(outs)} saidas")
            for dev in ins[:6]:
                print(f"   in  [{dev['index']:2d}] {dev['name'][:44]:44s} {dev['rate']} Hz")
            for dev in outs[:6]:
                print(f"   out [{dev['index']:2d}] {dev['name'][:44]:44s} {dev['rate']} Hz")
    except Exception as exc:
        print(f"Audio       : ERRO - {exc}")

    # --- portas seriais / PTT ---
    try:
        from .ptt import list_serial_ports

        ports = list_serial_ports()
        print(f"Portas      : {len(ports)} encontrada(s)")
        for port_name, desc in ports:
            print(f"   {port_name:16s} {desc[:44]}")
        if not ports:
            print("   (nenhuma - o cabo FTDI aparece aqui quando plugado)")
    except Exception as exc:
        print(f"Portas      : ERRO - {exc}")

    # --- relogio ---
    try:
        from .clock import SlotClock

        c = SlotClock(15.0)
        st = c.sync_ntp()
        if st.synced:
            print(f"Relogio     : NTP ok, offset {st.offset:+.3f} s")
        else:
            print(f"Relogio     : NTP falhou ({st.error}) - use o relogio do sistema")
        print(f"Hora UTC    : {c.utc_string()}")
    except Exception as exc:
        print(f"Relogio     : ERRO - {exc}")

    # --- config / log ---
    try:
        from .config import Settings, app_dir

        s = Settings.load()
        print(f"Config      : {app_dir() / 'settings.json'}")
        print(f"Indicativo  : {s.my_call or '(nao configurado)'} / {s.my_grid or '-'}")
        print(f"Log         : {s.ensure_log()}")
        print(f"PTT         : {s.ptt.port or 'desligado'} linha={s.ptt.line} "
              f"invert={s.ptt.invert}")
    except Exception as exc:
        print(f"Config      : ERRO - {exc}")

    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
