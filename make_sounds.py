"""Synthesize the three UI cues into assets/sounds (offline stand-ins for bencho.dev sounds)."""
import math, struct, wave, os
SR = 22050
def tone(freqs, dur, vol=0.35, decay=9):
    n = int(SR * dur); out = []
    for i in range(n):
        t = i / SR
        env = math.exp(-decay * t) * min(1, i / 80)
        out.append(sum(math.sin(2 * math.pi * f * t) for f in freqs) / len(freqs) * env * vol)
    return out
def save(name, samples):
    os.makedirs("assets/sounds", exist_ok=True)
    with wave.open(f"assets/sounds/{name}.wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples))
save("click-tactile", tone([1800, 900], 0.04, 0.5, 90))
save("confirm-chime", tone([660], 0.12, 0.4, 14) + tone([990], 0.22, 0.4, 10))
save("alert-pulse", tone([880], 0.18, 0.45, 8) + [0] * int(SR * 0.06) + tone([880], 0.18, 0.45, 8))
