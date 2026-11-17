"""Selecao automatica de estacoes para chamar (modo AUTO).

Logica pura, sem Qt e sem hardware, para poder ser testada.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CqCandidate:
    call: str
    grid: str = ""
    snr: float = 0.0
    freq_hz: float = 1500.0
    dt: float = 0.0
    slot_index: int = 0
    cq_modifier: str = ""
    raw: str = ""

    @property
    def is_cq_dx(self) -> bool:
        return "DX" in self.cq_modifier.upper().split()


def pick_cq(candidates: list[CqCandidate], worked: set[str],
            min_snr: float = -18.0, skip_worked: bool = True,
            skip_cq_dx: bool = True) -> CqCandidate | None:
    """Escolhe a melhor estacao chamando CQ.

    Criterios: SNR minimo, opcionalmente ignorar quem ja esta no log e
    chamadas "CQ DX" (que normalmente nao se destinam a nos). Desempate pelo
    sinal mais forte -- quem escuta melhor tem mais chance de fechar o QSO.
    """
    pool = [c for c in candidates if c.call and c.snr >= min_snr]
    if skip_worked:
        pool = [c for c in pool if c.call.upper() not in worked]
    if skip_cq_dx:
        pool = [c for c in pool if not c.is_cq_dx]
    if not pool:
        return None
    return max(pool, key=lambda c: (c.snr, -c.freq_hz))
