"""HTML/CSS widgets styled after bencho.dev blocks: rolling counter, segmented meter, toast stack, sound player."""
import base64
import html
from pathlib import Path

import streamlit.components.v1 as components

SOUND_DIR = Path(__file__).parent / "assets" / "sounds"
_SOUNDS = {}


def _sound_b64(name):
    if name not in _SOUNDS:
        _SOUNDS[name] = base64.b64encode((SOUND_DIR / f"{name}.wav").read_bytes()).decode()
    return _SOUNDS[name]


def rolling_counter(value, prev, decimals, unit, tick):
    """Digits roll vertically from prev to value. Alternating animation name restarts it each tick."""
    fmt = f"{{:.{decimals}f}}"
    cur = "--" if value is None else fmt.format(value)
    old = cur if prev is None or value is None else fmt.format(prev)
    old = old.rjust(len(cur), " ")[-len(cur):] if len(old) >= len(cur) else old.rjust(len(cur), "0")
    cells = []
    frac = False
    for c, o in zip(cur, old):
        if c == ".":
            frac = True
        if c.isdigit():
            f = o if o.isdigit() else c
            strip = "".join(f"<i>{n}</i>" for n in range(10))
            cells.append(f'<span class="rc-d{" dim" if frac else ""}"><b class="roll-{"ab"[tick % 2]}" '
                         f'style="--from:{f};--to:{c}">{strip}</b></span>')
        else:
            cells.append(f'<span class="rc-s">{html.escape(c)}</span>')
    return f'<div class="rc">{"".join(cells)}<span class="rc-u">{html.escape(unit)}</span></div>'


def thermal_meter(temp, thr, lo=20.0):
    """Segmented bar: emerald -> amber -> crimson, with release (thr-1) and limit (thr) ticks."""
    hi = thr + 5
    n = 30
    seg = (hi - lo) / n
    out = []
    for i in range(n):
        edge = lo + (i + 1) * seg
        on = temp is not None and temp >= lo + i * seg + seg * 0.5
        mid = lo + (i + 0.5) * seg
        col = "var(--secure)" if mid < thr - 3 else "var(--alert)" if mid < thr else "var(--critical)"
        out.append(f'<s class="{"on" if on else ""}" style="--c:{col}"></s>')
    pos = lambda v: max(0, min(100, (v - lo) / (hi - lo) * 100))
    return (f'<div class="meter">{"".join(out)}'
            f'<u style="left:{pos(thr - 1):.1f}%"><em class="up">REL {thr - 1:g}</em></u>'
            f'<u class="lim" style="left:{pos(thr):.1f}%"><em>LIMIT {thr:g}</em></u></div>')


def toast_stack(events):
    """Latest command / ack cards."""
    cards = []
    for e in events:
        if e["kind"] not in ("cmd", "ack", "nack"):
            continue
        label = {"cmd": "PC → ARDUINO", "ack": "ARDUINO → PC", "nack": "TIMEOUT"}[e["kind"]]
        cards.append(f'<div class="toast {e["kind"]}"><span>{label}</span>'
                     f'<b>{html.escape(e["text"])}</b><time>{e["ts"]:%H:%M:%S}</time></div>')
        if len(cards) == 3:
            break
    return f'<div class="toasts">{"".join(cards) or "<div class=toast><span>NO COMMANDS YET</span></div>"}</div>'


def play_sound(name, nonce):
    """Zero-height iframe that plays one cue. nonce forces a fresh iframe per event."""
    components.html(
        f'<audio autoplay src="data:audio/wav;base64,{_sound_b64(name)}"></audio><!--{nonce}-->', height=0)
