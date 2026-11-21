"""Testes de logica pura (sem Qt e sem hardware)."""

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ft8swx.adif import (AdifLog, QsoRecord, adif_header, band_from_mhz,
                          filter_records, is_recent_duplicate, read_adif)
from ft8swx.auto import CqCandidate, pick_cq
from ft8swx.audio import SlotCollector, resample
from ft8swx.grid import distance_bearing, grid_to_latlon, latlon_to_grid
from ft8swx.parse import parse_message
from ft8swx.qso import Phase, QsoEngine, fmt_report
from ft8swx.schedule import next_tx_slot, tx_parity_for
from ft8swx.waterfall_model import WaterfallModel

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print("  FALHOU:", msg)
    else:
        print("  ok:", msg)


def test_parse():
    print("parse")
    p = parse_message("CQ PY2ABC GG66")
    check(p.is_cq and p.call_from == "PY2ABC" and p.grid == "GG66", "CQ com grid")
    p = parse_message("CQ DX W1AW FN31")
    check(p.is_cq and p.call_from == "W1AW" and p.grid == "FN31", "CQ DX + grid")
    p = parse_message("PY2ABC N0CALL -12")
    check(p.call_to == "PY2ABC" and p.call_from == "N0CALL" and p.report == -12,
          "relatorio direcionado")
    p = parse_message("PY2ABC N0CALL R-07")
    check(p.report == -7 and p.token == "R", "R+relatorio")
    p = parse_message("PY2ABC N0CALL RR73")
    check(p.token == "RR73", "RR73")
    p = parse_message("N0CALL PY2ABC 73")
    check(p.token == "73", "73")


def test_grid():
    print("grid")
    check(grid_to_latlon("GG66") is not None, "decode GG66")
    check(abs(grid_to_latlon("JM79")[0] - 39.5) < 1, "latitude JM79 (39.5 N)")
    g = latlon_to_grid(-23.55, -46.63)
    check(g.startswith("GG"), f"latlon->grid {g}")
    d = distance_bearing("GG66", "FN31")
    check(d and 7000 < d[0] < 8200, f"distancia SP->CT {d[0]:.0f} km" if d else "sem distancia")


def test_qso():
    print("qso (nos chamamos CQ)")
    e = QsoEngine("PY2ABC", "GG66", tx_report=-10)
    check(e.start_cq() == "CQ PY2ABC GG66", "mensagem de CQ")
    a = e.on_message(parse_message("PY2ABC N0CALL -05"), snr=-5, now=100)
    check(a.tx_message == "N0CALL PY2ABC -05", f"respondemos relatorio: {a.tx_message}")
    a = e.on_message(parse_message("PY2ABC N0CALL R-12"), snr=-12, now=130)
    check(a.tx_message == "N0CALL PY2ABC RR73" and a.log,
          f"R recebido -> RR73 e log: {a.tx_message} log={a.log}")
    check(e.state.phase == Phase.FINAL, "fase FINAL apos RR73")
    check(not e.after_tx(), "RR73 nao deve ser repetido")
    a = e.on_message(parse_message("PY2ABC N0CALL 73"), now=160)
    check(e.state.phase == Phase.DONE, "73 do outro lado -> DONE")
    check(a.tx_message is None, "nada a transmitir depois do 73")

    print("qso (respondendo um CQ -> Tx2, Tx4, Tx6)")
    e = QsoEngine("PY2ABC", "GG66", tx_report=-10)
    msg = e.call("W1AW", "FN31", they_cq=True)
    check(msg == "W1AW PY2ABC GG66", f"Tx2 (grid): {msg}")
    a = e.on_message(parse_message("PY2ABC W1AW -03"), snr=-3, now=200)
    check(a.tx_message == "W1AW PY2ABC R-03",
          f"Tx4 (R+relatorio, papel de respondedor): {a.tx_message}")
    a = e.on_message(parse_message("PY2ABC W1AW RR73"), now=230)
    check(a.tx_message == "W1AW PY2ABC 73", f"Tx6 (73): {a.tx_message}")
    check(a.log, "73 enviado -> logar")
    check(not e.after_tx(), "nao repete o 73")

    print("qso (chamando com relatorio)")
    e = QsoEngine("PY2ABC", "GG66")
    msg = e.call("W1AW", they_cq=False, report=-15)
    check(msg == "W1AW PY2ABC -15", f"chamada direta com relatorio: {msg}")

    print("qso (limite de repeticoes)")
    e = QsoEngine("PY2ABC", "GG66", max_repeats=4)
    e.call("W1AW", "FN31", now=100)
    reps = 0
    while e.after_tx():
        reps += 1
        if reps > 20:
            break
    check(e.state.phase == Phase.DONE, "desiste depois de N repeticoes")

    print("qso (nao repetir QSO recem-concluido)")
    e = QsoEngine("PY2ABC", "GG66")
    e.mark_worked("CE3TSK", 1000.0)
    a = e.on_message(parse_message("PY2ABC CE3TSK -10"), snr=-10, now=1060,
                     auto_reply=True)
    check(a.tx_message is None, "60 s depois: nao reabre o QSO")
    a = e.on_message(parse_message("PY2ABC CE3TSK -10"), snr=-10, now=1500,
                     auto_reply=True)
    check(a.tx_message is not None, "apos 5 min: pode chamar de novo")

    print("qso (abortar / watchdog)")
    e = QsoEngine("PY2ABC", "GG66")
    e.call("W1AW", "FN31")
    check(e.state.active, "QSO ativo antes de abortar")
    e.abort("watchdog")
    check(e.state.phase == Phase.DONE and not e.state.active,
          "abort encerra e libera o modo AUTO")
    check(reps == 4, f"repetiu {reps} vezes (esperado 4)")

    print("qso (CQ pode repetir sem limite)")
    e = QsoEngine("PY2ABC", "GG66")
    e.start_cq()
    check(all(e.after_tx() for _ in range(50)), "CQ nunca desiste")


def test_adif():
    print("adif")
    tmp = Path(tempfile.mkdtemp()) / "t.adi"
    log = AdifLog(tmp)
    rec = QsoRecord(call="W1AW", grid="FN31", freq_mhz=14.074, band="20M",
                    rst_sent="-10", rst_rcvd="-08", qso_date="20260101",
                    time_on="123456", my_call="PY2ABC", my_grid="GG66")
    log.append(rec)
    rec2 = QsoRecord(call="N0CALL", grid="DM79", freq_mhz=7.074, mode="FT8")
    log.append(rec2)
    back = read_adif(tmp)
    check(len(back) == 2, f"relidos {len(back)} registros")
    check(back[0].call == "W1AW" and back[0].grid == "FN31" and back[0].rst_rcvd == "-08",
          "campos preservados")
    check(len(log.worked_calls()) == 2, "worked_calls sem banda")
    # trabalhado por banda: um QSO em 20 m nao bloqueia a mesma estacao em 40 m
    check(log.worked_calls("20m") == {"W1AW"}, f"20m: {log.worked_calls('20m')}")
    check(log.worked_calls("40m") == {"N0CALL"}, f"40m: {log.worked_calls('40m')}")
    check(log.worked_calls("15m") == set(), "15m ainda vazia")
    check(band_from_mhz(14.074) == "20M", "banda 20m")

    print("exportacao ADIF (QRZ)")
    exp = Path(tempfile.mkdtemp()) / "qrz.adi"
    n = log.export(exp, mode_style="qrz")
    check(n == 2, f"exportou {n} QSOs")
    txt = exp.read_text()
    check(txt.startswith("FT8SWX"), "cabecalho presente")
    check("<ADIF_VER:5>3.1.4" in txt and "<EOH>" in txt, "versao e EOH")
    # campos obrigatorios do QRZ em todo registro
    for campo in ("<CALL:", "<QSO_DATE:", "<BAND:", "<MODE:"):
        check(txt.count(campo) == 2, f"{campo} em todos os registros")
    check("<MODE:4>MFSK" not in txt, "formato QRZ nao usa MFSK")
    check("<EOR>" in txt, "terminador EOR")
    again = read_adif(exp)
    check(len(again) == 2 and again[0].call == "W1AW", "arquivo exportado e' lido de volta")

    exp2 = Path(tempfile.mkdtemp()) / "lotw.adi"
    log.export(exp2, mode_style="lotw")
    check("<MODE:4>MFSK<SUBMODE:3>FT8" in exp2.read_text(), "formato LoTW com submode")

    # filtros
    m1 = QsoRecord(call="A1A", freq_mhz=14.074, mode="FT8", qso_date="20260101",
                   band="20M")
    m2 = QsoRecord(call="B2B", freq_mhz=7.074, mode="FT8", qso_date="20260301",
                   band="40M")
    m3 = QsoRecord(call="C3C", freq_mhz=14.074, mode="FT4", qso_date="20260301",
                   band="20M")
    recs = [m1, m2, m3]
    check(len(filter_records(recs, since="20260201")) == 2, "filtro por data")
    check(len(filter_records(recs, band="20M")) == 2, "filtro por banda")
    check(len(filter_records(recs, mode="FT4")) == 1, "filtro por modo")
    check(len(filter_records(recs, since="20260201", band="20M")) == 1,
          "filtros combinados")

    print("anti-duplicidade (log repetido)")
    base = QsoRecord(call="CE3TSK", freq_mhz=14.074, band="20M", mode="FT8",
                     qso_date="20261116", time_on="004530")
    perto = QsoRecord(call="CE3TSK", freq_mhz=14.074, band="20M", mode="FT8",
                      qso_date="20261116", time_on="004630")     # 1 min depois
    longe = QsoRecord(call="CE3TSK", freq_mhz=14.074, band="20M", mode="FT8",
                      qso_date="20261116", time_on="012000")     # 35 min depois
    outra_banda = QsoRecord(call="CE3TSK", freq_mhz=7.074, band="40M", mode="FT8",
                            qso_date="20261116", time_on="004600")
    check(is_recent_duplicate([base], perto), "1 min depois = duplicado")
    check(not is_recent_duplicate([base], longe), "35 min depois = QSO novo")
    check(not is_recent_duplicate([base], outra_banda), "outra banda = QSO novo")

    print("limpar log (arquivar)")
    tmpdir = Path(tempfile.mkdtemp())
    lg = AdifLog(tmpdir / "limpo.adi")
    lg.append(base)
    lg.append(perto)
    check(len(lg.records) == 2, "2 QSOs antes")
    backup = lg.archive()
    check(backup.exists() and len(read_adif(backup)) == 2,
          "backup guardou os 2 QSOs")
    check(len(lg.records) == 0 and lg.path.exists(), "log novo em branco")
    check(lg.path.read_text().startswith("FT8SWX"), "cabecalho recriado")


def test_collector():
    print("coletor de slots")
    fs = 12000
    col = SlotCollector(fs, 15.0)
    got = []
    t = 0.0
    total = int(50 * fs)
    bloco = 600
    rng = np.arange(total, dtype=np.float32)
    for i in range(0, total, bloco):
        chunk = rng[i:i + bloco]
        t = (i + bloco - 1) / fs
        got.extend(col.push(chunk, t))
    check(len(got) >= 2, f"slots completos: {len(got)}")
    check(all(w.size == int(15 * fs) for _, w in got), "tamanho de 15 s por slot")
    # continuidade: primeiro sample de um slot deve seguir o do anterior
    if len(got) >= 2:
        gap = got[1][1][0] - got[0][1][0]
        check(abs(gap - int(15 * fs)) < 1, f"passo entre slots: {gap}")


def test_resample():
    print("resample")
    fs = 48000
    t = np.arange(fs) / fs
    x = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    y = resample(x, fs, 12000)
    check(abs(y.size - 12000) < 10, f"tamanho {y.size}")
    spec = np.abs(np.fft.rfft(y * np.hanning(y.size)))
    peak = np.argmax(spec) * 12000 / y.size
    check(abs(peak - 1000) < 15, f"pico em {peak:.0f} Hz")
    up = resample(y, 12000, 48000)
    check(abs(up.size - 48000) < 40, f"upsample {up.size}")


def test_waterfall():
    print("waterfall")
    m = WaterfallModel(12000, width=200, f_min=200, f_max=3000)
    fs = 12000
    t = np.arange(int(fs * 0.5)) / fs
    # tom + ruido (sinal sem ruido satura a escala adaptativa: nao e realista)
    rng = np.random.default_rng(0)
    tone = (np.sin(2 * np.pi * 1500 * t) * 0.5
            + rng.normal(0, 1e-3, t.size)).astype(np.float32)
    m.add_audio(tone)
    peak_bin = int(np.argmax(m.levels))
    peak_hz = m.freqs[peak_bin]
    check(abs(peak_hz - 1500) < 15, f"pico no waterfall em {peak_hz:.0f} Hz")
    rgb = m.rgb()
    # waterfall vertical: eixo Y = tempo, eixo X = frequencia
    check(rgb.shape == (200, m.n_bins, 3), f"forma RGB (tempo, freq, 3): {rgb.shape}")
    check(m.freq_to_frac(200) == 0.0 and m.freq_to_frac(3000) == 1.0,
          "eixo de frequencia horizontal")

    # alinhamento: o pico do espectro tem de cair na mesma coluna em que o
    # sinal aparece na ultima linha do waterfall
    col_peak = int(np.argmax(m.levels))
    last_row = m.data[:, -1]          # coluna de tempo mais recente
    row_peak = int(np.argmax(last_row))
    check(abs(col_peak - row_peak) <= 2,
          f"pico alinhado espectro/waterfall ({col_peak} vs {row_peak})")


def test_auto():
    print("modo AUTO (escolha de CQ)")
    cs = [
        CqCandidate("W1AW", "FN31", -8, 1200, 0.1, 10),
        CqCandidate("K1JT", "FN20", -3, 800, 0.2, 10),
        CqCandidate("DL1ABC", "JO40", -19, 1500, -0.1, 10),
        CqCandidate("VE3XYZ", "EN93", -5, 2000, 0.0, 10, cq_modifier="DX"),
    ]
    best = pick_cq(cs, set())
    check(best is not None and best.call == "K1JT", f"mais forte: {best.call if best else None}")

    # "CQ DX" ignorado por padrao
    cs2 = [c for c in cs if c.call != "K1JT"]
    best = pick_cq(cs2, set())
    check(best is not None and best.call == "W1AW", f"CQ DX ignorado: {best.call if best else None}")

    # quem ja esta no log e' ignorado
    best = pick_cq(cs, {"K1JT", "W1AW", "VE3XYZ"})
    check(best is None, "todos trabalhados -> ninguem")

    # desligando o filtro de repetidos, o CQ DX passa
    # com os filtros desligados, o CQ DX mais forte passa a ser escolhido
    best = pick_cq(cs2, {"W1AW"}, skip_worked=False, skip_cq_dx=False)
    check(best is not None and best.call == "VE3XYZ",
          f"filtros desligados -> CQ DX mais forte: {best.call if best else None}")

    # SNR minimo
    best = pick_cq(cs, set(), min_snr=-6)
    check(best is not None and best.call == "K1JT", "corte por SNR")

    print("modo AUTO (chamada direta a mim)")
    e = QsoEngine("PY2ABC", "GG66")
    a = e.on_message(parse_message("PY2ABC W1AW -12"), snr=-12, now=10, auto_reply=True)
    check(a.tx_message == "W1AW PY2ABC -12", f"responde sozinho: {a.tx_message}")
    check(e.state.phase == Phase.REPORT, "entrou em REPORT")

    e = QsoEngine("PY2ABC", "GG66")
    a = e.on_message(parse_message("PY2ABC W1AW -12"), snr=-12, now=10, auto_reply=False)
    check(a.tx_message is None, "auto_reply desligado nao transmite")

    # um 73 solto nao pode iniciar QSO
    e = QsoEngine("PY2ABC", "GG66")
    a = e.on_message(parse_message("PY2ABC W1AW 73"), now=10, auto_reply=True)
    check(a.tx_message is None, "73 isolado nao abre QSO")


def test_qso_falso_positivo():
    """Regressao: QSO so vale com mensagens do DX dirigidas a mim e relatorio trocado."""
    print("qso (DX fala com OUTRA estacao nao avanca nem loga)")
    for msg in ("K1ABC W1AW RR73", "K1ABC W1AW R-10", "K1ABC W1AW 73"):
        e = QsoEngine("PU2SWX", "GG66")
        e.call("W1AW", "FN31", they_cq=True, now=100)
        a = e.on_message(parse_message(msg), snr=-8, now=115)
        check(a.tx_message is None and not a.log, f"ignora '{msg}'")

    e = QsoEngine("PU2SWX", "GG66")
    e.call("W1AW", "FN31", they_cq=True, now=100)
    a = e.on_message(parse_message("CQ W1AW FN31"), snr=-8, now=115)
    check(a.tx_message is None, "CQ do proprio DX nao avanca o QSO")

    print("qso (RR73/73 sem relatorio trocado nao loga)")
    e = QsoEngine("PU2SWX", "GG66")
    e.call("W1AW", "FN31", they_cq=True, now=100)
    a = e.on_message(parse_message("PU2SWX W1AW RR73"), now=115)
    check(a.tx_message is None and not a.log, "RR73 sem relatorio e' ignorado")

    print("qso (73 solto nao abre QSO em resposta ao CQ)")
    e = QsoEngine("PU2SWX", "GG66")
    e.start_cq(now=0)
    a = e.on_message(parse_message("PU2SWX W1AW 73"), now=15)
    check(a.tx_message is None and e.state.phase == Phase.CQ, "continua em CQ")

    print("qso (reenvio do final quando o DX nao copiou)")
    # chamador com auto_cq: depois do log volta para CQ
    e = QsoEngine("PU2SWX", "GG66")
    e.start_cq(now=0)
    e.on_message(parse_message("PU2SWX W1AW FN31"), snr=-8, now=15)
    a = e.on_message(parse_message("PU2SWX W1AW R-10"), snr=-8, now=45)
    check(a.tx_message == "W1AW PU2SWX RR73" and a.log, "RR73 + log")
    e.mark_worked("W1AW", 60)
    e.start_cq(now=60)                                   # o que _log_qso faz
    a = e.on_message(parse_message("PU2SWX W1AW R-10"), snr=-8, now=75)
    check(a.tx_message == "W1AW PU2SWX RR73" and not a.log,
          f"DX repete R-10 -> reenvia RR73 sem logar de novo: {a.tx_message}")
    check(e.state.phase == Phase.CQ, "continua em CQ depois do reenvio")
    for t in (105, 135):
        a = e.on_message(parse_message("PU2SWX W1AW R-10"), snr=-8, now=t)
    a = e.on_message(parse_message("PU2SWX W1AW R-10"), snr=-8, now=165)
    check(a.tx_message is None, "limite de reenvios (3)")
    a = e.on_message(parse_message("PU2SWX W1AW R-10"), snr=-8, now=1000)
    check(a.tx_message != "W1AW PU2SWX RR73", "fora da janela de 5 min nao reenvia")

    # respondedor: o DX repete RR73 -> reenvia 73
    e = QsoEngine("PU2SWX", "GG66")
    e.call("W1AW", "FN31", they_cq=True, now=100)
    e.on_message(parse_message("PU2SWX W1AW -03"), snr=-3, now=115)
    a = e.on_message(parse_message("PU2SWX W1AW RR73"), now=145)
    check(a.tx_message == "W1AW PU2SWX 73" and a.log, "respondedor: 73 + log")
    e.after_tx()
    e.mark_worked("W1AW", 150)
    a = e.on_message(parse_message("PU2SWX W1AW RR73"), now=175)
    check(a.tx_message == "W1AW PU2SWX 73" and not a.log,
          "respondedor: DX repete RR73 -> reenvia 73")

    print("qso (relatorio na chamada direta e' guardado)")
    e = QsoEngine("PU2SWX", "GG66")
    a = e.on_message(parse_message("PU2SWX W1AW -12"), snr=-12, now=10, auto_reply=True)
    check(e.state.rx_report == -12, "rx_report guardado na chamada direta")


def test_dual_qso():
    """Duas estacoes completam um QSO trocando mensagens como no ar."""
    print("qso completo entre duas estacoes")
    a = QsoEngine("PY2ABC", "GG66", tx_report=-10)   # chama CQ
    b = QsoEngine("W1AW", "FN31", tx_report=-12)     # responde

    transcript: list[tuple[str, str]] = []

    def deliver(to, who, msg, snr=-9):
        act = to.on_message(parse_message(msg, to.my_call), snr=snr, now=0)
        return act

    m = a.start_cq()
    transcript.append(("A", m))
    p = parse_message(m, b.my_call)
    m = b.call(p.call_from, p.grid, they_cq=True)
    transcript.append(("B", m))

    for who, eng in (("A", a), ("B", b), ("A", a), ("B", b)):
        act = deliver(eng, who, m)
        if act.tx_message:
            m = act.tx_message
            transcript.append((who, m))

    esperado = [
        ("A", "CQ PY2ABC GG66"),        # Tx1
        ("B", "PY2ABC W1AW FN31"),      # Tx2
        ("A", "W1AW PY2ABC -09"),       # Tx3
        ("B", "PY2ABC W1AW R-09"),      # Tx4
        ("A", "W1AW PY2ABC RR73"),      # Tx5
        ("B", "PY2ABC W1AW 73"),        # Tx6
    ]
    check(transcript == esperado, f"sequencia Tx1..Tx6: {transcript}")
    check(a.state.phase == Phase.FINAL and b.state.phase == Phase.FINAL,
          "ambos encerraram")
    check(not a.after_tx() and not b.after_tx(), "nenhum repete a despedida")
    check(a.state.phase == Phase.DONE and b.state.phase == Phase.DONE,
          "estado final DONE nos dois")


def test_schedule():
    print("escalonamento de slots (par/impar)")
    slot = 15.0
    off = 0.5
    # 1) inicio: transmitimos no slot 0 (par) assim que possivel
    k, t = next_tx_slot(0.2, slot, off, 0)
    check(k == 0 and abs(t - 0.5) < 1e-6, f"primeiro slot: k={k} t={t:.2f}")

    # 2) apos transmitir no slot 0 (audio terminou em 13.3), a proxima
    #    transmissao TEM de ser dois slots depois -- nunca 3 s depois
    k, t = next_tx_slot(13.3, slot, off, 0, last_tx_slot=0)
    check(k == 2 and abs(t - 30.5) < 1e-6, f"proxima TX em k={k} t={t:.1f}s")
    check(t - 13.3 > 14.0, f"espera {t - 13.3:.1f}s entre transmissoes")

    # 3) paridade impar
    k, t = next_tx_slot(0.2, slot, off, 1)
    check(k == 1 and abs(t - 15.5) < 1e-6, f"slot impar: k={k} t={t:.1f}")

    # 4) nunca repetir o mesmo slot
    k, t = next_tx_slot(30.4, slot, off, 0, last_tx_slot=2)
    check(k > 2, f"nao repete slot 2 (k={k})")

    # 5) paridade do DX inverter
    check(tx_parity_for(0) == 1 and tx_parity_for(1) == 0, "responder inverte paridade")

    # 6) simulacao de uma hora: jamais dois TX no mesmo slot e sempre
    #    pelo menos 2 slots de intervalo
    now = 0.0
    parity = 0
    last = -1
    times = []
    for _ in range(120):
        k, t = next_tx_slot(now, slot, off, parity, last if last >= 0 else None)
        times.append(t)
        last = k
        now = t + 12.64 + 0.2   # fim do audio + hang
    gaps = [b - a for a, b in zip(times, times[1:])]
    check(min(gaps) >= 29.9, f"menor intervalo entre TX: {min(gaps):.1f}s")
    check(all(i % 2 == 0 for i in [int(round(x / slot)) for x in times]),
          "todos os TX em slots da paridade escolhida")


if __name__ == "__main__":
    for fn in (test_parse, test_grid, test_qso, test_adif, test_collector,
               test_resample, test_waterfall, test_schedule, test_auto, test_dual_qso,
               test_qso_falso_positivo):
        fn()
    print()
    if fails:
        print(f"{len(fails)} FALHAS")
        raise SystemExit(1)
    print("TODOS OS TESTES PASSARAM")
