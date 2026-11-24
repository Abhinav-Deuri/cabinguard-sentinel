"""CabinGuard parent companion dashboard. Run: streamlit run app.py"""
import html
from pathlib import Path

import pandas as pd
import streamlit as st

import bencho_components as bc
from serial_worker import BAUD, Hub, list_serial_ports
from telemetry_charts import CONFIG, build_figure

st.set_page_config(page_title="CabinGuard", layout="wide", initial_sidebar_state="collapsed")
st.markdown(f"<style>{(Path(__file__).parent / 'styles.css').read_text()}</style>", unsafe_allow_html=True)


@st.cache_resource
def get_hub():
    return Hub()


hub = get_hub()
S = st.session_state
S.setdefault("tick", 0)
S.setdefault("prev", {})
S.setdefault("snd_seq", None)
S.setdefault("click", False)
S.setdefault("frozen", None)

BANNER = {
    "SECURE": ("SECURE", "var(--secure)"),
    "ALERT": ("CHILD DETECTED — LOCKED", "var(--alert)"),
    "CRITICAL": ("CRITICAL HEAT — COOLING ACTIVE", "var(--critical)"),
    "HYSTERESIS": ("COOLING (HYSTERESIS HOLD)", "var(--critical)"),
    "FAIL-SAFE": ("SENSOR FAULT — FAIL-SAFE COOLING", "var(--failsafe)"),
    "MANUAL VENT": ("MANUAL VENTILATION", "var(--failsafe)"),
    "LINK LOST": ("LINK LOST — STALE DATA", "var(--off)"),
}
BUZ = ["OFF", "PULSE", "CONTINUOUS"]

# ------------------------------------------------------------------ header / source / port
ports = list_serial_ports()
with st.sidebar:
    st.html('<div class="brand"><i>CG</i><div><b>CabinGuard</b><small>Parent companion</small></div></div>')
    src = st.segmented_control("Data source", ["Live Serial", "Viva Demo Simulator"],
                               default="Viva Demo Simulator", key="src") or "Viva Demo Simulator"
    chosen = None
    if src == "Live Serial":
        labels = {p["port"]: f'{p["port"]} — {p["description"] or "unknown"}'
                             f'{"  [ARDUINO]" if p["arduino"] else ""}' for p in ports}
        if ports:
            chosen = st.selectbox("Serial port", list(labels), format_func=labels.get, key="port_sel")
        else:
            st.selectbox("Serial port", ["No serial ports found"], disabled=True)
        hub.configure("serial", chosen)
    else:
        st.selectbox("Serial port", ["(simulator — no hardware)"], disabled=True)
        hub.configure("sim")
    S["sound"] = st.toggle("Sound", value=True)

with st.expander(f"Detected serial ports ({len(ports)}) — pyserial", expanded=(src == "Live Serial" and not ports)):
    if ports:
        df_ports = pd.DataFrame(ports).rename(columns={"port": "Port", "description": "Description",
                                                       "manufacturer": "Manufacturer", "vid:pid": "VID:PID",
                                                       "arduino": "Arduino?"})
        df_ports["Connected"] = df_ports["Port"].eq(chosen) if src == "Live Serial" else False
        st.dataframe(df_ports, hide_index=True, width="stretch")
    else:
        st.warning("pyserial sees no serial ports. Plug in the Arduino Uno via USB, then rerun.")
    st.caption(f"Baud {BAUD}. Auto-flags Arduino / CH340 / FTDI / CP210x adapters. "
               "Close the Arduino IDE Serial Monitor first: only one program can hold the port.")


# ------------------------------------------------------------------ live cards
def roll(key, value, decimals, unit):
    prev = S["prev"].get(key)
    S["prev"][key] = value
    return bc.rolling_counter(value, prev, decimals, unit, S["tick"])


@st.fragment(run_every="1s")
def live_top():
    snap = hub.snapshot()
    S["tick"] += 1
    r, thr, lost = snap["last"], snap["threshold"], snap["lost"]
    state = snap["state"]
    text, color = BANNER[state]

    port_txt = "SIMULATOR" if snap["source"] == "sim" else (snap["port"] or "NO PORT")
    link = "bad" if lost else "on"
    age_txt = "" if snap["age"] is None else " %.1fs" % snap["age"]
    chips = (f'<span class="chip {link}">{html.escape(port_txt)} • {BAUD}</span>'
             f'<span class="chip">{html.escape(snap["status"])}</span>'
             f'<span class="chip {link}">{("LINK LOST" if lost else "LINK OK") + age_txt}</span>')
    st.html(f'<div class="head"><div><div class="micro">Live cabin telemetry</div><h1>Cabin Monitor</h1></div>'
            f'<div>{chips}</div></div>')

    if r is None:
        st.html(f'<div class="card status" style="--c:{color}"><h2>{text}</h2><span class="sub">waiting for first packet</span></div>')
        return

    t = r["t"]
    delta = "SENSOR NaN" if t is None else f"{t - thr:+.1f}°C vs limit"
    occ_txt = "OCCUPIED" if r["occ"] else "EMPTY"
    occ_c = "var(--alert)" if r["occ"] else "var(--secure)"
    chip = lambda label, on, c: f'<span class="pill {"on" if on else ""}" style="--c:{c}">{label}</span>'
    cards = f"""
<div class="{'stale' if lost else ''}"><div class="grid">
 <div class="card"><div class="top"><span class="ico" style="--c:var(--alert)">T</span><span class="micro">Cabin temperature</span></div>
  {roll("t", t, 1, "°C")}<div class="sub">{delta}</div>{bc.thermal_meter(t, thr)}</div>
 <div class="card"><div class="top"><span class="ico" style="--c:{occ_c}">S</span><span class="micro">Seat · HC-SR04</span></div>
  {roll("d", r["d"], 1, "cm")}
  <div class="pills">{chip(occ_txt, True, occ_c)}{chip("LOCKED" if r["lock"] else "UNLOCKED", r["lock"], "var(--alert)")}</div></div>
 <div class="card"><div class="top"><span class="ico" style="--c:var(--hum)">H</span><span class="micro">Relative humidity</span></div>
  {roll("h", r["h"], 0, "%")}<div class="sub">Rapid rise = hair-dryer test</div></div>
 <div class="card status" style="--c:{color}"><div class="top"><span class="ico" style="--c:{color}">!</span><span class="micro">System state</span></div>
  <h2>{text}</h2><span class="tag">THR {thr:g}°C · REL {thr - 1:g}°C</span>
  <div class="sub" style="margin-top:10px">MODE {r["mode"]}{" · MUTED" if r["sil"] else ""}</div></div>
</div>
<div class="panel"><div class="micro">Actuator telemetry</div><div class="pills" style="margin-top:10px">
   {chip("FAN: " + ("ON" if r["fan"] else "OFF"), r["fan"], "var(--secure)")}
   {chip(f'WINDOW: {r["srv"]}°', r["srv"], "var(--failsafe)")}
   {chip("BUZZER: " + BUZ[min(r["buz"], 2)], r["buz"], "var(--critical)")}
   <span class="sub" style="margin-left:auto;align-self:center">D7 relay · D9 servo · D8 buzzer</span></div></div>
</div>"""
    st.html(cards)

    # sounds: newest unseen event wins
    evs = snap["events"]
    top = evs[0]["seq"] if evs else 0
    if S["snd_seq"] is None:
        S["snd_seq"] = top
    new = [e for e in evs if e["seq"] > S["snd_seq"]]
    S["snd_seq"] = top
    cue = None
    if S["click"]:
        cue, S["click"] = "click-tactile", False
    if any(e["kind"] == "ack" for e in new):
        cue = "confirm-chime"
    if any(e["kind"] == "alert" for e in new):
        cue = "alert-pulse"
    if cue and S.get("sound"):
        bc.play_sound(cue, top)


# ------------------------------------------------------------------ command deck
@st.fragment
def command_deck():
    st.markdown('<div class="micro">Parental command deck</div>', unsafe_allow_html=True)
    snap = hub.snapshot()
    applied = snap["threshold"]
    a, b = st.columns([3, 1.2], vertical_alignment="bottom")
    val = a.slider("Temperature threshold (°C)", 20.0, 45.0, applied, 0.5, key="thr_ui",
                   help="Critical cooling starts at or above this; fan stays on until 1 °C below.")
    dirty = abs(val - applied) > 0.01
    if b.button(f"Apply threshold (SET:{val:g})", type="primary" if dirty else "secondary", width="stretch"):
        S["click"] = True
        hub.send(f"SET:{val:g}")
    st.caption(f"Applied on board: **{applied:g} °C**" + ("  ·  unsent change" if dirty else ""))
    b1, b2, b3 = st.columns(3)
    for col, label, cmd in ((b1, "Manual ventilate", "VENT"), (b2, "Silence alarm", "SILENCE"),
                            (b3, "Auto mode", "AUTO")):
        if col.button(label, key=f"btn_{cmd}", width="stretch"):
            S["click"] = True
            hub.send(cmd)
    st.html(bc.toast_stack(hub.snapshot()["events"]))

    if hub.source == "sim":
        with st.expander("Simulator manual inputs (override the scripted scenario)"):
            bd = hub.board
            bd.manual = st.toggle("Manual control", value=bd.manual)
            s1, s2, s3 = st.columns(3)
            bd.m_temp = s1.slider("Cabin temperature (°C)", 15.0, 50.0, float(bd.m_temp), 0.5)
            bd.m_hum = s2.slider("Humidity (%)", 20.0, 90.0, float(bd.m_hum), 1.0)
            bd.m_dist = s3.slider("Seat distance (cm)", 2.0, 40.0, float(bd.m_dist), 0.5)
            bd.m_lock = int(st.toggle("Car locked", value=bool(bd.m_lock)))


# ------------------------------------------------------------------ toolbar
@st.fragment
def toolbar():
    st.markdown('<div class="micro">Real-time sensor telemetry suite</div>', unsafe_allow_html=True)
    a, b, c = st.columns([3, 1.4, 1.4], vertical_alignment="center")
    a.segmented_control("Window", ["30s", "2m", "10m"], default="2m", key="win", label_visibility="collapsed")
    paused = b.toggle("Pause stream", key="paused")
    c.toggle("Humidity", value=True, key="show_hum")
    if paused and S["frozen"] is None:
        S["frozen"] = hub.snapshot()["rows"]
    if not paused:
        S["frozen"] = None


# ------------------------------------------------------------------ charts + tables
def acceptance(rows, events, thr):
    """Evaluate the CA4 acceptance tests from the telemetry seen so far."""
    emp = [r["d"] for r in rows if r["d"] is not None and not r["occ"]]
    occ = [r["d"] for r in rows if r["d"] is not None and r["occ"]]
    delay = None
    start = None
    for i, r in enumerate(rows):
        prev = rows[i - 1] if i else None
        if r["lock"] and r["occ"] and (prev is None or not prev["lock"]):
            start = r["ts"]
        if start and r["buz"] >= 1:
            delay = (r["ts"] - start).total_seconds()
            start = None
    crit = any(r["fan"] and r["t"] is not None and r["t"] >= r["thr"] for r in rows)
    hyst = any(r["state"] == "HYSTERESIS" for r in rows)
    fsafe = any(r["t"] is None and r["fan"] for r in rows)
    ack = any(e["kind"] == "ack" for e in events)
    lost = any("LINK LOST" in e["text"] for e in events)
    ok = lambda b: "PASS" if b else "pending"
    return pd.DataFrame([
        ["Detect child in seat", "~25 cm empty, ~6 cm doll",
         f"empty {sum(emp) / len(emp):.1f} cm · seated {sum(occ) / len(occ):.1f} cm" if emp and occ else "—",
         ok(emp and occ and sum(emp) / len(emp) > 20 and sum(occ) / len(occ) < 12)],
        ["Alert parents", "beeps 10 ± 1 s after lock", "—" if delay is None else f"{delay:.1f} s",
         ok(delay is not None and 9 <= delay <= 11)],
        ["Ventilate if hot", f"fan + window at ≥ {thr:g} °C", "fan on above limit" if crit else "—", ok(crit)],
        ["Hysteresis", "fan holds until < threshold − 1 °C", "hold observed" if hyst else "—", ok(hyst)],
        ["Parental control", "SET / VENT / SILENCE ACK", "ACK received" if ack else "—", ok(ack)],
        ["Missing data: NaN", "NaN starts ventilation", "fan on during NaN" if fsafe else "—", ok(fsafe)],
        ["Missing data: USB", "LINK LOST within 3 s", "LINK LOST logged" if lost else "—", ok(lost)],
    ], columns=["Requirement", "Test", "Observed", "Status"])


@st.fragment(run_every="1s")
def live_charts():
    snap = hub.snapshot()
    rows = S["frozen"] if S["frozen"] is not None else snap["rows"]
    thr = snap["threshold"]
    secs = {"30s": 30, "2m": 120, "10m": 600}[S.get("win") or "2m"]
    if not rows:
        st.info("No telemetry yet.")
        return
    cutoff = rows[-1]["ts"].timestamp() - secs
    view = [r for r in rows if r["ts"].timestamp() >= cutoff]

    df = pd.DataFrame(rows).drop(columns=["failsafe"])
    st.download_button("Export CSV", df.to_csv(index=False), "cabinguard_telemetry.csv", "text/csv",
                       key="csv")
    st.plotly_chart(build_figure(view, thr, secs, S.get("show_hum", True)), width="stretch",
                    config=CONFIG, key="telemetry")

    t_tel, t_evt, t_acc, t_pins = st.tabs(["Telemetry packets", "Event & command audit log",
                                           "Acceptance tests", "Pin map"])
    with t_tel:
        tbl = pd.DataFrame(rows[-15:][::-1])[["ts", "t", "h", "d", "occ", "lock", "fan", "srv", "buz", "thr",
                                              "mode", "state"]]
        tbl["ts"] = tbl["ts"].dt.strftime("%H:%M:%S")
        tbl.columns = ["Time", "T °C", "RH %", "D cm", "OCC", "LOCK", "FAN", "SRV °", "BUZ", "THR", "MODE", "State"]
        st.dataframe(tbl, hide_index=True, width="stretch")
    with t_evt:
        ev = pd.DataFrame(snap["events"][:60])
        if len(ev):
            ev["ts"] = ev["ts"].dt.strftime("%H:%M:%S")
            st.dataframe(ev[["ts", "kind", "text"]].rename(columns={"ts": "Time", "kind": "Type", "text": "Event"}),
                         hide_index=True, width="stretch")
    with t_acc:
        st.dataframe(acceptance(snap["rows"], snap["events"], thr), hide_index=True, width="stretch")
    with t_pins:
        st.dataframe(pd.DataFrame([
            ["HC-SR04", "TRIG D2 / ECHO D3", "Seat distance (cm)"], ["DHT11", "D4", "Temp °C, humidity %"],
            ["Push button", "D12 (INPUT_PULLUP)", "Car locked"], ["SG90 servo", "D9", "Window 0° / 90°"],
            ["Buzzer", "D8", "Alarm"], ["Relay + 5 V fan", "D7", "Ventilation"],
            ["LEDs 220 Ω", "D10 green / D11 red", "Status"]], columns=["Part", "Pin", "Function"]),
            hide_index=True, width="stretch")


live_top()
command_deck()
toolbar()
live_charts()
