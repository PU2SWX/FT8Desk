"""Testes do PTT: watchdog, nivel de repouso na abertura e pausa do CAT (porta simulada)."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ft8swx.ptt as ptt_mod
from ft8swx.cat import CatConfig, CatController
from ft8swx.ptt import PttConfig, PttController

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
    print("  ok:" if cond else "  FALHOU:", msg)


class FakeSerial:
    """Registra a ordem dos eventos: o que foi ajustado ANTES do open()."""
    instances = []

    def __init__(self):
        self.is_open = False
        self._dtr = None
        self._rts = None
        self.events = []
        FakeSerial.instances.append(self)

    dtr = property(lambda s: s._dtr, lambda s, v: (s.events.append(("dtr", v, s.is_open)), setattr(s, "_dtr", v)))
    rts = property(lambda s: s._rts, lambda s, v: (s.events.append(("rts", v, s.is_open)), setattr(s, "_rts", v)))

    def open(self):
        self.is_open = True
        self.events.append(("open",))

    def close(self):
        self.is_open = False

    in_waiting = 0
    def write(self, data): pass
    def flush(self): pass
    def reset_input_buffer(self): pass
    def read(self, n=1):
        time.sleep(0.01)
        return b""


ptt_mod.serial = type("M", (), {"Serial": FakeSerial})


def test_open_idle_levels():
    print("abertura em nivel de repouso")
    for invert in (False, True):
        FakeSerial.instances.clear()
        c = PttController(PttConfig(port="COM3", line="RTS", invert=invert))
        c.open()
        ser = FakeSerial.instances[0]
        before = [e for e in ser.events[:ser.events.index(("open",))]]
        check(("rts", invert, False) in before and ("dtr", False, False) in before,
              f"invert={invert}: RTS={invert} e DTR=False ajustados antes de abrir")
        check(ser.rts is invert and ser.dtr is False, "estado final de repouso correto")
        c.key()
        check(ser.rts is (not invert), "key() inverte a linha")
        c.unkey()
        check(ser.rts is invert, "unkey() volta ao repouso")
        c.close()


def test_watchdog():
    print("watchdog")
    c = PttController(PttConfig(port="COM3", line="RTS", max_tx_s=0.3))
    c.open()
    ser = FakeSerial.instances[-1]
    c.key()
    check(c.keyed and ser.rts is True, "PTT ligado")
    time.sleep(0.7)
    check(not c.keyed and ser.rts is False, "watchdog soltou o PTT sozinho")

    c2 = PttController(PttConfig(port="COM3", line="DTR", max_tx_s=0.3))
    c2.open()
    s2 = FakeSerial.instances[-1]
    with c2.tx():
        pass
    time.sleep(0.5)
    check(s2.dtr is False and not c2.keyed, "tx() normal libera e nao deixa timer pendente")

    c3 = PttController(PttConfig(port="COM3", line="RTS", max_tx_s=0.3))
    c3.open()
    s3 = FakeSerial.instances[-1]
    c3.key(); time.sleep(0.2); c3.unkey(); c3.key()      # religa: o prazo recomeca
    time.sleep(0.2)
    check(c3.keyed, "religar reinicia o prazo do watchdog")
    time.sleep(0.3)
    check(not c3.keyed, "e o novo prazo tambem expira")

    c4 = PttController(PttConfig(port="COM3", line="RTS", max_tx_s=0))
    c4.open(); c4.key(); time.sleep(0.4)
    check(c4.keyed, "max_tx_s=0 desliga o watchdog")
    c4.close()


class CountBackend:
    def __init__(self):
        self.reads = 0
    def open(self): ...
    def close(self): ...
    def get_freq(self):
        self.reads += 1
        return 7074000.0
    def set_ptt(self, on): ...


def test_cat_pause():
    print("CAT pausa durante o TX")
    be = CountBackend()
    cat = CatController(CatConfig(enabled=True, poll_s=0.25), backend=be)
    cat.open()
    time.sleep(0.6)
    cat.paused = True
    time.sleep(0.3)
    n = be.reads
    time.sleep(0.8)
    check(be.reads == n, "sem leituras CAT com paused=True")
    cat.paused = False
    time.sleep(0.6)
    check(be.reads > n, "leituras retomam depois")
    cat.close()


def test_cat_rts_and_diagnostics():
    print("CAT: RTS e mensagens de diagnostico")
    import ft8swx.cat as cat_mod
    from ft8swx.cat import AsciiBackend, CatError, SerialLink
    cat_mod.serial = ptt_mod.serial
    for rts in (False, True):
        FakeSerial.instances.clear()
        SerialLink("COM4", 38400, rts_high=rts).open()
        ev = FakeSerial.instances[0].events
        check(("rts", rts, False) in ev[:ev.index(("open",))] and ("dtr", False, False) in ev,
              f"rts_high={rts}: RTS={rts} e DTR=False antes de abrir")
    be = AsciiBackend("yaesu", "COM4", 38400, timeout=0.2)
    be.open()
    try:
        be.get_freq()
        check(False, "deveria falhar sem resposta")
    except CatError as exc:
        msg = str(exc)
        check("COM4" in msg and "38400" in msg and "nada" in msg and "CAT RATE" in msg,
              "erro informa porta, baud, o que chegou e a dica do menu: " + msg[:60])


if __name__ == "__main__":
    for fn in (test_open_idle_levels, test_watchdog, test_cat_pause, test_cat_rts_and_diagnostics):
        fn()
    if fails:
        print(f"\n{len(fails)} FALHAS"); raise SystemExit(1)
    print("\nTODOS OS TESTES PASSARAM")
