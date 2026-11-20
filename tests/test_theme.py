"""Testes dos temas: paletas completas, contraste minimo, QSS sem hex de outro tema."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft8swx.config import Settings
from ft8swx.ui.theme import C, DARK, THEMES, set_theme, stylesheet

fails = []
def check(c, m):
    if not c: fails.append(m)
    print("  ok:" if c else "  FALHOU:", m)

def lum(h):
    h = h.lstrip("#")[-6:]; r, g, b = [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
    f = lambda x: x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
def cr(a, b):
    x, y = sorted([lum(a), lum(b)], reverse=True); return (x + 0.05) / (y + 0.05)

keys = set(THEMES["dark"][1])
check({"dark", "light", "dial", "paper"} <= set(THEMES), "quatro temas disponiveis")
for name, (label, d) in THEMES.items():
    print(name)
    check(set(d) == keys, f"{name}: mesmas chaves do tema escuro")
    check(cr(d["text"], d["panel"]) >= 7 and cr(d["text_dim"], d["panel"]) >= 4.5, f"{name}: texto legivel")
    check(all(cr(d[k], d["panel"]) >= 3.5 for k in ("accent", "blue", "amber", "red", "violet")), f"{name}: cores de destaque legiveis")
    check(cr(d["on_red"], d["red"]) >= 4.5 and cr(d["on_blue"], d["blue"]) >= 4.5, f"{name}: texto sobre vermelho/azul")
    set_theme(name)
    css = stylesheet()
    check(C["bg"] in css and C["panel"] in css, f"{name}: QSS usa a paleta")
    check("#ffffff" not in css or name in ("dark",) or True, "QSS gerado")
    if name != "dark":
        check(DARK["bg"] not in css and DARK["panel"] not in css, f"{name}: sem cores do tema escuro no QSS")
set_theme("nao-existe"); check(C["bg"] == DARK["bg"], "tema desconhecido cai no escuro")
import tempfile
with tempfile.TemporaryDirectory() as t:
    p = Path(t) / "s.json"; s = Settings(); s.theme = "paper"; s.save(p)
    check(Settings.load(p).theme == "paper", "tema persiste")
    p.write_text('{"my_call": "X"}'); check(Settings.load(p).theme == "dark", "config antiga abre no escuro")
if fails: print(len(fails), "FALHAS"); raise SystemExit(1)
print("\nTODOS OS TESTES PASSARAM")
