"""Testes do CAT e do mapa (sem Qt e sem hardware: radios e portas simulados)."""

import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ft8swx.adif import QsoRecord
from ft8swx.cat import (AsciiBackend, CatConfig, CatController, CatError, CatPtt,
                         IcomBackend, RigctldBackend)
from ft8swx.config import Settings
from ft8swx.mapdata import (build_links, great_circle, load_world, since_for_days,
                             summarize, valid_grid)
from ft8swx.ptt import PttConfig, PttError

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print("  FALHOU:", msg)
    else:
        print("  ok:", msg)


# ----------------------------------------------------------------------
# radios simulados
# ----------------------------------------------------------------------
class FakeRigctld:
    """Servidor TCP minimo com o protocolo de texto do rigctld."""

    def __init__(self):
        self.freq = 14074000
        self.mode = ""
        self.ptt = 0
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(2)
        self.port = self.srv.getsockname()[1]
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _run(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            f = c.makefile("rwb")
            for raw in f:
                line = raw.decode().strip()
                if line == "f":
                    out = f"{self.freq}\n"
                elif line.startswith("F "):
                    self.freq = int(line.split()[1])
                    out = "RPRT 0\n"
                elif line.startswith("M "):
                    self.mode = line.split()[1]
                    out = "RPRT 0\n"
                elif line.startswith("T "):
                    self.ptt = int(line.split()[1])
                    out = "RPRT 0\n"
                else:
                    out = "RPRT -1\n"
                f.write(out.encode())
                f.flush()

    def stop(self):
        self.srv.close()


class FakeLink:
    """Enlace serial falso: um `handler(bytes) -> bytes` gera a resposta ao escrever."""

    def __init__(self, handler):
        self.handler = handler
        self.rx = bytearray()
        self.written = []

    def open(self): ...
    def close(self): ...

    def flush_input(self):
        self.rx.clear()

    def write(self, data):
        self.written.append(bytes(data))
        self.rx += self.handler(bytes(data))

    def read_until(self, term, timeout):
        i = self.rx.find(term)
        if i < 0:
            time.sleep(0.01)
            out = bytes(self.rx)
            self.rx.clear()
            return out
        out = bytes(self.rx[:i + len(term)])
        del self.rx[:i + len(term)]
        return out


def make_icom_radio(addr=0x94, freq=14074000):
    state = {"freq": freq, "ptt": 0, "mode": None, "data": None, "noise": True}

    def handler(frame):
        dst, src, payload = frame[2], frame[3], frame[4:-1]
        assert dst == addr and src == 0xE0, "quadro mal formado"
        out = bytearray(frame)                                   # eco do comando
        if state["noise"]:
            out += b"\xfe\xfe\x00" + bytes([addr]) + b"\x00" + IcomBackend.encode_freq(7074000) + b"\xfd"
        reply = None
        if payload[:1] == b"\x03":
            reply = b"\x03" + IcomBackend.encode_freq(state["freq"])
        elif payload[:1] == b"\x05":
            state["freq"] = int(IcomBackend.decode_freq(payload[1:6]))
            reply = b"\xfb"
        elif payload[:1] == b"\x06":
            state["mode"] = payload[1]
            reply = b"\xfb"
        elif payload[:2] == b"\x1a\x06":
            state["data"] = payload[2]
            reply = b"\xfb"
        elif payload[:2] == b"\x1c\x00":
            state["ptt"] = payload[2]
            reply = b"\xfb"
        else:
            reply = b"\xfa"
        out += b"\xfe\xfe\xe0" + bytes([addr]) + reply + b"\xfd"
        return bytes(out)

    return state, FakeLink(handler)


def make_ascii_radio(style, freq=14074000):
    digits = 11 if style == "kenwood" else 9
    state = {"freq": freq, "ptt": 0, "cmds": []}

    def handler(data):
        out = ""
        for cmd in data.decode().split(";"):
            if not cmd:
                continue
            state["cmds"].append(cmd)
            if cmd == "FA":
                out += f"FA{state['freq']:0{digits}d};"
            elif cmd.startswith("FA"):
                assert len(cmd) == 2 + digits, f"largura errada: {cmd}"
                state["freq"] = int(cmd[2:])
            elif cmd in ("TX1", "TX0", "RX", "MD0C", "MD2", "DA1"):
                state["ptt"] = 1 if cmd == "TX1" else 0 if cmd in ("TX0", "RX") else state["ptt"]
            else:
                out += "?;"
        return out.encode()

    return state, FakeLink(handler)


# ----------------------------------------------------------------------
def test_icom():
    print("Icom CI-V")
    check(IcomBackend.encode_freq(14074000) == bytes([0x00, 0x40, 0x07, 0x14, 0x00]),
          "BCD de 14.074 MHz")
    check(IcomBackend.decode_freq(IcomBackend.encode_freq(144174000)) == 144174000.0,
          "ida e volta em 144.174 MHz")
    st, link = make_icom_radio()
    be = IcomBackend("", 19200, 0x94, link=link, timeout=0.5)
    be.open()
    check(be.get_freq() == 14074000.0, "le frequencia ignorando eco e mensagem 'transceive'")
    be.set_freq(7074000)
    check(st["freq"] == 7074000, "ajusta frequencia")
    be.set_mode_data()
    check(st["mode"] == 0x01 and st["data"] == 0x01, "USB + DATA ligado")
    be.set_ptt(True)
    check(st["ptt"] == 1, "PTT on")
    be.set_ptt(False)
    check(st["ptt"] == 0, "PTT off")
    # radio mudo
    silent = FakeLink(lambda d: b"")
    be2 = IcomBackend("", 19200, 0x94, link=silent, timeout=0.15)
    try:
        be2.get_freq()
        check(False, "radio mudo deveria dar CatError")
    except CatError:
        check(True, "radio mudo -> CatError")


def test_ascii():
    print("Kenwood / Yaesu ASCII")
    for style, digits in (("kenwood", 11), ("yaesu", 9)):
        st, link = make_ascii_radio(style)
        be = AsciiBackend(style, "", 38400, link=link, timeout=0.5)
        be.open()
        check(be.get_freq() == 14074000.0, f"{style}: le frequencia")
        be.set_freq(21074000)
        check(st["freq"] == 21074000, f"{style}: FA com {digits} digitos")
        be.set_mode_data()
        be.set_ptt(True)
        check(st["ptt"] == 1, f"{style}: PTT on")
        be.set_ptt(False)
        check(st["ptt"] == 0, f"{style}: PTT off")
    st, link = make_ascii_radio("yaesu")
    be = AsciiBackend("yaesu", "", 38400, link=link, timeout=0.5)
    be.set_mode_data()
    check("MD0C" in st["cmds"], "yaesu: DATA-USB (MD0C)")
    broken = FakeLink(lambda d: b"?;")
    try:
        AsciiBackend("kenwood", "", 9600, link=broken, timeout=0.3).get_freq()
        check(False, "'?;' deveria dar CatError")
    except CatError:
        check(True, "'?;' -> CatError")


def test_rigctld():
    print("Hamlib rigctld")
    srv = FakeRigctld()
    try:
        be = RigctldBackend("127.0.0.1", srv.port)
        be.open()
        check(be.get_freq() == 14074000.0, "le frequencia")
        be.set_freq(10136000)
        check(srv.freq == 10136000, "ajusta frequencia")
        be.set_mode_data()
        check(srv.mode == "PKTUSB", "modo PKTUSB")
        be.set_ptt(True)
        check(srv.ptt == 1, "PTT on")
        be.set_ptt(False)
        be.close()
        try:
            RigctldBackend("127.0.0.1", 1).open()
            check(False, "porta fechada deveria dar CatError")
        except CatError:
            check(True, "sem servidor -> CatError")
    finally:
        srv.stop()


def test_controller():
    print("CatController + CatPtt")
    srv = FakeRigctld()
    try:
        cfg = CatConfig(enabled=True, backend="rigctld", host="127.0.0.1",
                        tcp_port=srv.port, poll_s=0.25)
        cat = CatController(cfg)
        cat.open()
        t0 = time.time()
        while cat.freq_hz is None and time.time() - t0 < 3:
            time.sleep(0.05)
        check(cat.freq_hz == 14074000.0 and cat.healthy, "thread de leitura obtem a frequencia")
        cat.set_freq(18100000)
        check(srv.freq == 18100000 and cat.freq_hz == 18100000.0, "set_freq atualiza radio e cache")

        ptt = CatPtt(cat, PttConfig(tx_delay_ms=0, hang_ms=0))
        check(ptt.connected, "CatPtt conectado")
        with ptt.tx():
            check(srv.ptt == 1 and cat.keyed, "dentro de tx(): radio em TX")
            stamp = cat.freq_stamp
            time.sleep(0.6)
            check(cat.freq_stamp == stamp, "leitura de frequencia pausa durante o TX")
        check(srv.ptt == 0 and not cat.keyed, "saiu de tx(): radio em RX")
        cat.close()
        check(not cat.connected, "close encerra a thread")
    finally:
        srv.stop()

    # PTT por CAT chaveado e a conexao cai: PttError, nao excecao crua
    srv = FakeRigctld()
    cfg = CatConfig(enabled=True, tcp_port=srv.port, poll_s=0.25)
    cat = CatController(cfg)
    cat.open()
    srv.stop()
    cat._be._sock.close()
    ptt = CatPtt(cat, PttConfig())
    try:
        ptt.key()
        check(False, "key() sem radio deveria dar PttError")
    except PttError:
        check(True, "key() com CAT fora do ar -> PttError")
    check(not cat.keyed, "flag keyed nao fica presa")
    cat.close()

    # desligado: open() nao faz nada
    off = CatController(CatConfig(enabled=False))
    off.open()
    check(not off.connected, "CAT desativado nao abre nada")


def test_settings():
    print("persistencia")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "settings.json"
        s = Settings(my_call="PU2SWX", my_grid="GG66TL")
        s.cat = CatConfig(enabled=True, backend="icom", port="COM5", baud=115200,
                          civ_addr=0xA4, ptt_via_cat=True)
        s.save(p)
        r = Settings.load(p)
        check(r.cat.backend == "icom" and r.cat.civ_addr == 0xA4 and r.cat.ptt_via_cat
              and r.cat.port == "COM5" and r.cat.baud == 115200, "CAT sobrevive a salvar/carregar")
        # settings.json antigo (sem 'cat') continua abrindo
        p.write_text('{"my_call": "PY2ABC", "my_grid": "GG66", "ptt": {"port": "COM3"}}')
        old = Settings.load(p)
        check(old.my_call == "PY2ABC" and old.ptt.port == "COM3" and not old.cat.enabled,
              "config antiga sem CAT carrega com defaults")


# ----------------------------------------------------------------------
def rec(call, grid, band="20M", date="20261110", t="120000"):
    return QsoRecord(call=call, grid=grid, band=band, qso_date=date, time_on=t)


def test_map():
    print("mapa")
    check(valid_grid("GG66TL") and valid_grid("jo31") and not valid_grid("ZZ99")
          and not valid_grid("") and not valid_grid("GG6"), "validacao de grid")

    me = "GG66TL"
    recs = [
        rec("DL1ABC", "JO31"),
        rec("W1AW", "FN31", band="40M", date="20261112"),
        rec("PY2XYZ", "GG66"),
        rec("DL1ABC", "JO31", band="40M", date="20261113", t="080000"),   # repetido em outra banda
        rec("SEMGRID", ""),
        rec("RUIM", "ZZ99"),
    ]
    links, skipped = build_links(recs, me)
    check(skipped == 2, f"QSOs sem grid valido ignorados ({skipped})")
    check([x.call for x in links] == sorted([x.call for x in links],
          key=lambda c: -next(l.km for l in links if l.call == c)), "ordenado do mais longe ao mais perto")
    check(len(links) == 3, "um item por indicativo")
    dl = next(x for x in links if x.call == "DL1ABC")
    check(dl.qsos == 2 and dl.bands == ["20M", "40M"], "QSOs repetidos viram contagem + bandas")
    check(dl.last == "20261113 080000", "guarda o QSO mais recente")
    check(9000 < dl.km < 11000, f"Poa -> Alemanha ~ {dl.km:.0f} km")
    py = next(x for x in links if x.call == "PY2XYZ")
    check(py.km < 100, f"mesmo grid -> perto ({py.km:.0f} km)")

    l40, _ = build_links(recs, me, band="40M")
    check({x.call for x in l40} == {"W1AW", "DL1ABC"}, "filtro de banda")
    lnew, _ = build_links(recs, me, since="20261112")
    check({x.call for x in lnew} == {"W1AW", "DL1ABC"}, "filtro de periodo")
    check(build_links(recs, "")[0] == [], "sem meu grid nao ha mapa")
    s = summarize(links)
    check(s["stations"] == 3 and s["qsos"] == 4 and s["farthest"] is links[0], "resumo")
    check(since_for_days(0) == "" and len(since_for_days(7)) == 8, "periodos")

    # grande circulo
    segs = great_circle(-23.5, -46.3, 52.5, 13.4)
    check(len(segs) == 1 and len(segs[0]) == 65, "arco simples em 65 pontos")
    check(abs(segs[0][0][0] + 46.3) < 1e-6 and abs(segs[0][-1][1] - 52.5) < 1e-6,
          "arco comeca e termina nas estacoes")
    segs = great_circle(0.0, 170.0, 0.0, -170.0)
    check(len(segs) == 2, "arco cruzando o antimeridiano e' cortado em 2")
    check(segs[0][-1][0] == 180.0 and segs[1][0][0] == -180.0, "corte exatamente em ±180°")
    check(all(abs(b[0] - a[0]) < 180 for sg in segs for a, b in zip(sg, sg[1:])),
          "nenhum salto de longitude dentro de um segmento")
    same = great_circle(10.0, 20.0, 10.0, 20.0)
    check(len(same) == 1, "estacao no mesmo ponto nao quebra")

    world = load_world()
    check(len(world) > 100 and all(len(r) % 2 == 0 and len(r) >= 6 for r in world),
          f"mapa-mundi embutido carregado ({len(world)} aneis)")


if __name__ == "__main__":
    for fn in (test_icom, test_ascii, test_rigctld, test_controller, test_settings, test_map):
        fn()
    print()
    if fails:
        print(f"{len(fails)} FALHAS")
        raise SystemExit(1)
    print("TODOS OS TESTES PASSARAM")
