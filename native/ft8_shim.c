/*
 * ft8_shim.c - Thin C API around kgoba/ft8_lib (MIT) for use from Python/ctypes.
 *
 * Provides:
 *   - streaming waterfall/decoder object per slot (FT8 / FT4)
 *   - text -> audio synthesis (GFSK shaped)
 *   - callsign hash table so <HASH> callsigns resolve across slots
 *
 * Build: see build_native.py
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdint.h>
#include <stdbool.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef HAVE_STPCPY
#define HAVE_STPCPY 1
#endif

#include "ft8/decode.h"
#include "ft8/encode.h"
#include "ft8/message.h"
#include "ft8/constants.h"
#include "common/monitor.h"

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif

#define FT8D_MAX_RESULTS 80
#define MAX_DECODED 80
#define HASHTABLE_SIZE 256

/* ------------------------------------------------------------------ */
/* Result structure shared with Python                                 */
/* ------------------------------------------------------------------ */

#pragma pack(push, 1)
typedef struct
{
    char text[48];      /* decoded message, NUL terminated            */
    float freq_hz;      /* audio frequency of the signal              */
    float time_s;       /* start offset inside the slot, seconds      */
    float snr;          /* estimated SNR in dB (2500 Hz reference)    */
    int32_t score;      /* Costas sync score                          */
    int32_t ldpc_errors;
    int32_t flags;      /* bit0: contains unresolved <HASH> callsign  */
} ft8d_result_t;
#pragma pack(pop)

typedef struct
{
    char callsign[12];
    uint32_t hash; /* 8 MSBs = age, 22 LSBs = hash */
} hash_entry_t;

struct ft8d
{
    monitor_t mon;
    monitor_config_t cfg;
    int sample_rate;
    int frame_len;    /* samples consumed per monitor_process() call  */
    int total_fed;    /* samples fed since reset                      */
    ftx_protocol_t protocol;
    float f_min, f_max;
    hash_entry_t hashtable[HASHTABLE_SIZE];
    ftx_message_t decoded[MAX_DECODED];
    ftx_callsign_hash_interface_t hash_if;
};

/* ------------------------------------------------------------------ */
/* Callsign hash table                                                 */
/* ------------------------------------------------------------------ */

static void hashtable_init(hash_entry_t *tbl)
{
    memset(tbl, 0, sizeof(hash_entry_t) * HASHTABLE_SIZE);
}

static void hashtable_add_cb(struct ft8d *me, const char *callsign, uint32_t hash);

static bool hashtable_lookup(ftx_callsign_hash_type_t hash_type, uint32_t hash, char *callsign)
{
    /* The callback receives no context pointer, so the table lives in a
     * per-thread static. Decoding happens on one worker thread, so this is
     * safe for this application. */
    static hash_entry_t *tbl = NULL;
    if (tbl == NULL)
    {
        callsign[0] = '\0';
        return false;
    }
    uint8_t hash_shift = (hash_type == FTX_CALLSIGN_HASH_10_BITS)
                             ? 12
                             : (hash_type == FTX_CALLSIGN_HASH_12_BITS ? 10 : 0);
    uint16_t hash10 = (hash >> (12 - hash_shift)) & 0x3FFu;
    int idx = (hash10 * 23) % HASHTABLE_SIZE;
    while (tbl[idx].callsign[0] != '\0')
    {
        if (((tbl[idx].hash & 0x3FFFFFu) >> hash_shift) == hash)
        {
            strcpy(callsign, tbl[idx].callsign);
            tbl[idx].hash &= 0x3FFFFFu; /* reset age */
            return true;
        }
        idx = (idx + 1) % HASHTABLE_SIZE;
    }
    callsign[0] = '\0';
    return false;
}

static void hashtable_add_cb(struct ft8d *me, const char *callsign, uint32_t hash)
{
    hash_entry_t *tbl = me->hashtable;
    uint16_t hash10 = (hash >> 12) & 0x3FFu;
    int idx = (hash10 * 23) % HASHTABLE_SIZE;
    while (tbl[idx].callsign[0] != '\0')
    {
        if (((tbl[idx].hash & 0x3FFFFFu) == hash) &&
            (0 == strcmp(tbl[idx].callsign, callsign)))
        {
            tbl[idx].hash &= 0x3FFFFFu;
            return;
        }
        idx = (idx + 1) % HASHTABLE_SIZE;
    }
    strncpy(tbl[idx].callsign, callsign, 11);
    tbl[idx].callsign[11] = '\0';
    tbl[idx].hash = hash;
}

static void hashtable_save_adapter(const char *callsign, uint32_t hash)
{
    /* ft8_lib passes no context; route through a thread-local pointer. */
    extern struct ft8d *ft8d_active_instance;
    if (ft8d_active_instance != NULL)
        hashtable_add_cb(ft8d_active_instance, callsign, hash);
}

struct ft8d *ft8d_active_instance = NULL;

static void hashtable_age(hash_entry_t *tbl, uint8_t max_age)
{
    for (int i = 0; i < HASHTABLE_SIZE; ++i)
    {
        if (tbl[i].callsign[0] != '\0')
        {
            uint8_t age = (uint8_t)(tbl[i].hash >> 24);
            if (age > max_age)
            {
                tbl[i].callsign[0] = '\0';
                tbl[i].hash = 0;
            }
            else
            {
                tbl[i].hash = (((uint32_t)age + 1u) << 24) |
                              (tbl[i].hash & 0x3FFFFFu);
            }
        }
    }
}

/* ------------------------------------------------------------------ */
/* Lifecycle                                                           */
/* ------------------------------------------------------------------ */

EXPORT struct ft8d *ft8d_create(float f_min, float f_max, int sample_rate, int protocol)
{
    struct ft8d *me = (struct ft8d *)calloc(1, sizeof(struct ft8d));
    if (!me)
        return NULL;

    me->protocol = (protocol == 0) ? FTX_PROTOCOL_FT4 : FTX_PROTOCOL_FT8;
    me->sample_rate = sample_rate;
    me->f_min = f_min;
    me->f_max = f_max;

    me->cfg.f_min = f_min;
    me->cfg.f_max = f_max;
    me->cfg.sample_rate = sample_rate;
    me->cfg.time_osr = 2;
    me->cfg.freq_osr = 2;
    me->cfg.protocol = me->protocol;

    monitor_init(&me->mon, &me->cfg);
    me->frame_len = me->mon.subblock_size * me->cfg.time_osr;

    hashtable_init(me->hashtable);
    me->hash_if.lookup_hash = hashtable_lookup;
    me->hash_if.save_hash = hashtable_save_adapter;

    ft8d_active_instance = me;
    return me;
}

EXPORT void ft8d_destroy(struct ft8d *me)
{
    if (!me)
        return;
    monitor_free(&me->mon);
    if (ft8d_active_instance == me)
        ft8d_active_instance = NULL;
    free(me);
}

EXPORT void ft8d_reset(struct ft8d *me)
{
    monitor_reset(&me->mon);
    me->total_fed = 0;
}

EXPORT int ft8d_frame_len(struct ft8d *me) { return me->frame_len; }
EXPORT int ft8d_blocks_ready(struct ft8d *me) { return me->mon.wf.num_blocks; }
EXPORT int ft8d_blocks_max(struct ft8d *me) { return me->mon.wf.max_blocks; }

/* Feed a block of mono float32 samples at me->sample_rate.
 * Returns number of waterfall blocks produced (may be >1 or 0).       */
EXPORT int ft8d_feed(struct ft8d *me, const float *samples, int n)
{
    int produced = 0;
    int pos = 0;
    while (pos + me->frame_len <= n)
    {
        monitor_process(&me->mon, samples + pos);
        pos += me->frame_len;
        me->total_fed += me->frame_len;
        ++produced;
    }
    return produced;
}

/* Convenience: feed exactly one frame (frame_len samples).             */
EXPORT int ft8d_feed_frame(struct ft8d *me, const float *frame)
{
    monitor_process(&me->mon, frame);
    me->total_fed += me->frame_len;
    return me->mon.wf.num_blocks;
}

/* ------------------------------------------------------------------ */
/* SNR estimation                                                      */
/* ------------------------------------------------------------------ */

static float estimate_snr(const monitor_t *mon, const ftx_candidate_t *cand,
                          const uint8_t *tones, int n_sym)
{
    const ftx_waterfall_t *wf = &mon->wf;
    const int n_bins = wf->num_bins;
    const int t_osr = wf->time_osr;
    const int f_osr = wf->freq_osr;

    /* Global noise floor: median estimated from a 0.5 dB histogram.
     * O(n) and stable, unlike a sort of the whole waterfall. */
    static int hist[256];
    memset(hist, 0, sizeof(hist));
    long total = (long)wf->num_blocks * t_osr * f_osr * n_bins;
    long counted = 0;
    for (long i = 0; i < total; ++i)
    {
        int b = (int)wf->mag[i];
        if (b < 0)
            b = 0;
        if (b > 255)
            b = 255;
        hist[b]++;
        ++counted;
    }
    float noise = -120.0f;
    if (counted > 0)
    {
        long half = counted / 2, acc_c = 0;
        for (int b = 0; b < 256; ++b)
        {
            acc_c += hist[b];
            if (acc_c >= half)
            {
                noise = b * 0.5f - 120.0f;
                break;
            }
        }
    }

    int n_sym_used = 0;
    float acc = 0.0f;
    for (int s = 0; s < n_sym; ++s)
    {
        int blk = cand->time_offset + s;
        if (blk >= wf->num_blocks)
            break;
        int bin = cand->freq_offset + tones[s];
        if (bin < 0 || bin >= n_bins)
            continue;
        long off = (long)blk * wf->block_stride +
                   (long)cand->time_sub * f_osr * n_bins +
                   (long)cand->freq_sub * n_bins + bin;
        acc += WF_ELEM_MAG(wf->mag[off]);
        ++n_sym_used;
    }

    if (n_sym_used == 0)
        return 0.0f;

    float sig = acc / n_sym_used;
    /* 6.25 Hz bin -> 2500 Hz reference bandwidth (26 dB), plus a constant
     * correction calibrated against synthetic GFSK + AWGN references. */
    float snr = (sig - noise) - 39.2f;
    if (snr < -25.0f)
        snr = -25.0f;
    if (snr > 20.0f)
        snr = 20.0f;
    return snr;
}

/* ------------------------------------------------------------------ */
/* Decode a completed slot                                             */
/* ------------------------------------------------------------------ */

EXPORT int ft8d_decode(struct ft8d *me, int max_results, ft8d_result_t *out)
{
    const int kMin_score = 10;
    const int kMax_candidates = 140;
    const int kLDPC_iterations = 25;

    if (max_results > FT8D_MAX_RESULTS)
        max_results = FT8D_MAX_RESULTS;

    ft8d_active_instance = me;

    ftx_waterfall_t *wf = &me->mon.wf;
    ftx_candidate_t cand_list[kMax_candidates];
    int num_cand = ftx_find_candidates(wf, kMax_candidates, cand_list, kMin_score);

    ftx_message_t payloads[MAX_DECODED];
    ftx_message_t *seen[MAX_DECODED];
    for (int i = 0; i < MAX_DECODED; ++i)
        seen[i] = NULL;

    int n_out = 0;
    for (int i = 0; i < num_cand && n_out < max_results; ++i)
    {
        const ftx_candidate_t *cand = &cand_list[i];
        ftx_message_t msg;
        ftx_decode_status_t status;
        memset(&status, 0, sizeof(status));

        if (!ftx_decode_candidate(wf, cand, kLDPC_iterations, &msg, &status))
            continue;

        /* de-duplicate */
        bool dup = false;
        int idx = msg.hash % MAX_DECODED;
        for (int probe = 0; probe < MAX_DECODED; ++probe)
        {
            int k = (idx + probe) % MAX_DECODED;
            if (seen[k] == NULL)
            {
                seen[k] = &payloads[k];
                payloads[k] = msg;
                break;
            }
            if (seen[k]->hash == msg.hash &&
                0 == memcmp(seen[k]->payload, msg.payload, sizeof(msg.payload)))
            {
                dup = true;
                break;
            }
        }
        if (dup)
            continue;

        char text[FTX_MAX_MESSAGE_LENGTH];
        ftx_message_offsets_t offsets;
        memset(text, 0, sizeof(text));
        ftx_message_rc_t rc = ftx_message_decode(&msg, &me->hash_if, text, &offsets);

        ft8d_result_t *r = &out[n_out];
        memset(r, 0, sizeof(*r));
        if (rc != FTX_MESSAGE_RC_OK)
            snprintf(r->text, sizeof(r->text), "?? (unpack rc=%d)", (int)rc);
        else
            snprintf(r->text, sizeof(r->text), "%s", text);

        r->freq_hz = (me->mon.min_bin + cand->freq_offset +
                      (float)cand->freq_sub / wf->freq_osr) /
                     me->mon.symbol_period;
        r->time_s = (cand->time_offset +
                     (float)cand->time_sub / wf->time_osr) *
                    me->mon.symbol_period;
        uint8_t tones[FT8_NN];
        if (wf->protocol == FTX_PROTOCOL_FT8)
        {
            ft8_encode(msg.payload, tones);
            r->snr = estimate_snr(&me->mon, cand, tones, FT8_NN);
        }
        else
        {
            ft4_encode(msg.payload, tones);
            r->snr = estimate_snr(&me->mon, cand, tones, FT4_NN);
        }
        r->score = cand->score;
        r->ldpc_errors = status.ldpc_errors;
        r->flags = (strchr(r->text, '<') != NULL) ? 1 : 0;
        ++n_out;
    }

    hashtable_age(me->hashtable, 12);
    return n_out;
}

/* ------------------------------------------------------------------ */
/* Encoder                                                             */
/* ------------------------------------------------------------------ */

#define FT8_SYMBOL_BT 2.0f
#define FT4_SYMBOL_BT 1.0f
#define GFSK_CONST_K 5.336446f

static void gfsk_pulse(int n_spsym, float symbol_bt, float *pulse)
{
    for (int i = 0; i < 3 * n_spsym; ++i)
    {
        float t = i / (float)n_spsym - 1.5f;
        float arg1 = GFSK_CONST_K * symbol_bt * (t + 0.5f);
        float arg2 = GFSK_CONST_K * symbol_bt * (t - 0.5f);
        pulse[i] = (erff(arg1) - erff(arg2)) / 2;
    }
}

static void synth_gfsk(const uint8_t *symbols, int n_sym, float f0, float symbol_bt,
                       float symbol_period, int signal_rate, float *signal)
{
    int n_spsym = (int)(0.5f + signal_rate * symbol_period);
    int n_wave = n_sym * n_spsym;
    int n_total = n_wave + 2 * n_spsym;

    float *dphi = (float *)calloc(n_total, sizeof(float));
    float *pulse = (float *)calloc(3 * n_spsym, sizeof(float));
    if (!dphi || !pulse)
    {
        free(dphi);
        free(pulse);
        return;
    }

    float dphi_peak = 2 * (float)M_PI / n_spsym;
    for (int i = 0; i < n_total; ++i)
        dphi[i] = 2 * (float)M_PI * f0 / signal_rate;

    gfsk_pulse(n_spsym, symbol_bt, pulse);

    for (int i = 0; i < n_sym; ++i)
    {
        int ib = i * n_spsym;
        for (int j = 0; j < 3 * n_spsym; ++j)
            dphi[j + ib] += dphi_peak * symbols[i] * pulse[j];
    }
    for (int j = 0; j < 2 * n_spsym; ++j)
    {
        dphi[j] += dphi_peak * pulse[j + n_spsym] * symbols[0];
        dphi[j + n_sym * n_spsym] += dphi_peak * pulse[j] * symbols[n_sym - 1];
    }

    float phi = 0.0f;
    for (int k = 0; k < n_wave; ++k)
    {
        signal[k] = sinf(phi);
        phi = fmodf(phi + dphi[k + n_spsym], 2.0f * (float)M_PI);
    }

    int n_ramp = n_spsym / 8;
    for (int i = 0; i < n_ramp; ++i)
    {
        float env = (1 - cosf(2 * (float)M_PI * i / (2 * n_ramp))) / 2;
        signal[i] *= env;
        signal[n_wave - 1 - i] *= env;
    }

    free(dphi);
    free(pulse);
}

/* Encode a text message into a waveform.
 * Returns number of samples written, or a negative error code:
 *   -1 invalid args, -2 message could not be packed, -3 buffer too small */
EXPORT int ft8d_encode_text(struct ft8d *me, const char *text, float f0,
                            int sample_rate, float *out, int max_out)
{
    if (!text || !out || max_out <= 0)
        return -1;

    ftx_protocol_t proto = me ? me->protocol : FTX_PROTOCOL_FT8;
    ftx_message_t msg;
    ftx_message_init(&msg);

    ftx_callsign_hash_interface_t *hif = me ? &me->hash_if : NULL;
    ftx_message_rc_t rc = ftx_message_encode(&msg, hif, text);
    if (rc != FTX_MESSAGE_RC_OK)
        return -2;

    uint8_t tones[FT8_NN];
    if (proto == FTX_PROTOCOL_FT8)
        ft8_encode(msg.payload, tones);
    else
        ft4_encode(msg.payload, tones);

    float symbol_period = (proto == FTX_PROTOCOL_FT8) ? FT8_SYMBOL_PERIOD : FT4_SYMBOL_PERIOD;
    float bt = (proto == FTX_PROTOCOL_FT8) ? FT8_SYMBOL_BT : FT4_SYMBOL_BT;
    int n_sym = (proto == FTX_PROTOCOL_FT8) ? FT8_NN : FT4_NN;
    int n_spsym = (int)(0.5f + sample_rate * symbol_period);
    int n_wave = n_sym * n_spsym;

    if (n_wave > max_out)
        return -3;

    synth_gfsk(tones, n_sym, f0, bt, symbol_period, sample_rate, out);
    return n_wave;
}

/* Length in samples of one transmission at the given rate. */
EXPORT int ft8d_tx_samples(int sample_rate, int protocol)
{
    float sp = (protocol == 0) ? FT4_SYMBOL_PERIOD : FT8_SYMBOL_PERIOD;
    int nn = (protocol == 0) ? FT4_NN : FT8_NN;
    int n_spsym = (int)(0.5f + sample_rate * sp);
    return nn * n_spsym;
}

/* Validate/pack a message without generating audio. Returns 0 on success. */
EXPORT int ft8d_check_text(struct ft8d *me, const char *text, char *packed_out, int packed_len)
{
    ftx_message_t msg;
    ftx_message_init(&msg);
    ftx_message_rc_t rc = ftx_message_encode(&msg, me ? &me->hash_if : NULL, text);
    if (rc != FTX_MESSAGE_RC_OK)
        return (int)rc;
    if (packed_out && packed_len > 0)
    {
        ftx_message_offsets_t off;
        char tmp[FTX_MAX_MESSAGE_LENGTH];
        ftx_message_decode(&msg, me ? &me->hash_if : NULL, tmp, &off);
        snprintf(packed_out, packed_len, "%s", tmp);
    }
    return 0;
}
