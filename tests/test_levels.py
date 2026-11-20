"""Testes dos medidores de nivel (dBFS), RMS/pico, clip, release e envelope de TX."""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft8swx.levels import CLIP_DB, FLOOR_DB, LevelMeter, block_levels, tx_envelope

fails = []
def check(c, m):
    if not c: fails.append(m)
    print("  ok:" if c else "  FALHOU:", m)

t = np.arange(12000) / 12000.0
sine = lambda a: (a * np.sin(2 * np.pi * 1500 * t)).astype(np.float32)

r, p = block_levels(np.zeros(100, np.float32))
check(r == FLOOR_DB and p == FLOOR_DB, "silencio fica no piso")
r, p = block_levels(sine(0.5))
check(abs(r - (-9.03)) < 0.1 and abs(p - (-6.02)) < 0.1, f"senoide 0.5: RMS {r:.2f} / pico {p:.2f} dBFS")
r, p = block_levels(sine(1.0))
check(p >= CLIP_DB and abs(r + 3.01) < 0.1, "senoide cheia: pico em 0 dBFS")
check(block_levels(np.array([], np.float32)) == (FLOOR_DB, FLOOR_DB), "bloco vazio")

m = LevelMeter()
m.push(-20, -10, 0.0)
check(m.level == -20 and m.peak == -10 and not m.clip(0.0), "ataque imediato, sem clip")
m.push(FLOOR_DB, FLOOR_DB, 1.0)
check(abs(m.level - (-44)) < 0.1, f"release de 24 dB/s ({m.level:.1f})")
check(m.peak == -10, "pico retido dentro do tempo de hold")
m.push(FLOOR_DB, FLOOR_DB, 3.0)
check(m.peak < -10, f"pico comeca a cair depois do hold ({m.peak:.1f})")
m.push(-5, -0.5, 4.0)
check(m.clip(4.0) and m.clip(5.9) and not m.clip(6.1), "CLIP acende por 2 s e apaga")
for i in range(1, 20): m.decay(6.0 + i)
check(m.level == FLOOR_DB, "decay leva ao piso")

env = tx_envelope(sine(1.0), gain=0.5)
check(len(env) == 20 and all(abs(e[1] - (-6.02)) < 0.2 for e in env), "envelope de TX: 20 trechos de 50 ms, pico -6 dBFS com ganho 0.5")
env = tx_envelope(sine(1.0), gain=3.0)
check(max(e[1] for e in env) <= -0.08, "limitador a 0.99 como no play_12k")
if fails: print(len(fails), "FALHAS"); raise SystemExit(1)
print("\nTODOS OS TESTES PASSARAM")
