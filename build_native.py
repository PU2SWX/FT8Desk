#!/usr/bin/env python3
"""
Compila a biblioteca nativa (ft8_shim + ft8_lib) para a plataforma atual.

Uso:
    python build_native.py            # compila
    python build_native.py --clean    # recompila do zero

Procura um compilador nesta ordem:
  1. zig cc   (instale com: pip install ziglang)  -> funciona no Windows sem MSVC
  2. cl       (MSVC, precisa de "x64 Native Tools Command Prompt")
  3. gcc/cc   (MinGW, Linux, macOS)

Saída: ft8desk/native/libft8shim.{dll|so|dylib}
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
NATIVE = HERE / "native"
BUILD = HERE / "build" / "native"


def sources():
    src = [
        NATIVE / "ft8_shim.c",
        NATIVE / "ft8_lib" / "ft8" / "encode.c",
        NATIVE / "ft8_lib" / "ft8" / "decode.c",
        NATIVE / "ft8_lib" / "ft8" / "message.c",
        NATIVE / "ft8_lib" / "ft8" / "crc.c",
        NATIVE / "ft8_lib" / "ft8" / "text.c",
        NATIVE / "ft8_lib" / "ft8" / "constants.c",
        NATIVE / "ft8_lib" / "ft8" / "ldpc.c",
        NATIVE / "ft8_lib" / "common" / "monitor.c",
        NATIVE / "ft8_lib" / "fft" / "kiss_fft.c",
        NATIVE / "ft8_lib" / "fft" / "kiss_fftr.c",
    ]
    missing = [str(s) for s in src if not s.exists()]
    if missing:
        raise SystemExit("Arquivos-fonte ausentes:\n  " + "\n  ".join(missing))
    return [str(s) for s in src]


def lib_name() -> str:
    if sys.platform.startswith("win"):
        return "ft8shim.dll"
    if sys.platform == "darwin":
        return "libft8shim.dylib"
    return "libft8shim.so"


def find_zig() -> str | None:
    exe = shutil.which("zig")
    if exe:
        return exe
    try:
        import ziglang  # pip install ziglang

        cand = Path(ziglang.__file__).parent / ("zig.exe" if os.name == "nt" else "zig")
        if cand.exists():
            return str(cand)
    except Exception:
        pass
    return None


def find_toolchain():
    """Retorna (kind, compiler_cmd_prefix)."""
    zig = find_zig()
    if zig:
        return "zig", [zig, "cc"]
    if os.name == "nt":
        if shutil.which("cl"):
            return "msvc", ["cl"]
        if shutil.which("gcc"):
            return "gcc", ["gcc"]
    else:
        cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if cc:
            return "gcc", [cc]
    raise SystemExit(
        "Nenhum compilador C encontrado.\n"
        "No Windows, a forma mais simples:\n"
        "    pip install ziglang\n"
        "e rode este script de novo."
    )


def build(clean: bool = False) -> Path:
    NATIVE.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    if clean:
        for p in BUILD.glob("*"):
            try:
                p.unlink()
            except OSError:
                pass

    kind, cc = find_toolchain()
    final = NATIVE / lib_name()
    # O workspace e' um filesystem de rede (sem seek). O linker precisa
    # escrever e reposicionar, entao linkamos em disco local e copiamos.
    tmpdir = tempfile.mkdtemp(prefix="ft8build_")
    out = Path(tmpdir) / lib_name()
    srcs = sources()
    inc = f"-I{NATIVE / 'ft8_lib'}"

    if kind == "msvc":
        cmd = cc + ["/nologo", "/O2", "/LD", "/D_CRT_SECURE_NO_WARNINGS", "/DLOG_LEVEL=LOG_ERROR", inc, *srcs, f"/Fe:{out}", "/link", "/FORCE:MULTIPLE"]
    else:
        cmd = cc + ["-O3", "-fPIC", "-shared", "-std=c11", "-D_GNU_SOURCE", "-DLOG_LEVEL=LOG_ERROR", inc, *srcs, "-o", str(out), "-lm"]
        if sys.platform == "darwin":
            cmd += ["-undefined", "dynamic_lookup"]

    print(f"[build] compilador: {kind}")
    print("[build] " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + "\n" + proc.stderr)
        raise SystemExit(f"[build] FALHOU (codigo {proc.returncode})")
    if proc.stderr.strip():
        print(proc.stderr.strip()[:2000])
    shutil.copyfile(out, final)
    shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"[build] OK -> {final}")
    return final


if __name__ == "__main__":
    build(clean="--clean" in sys.argv)
