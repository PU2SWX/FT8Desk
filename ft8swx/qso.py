"""Maquina de estados do QSO FT8, ciente do papel (quem chamou / quem respondeu).

Sequencia padrao (WSJT-X):

    Chamador (Tx1..Tx5)          Respondedor (Tx2..Tx6)
    --------------------         ----------------------
    Tx1  CQ CALL GRID
                                 Tx2  CALL ME GRID
    Tx3  DX CALL -10
                                 Tx4  DX CALL R-12
    Tx5  DX CALL RR73            (log)
                                 Tx6  DX CALL 73      (log)

O "R" em Tx4 e' o acuse de recebimento do relatorio: quem responde ao CQ usa
essa forma; quem chamou usa o relatorio simples. Sem essa distincao o QSO
"funciona" mas a sequencia fica incoerente com os botoes Tx1..Tx6.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .parse import Parsed


class Phase(str, Enum):
    IDLE = "IDLE"
    CQ = "CQ"                  # chamando CQ
    CALLING = "CALLING"        # chamamos um DX, aguardando resposta
    REPORT = "REPORT"          # enviamos relatorio, aguardando R/RR73
    FINAL = "FINAL"            # enviamos RR73 ou 73: QSO encerrado para nos
    DONE = "DONE"


ROLE_CALLER = "caller"         # nos chamamos CQ (ou fomos chamados direto)
ROLE_RESPONDER = "responder"   # nos respondemos ao CQ de outro


@dataclass
class QsoState:
    phase: Phase = Phase.IDLE
    role: str = ""
    dx_call: str = ""
    dx_grid: str = ""
    rx_report: int | None = None
    tx_report: int = -10
    tx_message: str = ""
    repeats: int = 0
    sent_final: bool = False
    started_at: float = 0.0
    last_rx_at: float = 0.0
    progress_at: float = 0.0     # ultimo sinal de vida (TX ou RX)
    logged: bool = False

    @property
    def active(self) -> bool:
        return self.phase not in (Phase.IDLE, Phase.DONE)


@dataclass
class Action:
    tx_message: str | None = None
    log: bool = False
    note: str = ""


def fmt_report(value: int) -> str:
    return f"{value:+03d}"


class QsoEngine:
    def __init__(self, my_call: str = "", my_grid: str = "", tx_report: int = -10,
                 max_repeats: int = 4):
        self.my_call = my_call.upper()
        self.my_grid = my_grid.upper()
        self.tx_report = tx_report
        self.max_repeats = max_repeats
        self.state = QsoState()
        self.worked_at: dict[str, float] = {}   # call -> instante da conclusao

    def mark_worked(self, call: str, now: float) -> None:
        if call:
            self.worked_at[call.upper()] = now

    def recently_worked(self, call: str, now: float, window: float = 300.0) -> bool:
        t = self.worked_at.get(call.upper())
        return t is not None and bool(now) and (now - t) <= window

    # -- configuracao --------------------------------------------------
    def configure(self, my_call: str, my_grid: str, tx_report: int | None = None) -> None:
        self.my_call = (my_call or "").upper()
        self.my_grid = (my_grid or "").upper()
        if tx_report is not None:
            self.tx_report = tx_report

    def reset(self, keep_cq: bool = False) -> None:
        was_cq = self.state.phase == Phase.CQ
        self.state = QsoState()
        if keep_cq and was_cq:
            self.start_cq()

    # -- inicio --------------------------------------------------------
    def start_cq(self, now: float = 0.0) -> str:
        self.state = QsoState(phase=Phase.CQ, role=ROLE_CALLER,
                              tx_report=self.tx_report, started_at=now)
        self.state.tx_message = f"CQ {self.my_call} {self.my_grid}".strip()
        return self.state.tx_message

    def call(self, call: str, grid: str = "", report: int | None = None,
             they_cq: bool = True, now: float = 0.0) -> str:
        """Inicia chamada a um DX. they_cq=True: estamos respondendo um CQ."""
        call = call.upper()
        tx_report = self.state.tx_report if report is None else int(report)
        if they_cq and grid:
            msg = f"{call} {self.my_call} {self.my_grid}".strip()
            role = ROLE_RESPONDER
        else:
            msg = f"{call} {self.my_call} {fmt_report(tx_report)}"
            role = ROLE_CALLER
        self.state = QsoState(phase=Phase.CALLING, role=role, dx_call=call,
                              dx_grid=grid.upper(), tx_report=tx_report,
                              tx_message=msg, started_at=now)
        return msg

    # -- fim de transmissao (chamado pela UI) --------------------------
    def after_tx(self) -> bool:
        """Decide se a mensagem atual deve ser repetida no proximo slot."""
        st = self.state
        if st.phase in (Phase.IDLE, Phase.DONE):
            return False
        if st.phase == Phase.CQ:
            return True                      # CQ pode repetir indefinidamente
        if st.phase == Phase.FINAL:
            st.phase = Phase.DONE            # ja nos despedimos: nao repetir
            return False
        st.repeats += 1
        st.progress_at = st.progress_at  # atualizado pela UI no disparo
        if st.repeats > self.max_repeats:
            st.phase = Phase.DONE
            return False
        return True

    def abort(self, reason: str = "") -> None:
        """Encerra o QSO a forca (watchdog, erro de TX, pedido do operador)."""
        if self.state.active:
            self.state.phase = Phase.DONE
            self.state.tx_message = ""

    # -- reacao a um decode -------------------------------------------
    def on_message(self, parsed: Parsed, snr: int | None = None,
                   now: float = 0.0, auto_reply: bool = True) -> Action:
        st = self.state
        me = self.my_call
        if not me:
            return Action(note="sem indicativo configurado")
        p = parsed

        # 0) Ociosos e alguem nos chama direto -> entramos como chamador
        if st.phase in (Phase.IDLE, Phase.DONE) and p.call_to.upper() == me \
                and p.call_from and (p.report is not None or p.grid):
            if not auto_reply:
                return Action(note=f"{p.call_from} chamando voce")
            if self.recently_worked(p.call_from, now):
                return Action(note=f"{p.call_from}: QSO concluido ha pouco, "
                                   "nao vou repetir")
            rpt = int(round(snr)) if snr is not None else st.tx_report
            self.state = QsoState(phase=Phase.REPORT, role=ROLE_CALLER,
                                  dx_call=p.call_from.upper(), dx_grid=p.grid,
                                  tx_report=max(-24, min(20, rpt)), started_at=now)
            self.state.tx_message = (f"{self.state.dx_call} {me} "
                                     f"{fmt_report(self.state.tx_report)}")
            return Action(tx_message=self.state.tx_message,
                          note=f"{p.call_from} chamou voce - respondendo")

        # 1) Alguem responde ao nosso CQ
        if st.phase == Phase.CQ and p.call_to.upper() == me and p.call_from:
            st.dx_call = p.call_from.upper()
            st.dx_grid = p.grid
            st.role = ROLE_CALLER
            st.started_at = now or st.started_at
            return self._send_report(st, snr, first_time=True)

        if not st.active:
            return Action(note="QSO encerrado")

        # 2) Mensagem de outra estacao que nao participa do QSO
        if p.call_to.upper() != me and p.call_from.upper() != st.dx_call:
            return Action(note="nao relacionado ao QSO atual")

        dx = st.dx_call
        st.last_rx_at = now
        st.progress_at = now
        token = (p.token or "").upper()

        # 3) Despedida do outro lado
        if token == "73":
            # ele encerrou: nao ha o que transmitir
            st.phase = Phase.DONE
            return Action(log=not st.logged, note="73 recebido: QSO completo")
        if token in ("RR73", "RRR"):
            if st.sent_final:
                st.phase = Phase.DONE
                return Action(log=not st.logged,
                              note="QSO confirmado pelo outro lado")
            # recebemos RR73 sem ter mandado o nosso -> fechamos com 73
            return self._send_final(st, "73")

        # 4) Relatorio (com ou sem "R")
        if p.report is not None:
            st.rx_report = int(p.report)
            acked = self._has_r(p)
            if st.phase == Phase.CALLING:
                return self._send_report(st, snr, first_time=True)
            if acked:
                # ele acusou o nosso relatorio -> mandamos o RR73 e logamos
                return self._send_final(st, "RR73")
            # relatorio sem R: repetimos o nosso
            return self._send_report(st, snr, first_time=False)

        # 5) Grid: mesma coisa que relatorio
        if p.grid and st.phase in (Phase.CALLING, Phase.REPORT):
            st.dx_grid = p.grid
            return self._send_report(st, snr, first_time=True)

        return Action()

    # -- helpers -------------------------------------------------------
    @staticmethod
    def _has_r(p: Parsed) -> bool:
        return (p.token or "").upper() == "R" or any(
            t.upper().startswith("R") and t[1:].lstrip("+-").isdigit()
            for t in p.tokens
        )

    def _send_report(self, st: QsoState, snr: int | None, first_time: bool) -> Action:
        if first_time and snr is not None:
            st.tx_report = max(-24, min(20, int(round(snr))))
        rpt = fmt_report(st.tx_report)
        # O "R" (Tx4) e' do respondedor que ja recebeu um relatorio:
        # e' o acuse de recebimento alem do nosso proprio relatorio.
        prefix = "R" if (st.role == ROLE_RESPONDER and st.rx_report is not None) else ""
        st.phase = Phase.REPORT
        st.repeats = 0
        st.tx_message = f"{st.dx_call} {self.my_call} {prefix}{rpt}"
        return Action(tx_message=st.tx_message)

    def _send_final(self, st: QsoState, token: str) -> Action:
        st.phase = Phase.FINAL
        st.sent_final = True
        st.repeats = 0
        st.tx_message = f"{st.dx_call} {self.my_call} {token}"
        return Action(tx_message=st.tx_message, log=not st.logged,
                      note=f"QSO completo ({token})")
