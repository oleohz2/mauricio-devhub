"""Synthesizes the soundtrack: 120 BPM, A minor (Am-F-C-G), with SFX on the same grid and key."""
import numpy as np
import wave

SR = 48000
DUR = 22.0
N = int(SR * DUR)
BEAT = 0.5
BAR = 2.0
rng = np.random.default_rng(7)


def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def place(buf, sig, t, gain=1.0):
    i = int(round(t * SR))
    if i >= len(buf):
        return
    sig = sig[: len(buf) - i]
    buf[i:i + len(sig)] += sig * gain


def env(n, a=0.005, d=0.3, sustain=0.0, rel=None):
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4)) * (sustain + (1 - sustain) * np.exp(-t / d))
    if rel:
        r = int(rel * SR)
        e[-r:] *= np.linspace(1, 0, r)
    return e


def lowpass(x, cutoff):
    # one-pole lowpass (cutoff may be an array)
    a = np.exp(-2 * np.pi * np.asarray(cutoff) / SR) * np.ones(len(x))
    y = np.zeros_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a[i]) * x[i] + a[i] * acc
        y[i] = acc
    return y


def lp_fast(x, cutoff, passes=2):
    # cheap fixed-cutoff lowpass via repeated one-pole using lfilter-like recurrence in numpy
    from itertools import accumulate  # noqa
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = x
    for _ in range(passes):
        out = np.empty_like(y)
        acc = 0.0
        b = 1 - a
        for i, v in enumerate(y):
            acc = b * v + a * acc
            out[i] = acc
        y = out
    return y


def saw(f, n, detune=0.0):
    t = np.arange(n) / SR
    out = np.zeros(n)
    for d in (-detune, 0, detune):
        ph = (t * f * (1 + d)) % 1.0
        out += 2 * ph - 1
    return out / 3


def tri(f, n):
    t = np.arange(n) / SR
    return 2 * np.abs(2 * ((t * f) % 1.0) - 1) - 1


def sine(f, n):
    return np.sin(2 * np.pi * f * np.arange(n) / SR)


# ---- chords: Am F C G (one per 2s bar)
CHORDS = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]  # A3 C4 E4 | F3 A3 C4 | C3 E3 G3 | G3 B3 D4
ROOTS = [45, 41, 48, 43]  # A2 F2 C3 G2

drums = np.zeros(N)
bass = np.zeros(N)
pad = np.zeros(N)
arp = np.zeros(N)
sfx = np.zeros(N)

DROP = 3.5      # full beat enters with the reveal
END_HIT = 21.0  # last downbeat: final chord rings out

# --- pad (whole piece), slowly opening filter
for bar in range(11):
    t0 = bar * BAR
    n = int(BAR * SR) + int(0.3 * SR)
    ch = CHORDS[bar % 4] if t0 < END_HIT else CHORDS[0]
    sig = sum(saw(mtof(m), n, 0.004) for m in ch) / 3
    sig += 0.5 * sine(mtof(ch[0] - 12), n)
    e = env(n, a=0.25, d=10, sustain=1, rel=0.3)
    place(pad, sig * e, t0)
pad = lp_fast(pad, 1400, passes=2)

# final held chord
n = int(1.0 * SR)
final = sum(saw(mtof(m), n, 0.004) for m in [57, 60, 64, 69]) / 4
place(pad, lp_fast(final * env(n, a=0.01, d=0.5, sustain=0.0), 2000), END_HIT, 0.9)

# --- arp: 8th-note plucks of chord tones, an octave up
for k in range(int(END_HIT / 0.25)):
    t0 = k * 0.25
    bar = int(t0 // BAR)
    ch = CHORDS[bar % 4]
    pattern = [0, 1, 2, 1, 0, 2, 1, 2]
    m = ch[pattern[k % 8]] + 12
    n = int(0.35 * SR)
    sig = (tri(mtof(m), n) * 0.7 + sine(mtof(m + 12), n) * 0.3) * env(n, a=0.002, d=0.09)
    g = 0.55 if t0 < DROP else 0.8
    place(arp, sig, t0, g)
arp = lp_fast(arp, 3500, passes=1)

# --- bass: 8ths from the drop
for k in range(int(DROP / 0.25), int(END_HIT / 0.25)):
    t0 = k * 0.25
    root = ROOTS[int(t0 // BAR) % 4]
    m = root + (12 if k % 4 == 3 else 0)
    n = int(0.24 * SR)
    sig = saw(mtof(m), n, 0.002) * 0.6 + sine(mtof(m), n) * 0.6
    place(bass, sig * env(n, a=0.004, d=0.12, sustain=0.3, rel=0.02), t0)
place(bass, sine(mtof(33), int(1.0 * SR)) * env(int(1.0 * SR), a=0.004, d=0.4), END_HIT, 0.9)
bass = lp_fast(bass, 500, passes=2)

# --- drums
def kick():
    n = int(0.4 * SR)
    t = np.arange(n) / SR
    f = 45 + 85 * np.exp(-t / 0.035)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t / 0.16) + 0.15 * rng.standard_normal(n) * np.exp(-t / 0.004)


def clap():
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    noise = noise - lp_fast(noise, 900, passes=1)
    e = np.exp(-t / 0.06) * (1 + 0.6 * np.sin(2 * np.pi * 90 * t) * (t < 0.02))
    return noise * e


def hat():
    n = int(0.08 * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    noise = noise - lp_fast(noise, 6000, passes=1)
    return noise * np.exp(-t / 0.018)


K, C, H = kick(), clap(), hat()
kick_times = []
for b in range(int(DROP / BEAT), int(END_HIT / BEAT)):
    t0 = b * BEAT
    place(drums, K, t0, 1.0)
    kick_times.append(t0)
    if b % 2 == 1:
        place(drums, C, t0, 0.32)
place(drums, K, END_HIT, 1.0)
kick_times.append(END_HIT)
for k in range(int(END_HIT / 0.25)):
    t0 = k * 0.25
    if t0 < 1.0:
        continue
    g = 0.10 if k % 2 == 1 else 0.05
    if t0 < DROP:
        g *= 0.7
    place(drums, H, t0, g)

# --- sidechain pump on pad + bass from each kick
duck = np.ones(N)
for t0 in kick_times:
    i = int(t0 * SR)
    n = min(int(0.4 * SR), N - i)
    tt = np.arange(n) / SR
    duck[i:i + n] = np.minimum(duck[i:i + n], 1 - 0.55 * np.exp(-tt / 0.12))

# --- SFX (same key, soft)
def whoosh(length=0.45):
    n = int(length * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    sweep = 300 + 3500 * (t / length) ** 2
    y = lowpass(noise, sweep)
    y = y - lp_fast(y, 200, passes=1)
    return y * (t / length) ** 2 * np.exp(-np.maximum(0, t - length + 0.02) / 0.01)


def pluck(m, d=0.25):
    n = int(0.6 * SR)
    return (sine(mtof(m), n) + 0.3 * sine(mtof(m + 12), n)) * env(n, a=0.002, d=d)


def tick():
    n = int(0.03 * SR)
    t = np.arange(n) / SR
    return sine(mtof(93), n) * np.exp(-t / 0.006)  # A6, tiny


W = whoosh()
for cut in (3.5, 7.0, 11.5, 15.5, 18.5):
    place(sfx, W, cut - len(W) / SR, 0.22)
# riser into the drop
n = int(1.0 * SR)
place(sfx, whoosh(1.0), DROP - 1.0, 0.25)

# hook words: A5 C6 E6
for t0, m in ((0.0, 81), (0.25, 84), (0.5, 88)):
    place(sfx, pluck(m, 0.2), t0, 0.22)
# answer line lands (1.5): soft A-minor bell
for m in (69, 72, 76, 81):
    place(sfx, pluck(m, 0.5), 1.5, 0.08)
# service cards (7.5, 8, 8.5) and chips (9, 9.25, 9.5)
for t0, m in ((7.5, 76), (8.0, 79), (8.5, 81)):
    place(sfx, pluck(m, 0.15), t0, 0.12)
for t0, m in ((9.0, 88), (9.25, 91), (9.5, 93)):
    place(sfx, pluck(m, 0.08), t0, 0.08)
# project cards (12, 12.5, 13)
for t0 in (12.0, 12.5, 13.0):
    place(sfx, whoosh(0.25), t0 - 0.2, 0.12)
# hover on Goblin Planet (14.0)
place(sfx, pluck(84, 0.1), 14.0, 0.07)
# typing ticks: name at 8 cps from 16.0, message at 16 cps from 16.5
for k in range(1, 4):
    place(sfx, tick(), 16.0 + k / 8, 0.10)
for k in range(1, 20):
    place(sfx, tick(), 16.5 + k / 16, 0.07)
# button click (17.75) + success chime
place(sfx, tick(), 17.75, 0.25)
for i, m in enumerate((81, 84, 88, 93)):
    place(sfx, pluck(m, 0.35), 17.75 + i * 0.0625, 0.10)
# CTA lands (19.75)
place(sfx, pluck(81, 0.4), 19.75, 0.12)
place(sfx, pluck(88, 0.4), 19.75, 0.08)

# ---- mix
mix = (drums * 0.45 + bass * 0.9 * duck + pad * 0.35 * duck + arp * 0.4 + sfx * 0.9)
# tiny stereo: arp slightly right, sfx centered
L = mix - arp * 0.05
R = mix + arp * 0.05
st = np.stack([L, R], axis=1)
for name, x in (('drums', drums*0.45), ('bass', bass*0.75*duck), ('pad', pad*0.35*duck), ('arp', arp*0.32), ('sfx', sfx*0.9)):
    print(f'{name:6s} peak {np.max(np.abs(x)):.2f} rms {np.sqrt(np.mean(x[int(4*SR):int(20*SR)]**2)):.3f}')
print('pre-limit peak', np.max(np.abs(st)))
st = st / np.max(np.abs(st))
st = np.tanh(st * 1.5) / np.tanh(1.5)
# fade in 10ms, fade out last 0.8s
fi = int(0.01 * SR)
st[:fi] *= np.linspace(0, 1, fi)[:, None]
fo = int(0.8 * SR)
st[-fo:] *= np.linspace(1, 0, fo)[:, None] ** 1.5
st *= 0.89 / np.max(np.abs(st))

with wave.open('music.wav', 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((st * 32767).astype(np.int16).tobytes())
print('ok', st.shape)
