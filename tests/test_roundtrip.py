"""Round-trip: sintetiza FT8, mistura com ruido, decodifica e confere."""

import numpy as np

from ft8desk.native import Decoder, SAMPLE_RATE

SLOT = 15.0


def build_slot(messages, snr_db=0.0, seed=1, tx_offset=0.5, noise_bw=2500.0):
    rng = np.random.default_rng(seed)
    total = int(SLOT * SAMPLE_RATE)
    slot = rng.normal(0.0, 1.0, total).astype(np.float32)
    # ruido a -3 dBFS RMS -> sinal ajustado para o SNR pedido
    noise_rms = 10 ** (-3 / 20)
    slot *= noise_rms / np.sqrt(np.mean(slot ** 2))

    dec = Decoder()
    for text, freq in messages:
        wave = dec.encode(text, freq)
        sig_rms = np.sqrt(np.mean(wave ** 2))
        target_rms = noise_rms * 10 ** (snr_db / 20) * np.sqrt(noise_bw / 2500.0) * 2.5
        wave = wave * (target_rms / sig_rms)
        start = int(tx_offset * SAMPLE_RATE)
        slot[start:start + wave.size] += wave
    dec.close()
    return slot


def run():
    msgs = [
        ("CQ PY2ABC GG66", 1200.0),
        ("PY2ABC W1AW -12", 700.0),
        ("W1AW PY2ABC R-08", 2200.0),
        ("PY2ABC W1AW RR73", 1500.0),
    ]
    slot = build_slot(msgs, snr_db=-5.0)

    d = Decoder(f_min=200, f_max=3000)
    print(f"frame_len={d.frame_len} max_blocks={d.max_blocks}")

    pos = 0
    while pos + d.frame_len <= slot.size:
        d.feed(slot[pos:pos + d.frame_len])
        pos += d.frame_len

    print(f"blocos: {d.blocks_ready}/{d.max_blocks}")
    results = d.decode()
    print(f"decodificados: {len(results)}")
    for r in results:
        print(f"  {r.snr:+5.1f} dB  {r.time_s:5.2f}s  {r.freq_hz:6.0f} Hz  score={r.score:3d}  {r.text}")

    found = {r.text.decode("ascii", "replace").strip(): r for r in results}
    ok = 0
    for text, freq in msgs:
        r = found.get(text)
        if r and abs(r.freq_hz - freq) < 30:
            ok += 1
        else:
            print(f"  FALHOU: {text!r} freq esperada {freq}")
    print(f"\n{ok}/{len(msgs)} mensagens recuperadas")

    # encoder deve recusar lixo
    ok_pack, norm = d.check_text("PY2ABC W1AW -10")
    print(f"check_text ok={ok_pack} -> {norm!r}")
    d.close()
    return ok == len(msgs)


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
