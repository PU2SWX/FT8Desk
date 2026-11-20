#!/usr/bin/env python3
"""Compila native/portaudio.dll (Windows x64) SEM WDM-KS.

Por que: a PortAudio que vem com o sounddevice inclui o host API WDM-KS e a
consulta de canais via Kernel Streaming (PAWIN_USE_WDMKS_DEVICE_INFO). Com o
driver FlexRadio DAX ativo (SmartSDR aberto), Pa_Initialize() corrompe o heap
(0xC0000374) e o processo morre antes de abrir a janela.

Esta build tem apenas MME, DirectSound e WASAPI - suficiente para DAX, placas
USB e VB-Cable. O sounddevice a encontra via PATH (veja ft8swx/audio.py).

Uso:
    pip install ziglang
    python build_portaudio.py            # baixa a v19.7.0 e compila
"""

from __future__ import annotations

import io
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = "19.7.0"
URL = f"https://codeload.github.com/PortAudio/portaudio/zip/refs/tags/v{VERSION}"
SRC_DIR = ROOT / "build" / "pa" / f"portaudio-{VERSION}"
OUT = ROOT / "native" / "portaudio.dll"

SOURCES = [
    "src/common/pa_allocation.c",
    "src/common/pa_converters.c",
    "src/common/pa_cpuload.c",
    "src/common/pa_debugprint.c",
    "src/common/pa_dither.c",
    "src/common/pa_front.c",
    "src/common/pa_process.c",
    "src/common/pa_ringbuffer.c",
    "src/common/pa_stream.c",
    "src/common/pa_trace.c",
    "src/os/win/pa_win_coinitialize.c",
    "src/os/win/pa_win_hostapis.c",
    "src/os/win/pa_win_util.c",
    "src/os/win/pa_win_waveformat.c",
    "src/hostapi/wmme/pa_win_wmme.c",
    "src/hostapi/dsound/pa_win_ds.c",
    "src/hostapi/dsound/pa_win_ds_dynlink.c",
    "src/hostapi/wasapi/pa_win_wasapi.c",
]

DEFINES = [
    "PA_USE_WMME=1",
    "PA_USE_DS=1",
    "PA_USE_WASAPI=1",
    "PA_USE_WDMKS=0",
    "PA_USE_ASIO=0",
    "PA_USE_SKELETON=0",
    # PAWIN_USE_WDMKS_DEVICE_INFO fica de fora de proposito
    "PAWIN_USE_DIRECTSOUNDFULLDUPLEXCREATE",
    "COBJMACROS",                         # IUnknown_* no mingw
    "_CRT_SECURE_NO_WARNINGS",
    "NDEBUG",
]


def fetch() -> None:
    if (SRC_DIR / "include" / "portaudio.h").exists():
        return
    print(f"Baixando PortAudio v{VERSION}...")
    try:
        data = urllib.request.urlopen(URL, timeout=60).read()
    except urllib.error.URLError as exc:
        # Python no Windows costuma falhar com CERTIFICATE_VERIFY_FAILED (nao usa
        # o repositorio de certificados do sistema). O curl.exe do Windows usa.
        print(f"  urllib falhou ({exc.reason}); tentando com curl...")
        try:
            data = subprocess.run(["curl", "-fsSL", "--max-time", "120", URL],
                                  check=True, capture_output=True).stdout
        except (OSError, subprocess.CalledProcessError) as exc2:
            raise SystemExit(
                f"Nao foi possivel baixar a PortAudio: {exc2}\n"
                f"Baixe manualmente {URL}\n"
                f"e extraia em {SRC_DIR.parent}") from exc2
    SRC_DIR.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(SRC_DIR.parent)


def zig_cmd() -> list[str]:
    try:
        import ziglang  # noqa: F401
    except ImportError:
        raise SystemExit("Instale o compilador portatil:  pip install ziglang")
    return [sys.executable, "-m", "ziglang"]


def build() -> Path:
    fetch()
    cmd = zig_cmd() + [
        "cc", "-target", "x86_64-windows-gnu", "-shared", "-O2", "-w",
        "-o", str(OUT),
        f"-I{SRC_DIR / 'include'}",
        f"-I{SRC_DIR / 'src' / 'common'}",
        f"-I{SRC_DIR / 'src' / 'os' / 'win'}",
    ]
    cmd += [f"-D{d}" for d in DEFINES]
    cmd += [str(SRC_DIR / s) for s in SOURCES]
    cmd += ["-lwinmm", "-lole32", "-luuid", "-lsetupapi"]
    print("Compilando portaudio.dll (MME + DirectSound + WASAPI, sem WDM-KS)...")
    subprocess.run(cmd, check=True, cwd=ROOT)
    for junk in OUT.parent.glob("portaudio.*"):
        if junk.suffix in (".lib", ".pdb"):
            junk.unlink(missing_ok=True)
    print(f"OK: {OUT}")
    return OUT


if __name__ == "__main__":
    build()
