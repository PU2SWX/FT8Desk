"""Escalonamento de transmissao nos slots FT8 (logica pura, testavel).

FT8 e' um protocolo de slots: cada periodo de 15 s comporta uma transmissao.
Duas estacoes que transmitem no MESMO slot nunca se ouvem -- elas precisam
alternar par/impar. Este modulo centraliza essa decisao para que ela seja
testada fora da UI.
"""

from __future__ import annotations

import math


def next_tx_slot(now: float, slot: float, offset: float, parity: int,
                 last_tx_slot: int | None = None) -> tuple[int, float]:
    """Retorna (indice do slot, instante absoluto) da proxima transmissao.

    now          instante atual (epoch)
    slot         duracao do slot (15 s para FT8)
    offset       atraso dentro do slot (ex.: 0.5 s)
    parity       0 = slots pares, 1 = impares
    last_tx_slot slot usado na transmissao anterior (nunca repetir)
    """
    k = math.ceil((now - offset) / slot)
    if k * slot + offset <= now + 0.05:
        k += 1
    if (k % 2) != (parity % 2):
        k += 1
    if last_tx_slot is not None and k <= last_tx_slot:
        k = last_tx_slot + 2 if (last_tx_slot + 2) % 2 == (parity % 2) else last_tx_slot + 1
        if (k % 2) != (parity % 2):
            k += 1
    return k, k * slot + offset


def tx_parity_for(dx_slot: int) -> int:
    """Paridade que devemos usar ao responder uma estacao: a oposta a dela."""
    return 1 - (dx_slot % 2)


def parity_name(parity: int) -> str:
    return "par" if parity % 2 == 0 else "impar"
