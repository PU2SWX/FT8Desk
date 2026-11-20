"""Estresse do decodificador nativo: close() durante decode e encode/check_text concorrentes."""
import sys, threading, time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft8swx.native import Decoder, SAMPLE_RATE

fails = []
def check(c, m):
    if not c: fails.append(m)
    print("  ok:" if c else "  FALHOU:", m)

enc = Decoder(200.0, 3000.0, SAMPLE_RATE, "FT8")
wave = enc.encode("CQ PU2SWX GG66", 1500.0)
slot = np.zeros(SAMPLE_RATE * 15, dtype=np.float32); slot[SAMPLE_RATE // 2: SAMPLE_RATE // 2 + wave.size] = wave * 0.3

def decode_job(d, out):
    try:
        d.reset(); n = d.frame_len; p = 0
        while p + n <= slot.size:
            d.feed(slot[p:p + n]); p += n
        out.append(d.decode())
    except RuntimeError as e:
        out.append(str(e))

print("close() enquanto decodifica (40 rodadas)")
ok = True
for i in range(40):
    d = Decoder(200.0, 3000.0, SAMPLE_RATE, "FT8"); out = []
    t = threading.Thread(target=decode_job, args=(d, out)); t.start()
    time.sleep(0.005 * (i % 8))
    d.close(); t.join(10)
    ok &= (not t.is_alive()) and len(out) == 1
check(ok, "nenhum crash; a thread termina com resultado ou 'Decoder ja foi fechado'")
d = Decoder(); d.close(); d.close()
check(True, "close() duplo e' inofensivo")
try:
    d.decode(); check(False, "decode apos close deveria levantar erro")
except RuntimeError:
    check(True, "uso apos close() levanta RuntimeError (antes: NULL/UAF)")

print("encode + check_text na janela enquanto outra instancia decodifica")
dec = Decoder(200.0, 3000.0, SAMPLE_RATE, "FT8"); out = []
t = threading.Thread(target=lambda: [decode_job(dec, out) for _ in range(3)]); t.start()
n_ok = 0
while t.is_alive():
    ok_txt, _ = enc.check_text("CQ PU2SWX GG66"); n_ok += ok_txt
    w = enc.encode("PU2SWX W1AW -10", 1500.0)
t.join()
check(n_ok > 0 and w.size > 100000 and len(out) == 3 and any(r for r in out if not isinstance(r, str)),
      f"sem crash; {n_ok} validacoes; decode ainda acha a mensagem")
if fails: print(len(fails), "FALHAS"); raise SystemExit(1)
print("\nTODOS OS TESTES PASSARAM")
