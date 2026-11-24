"""Single synchronized Plotly figure: thermal+humidity / ultrasonic / actuator step timeline."""
from datetime import timedelta

import plotly.graph_objects as go
from plotly.subplots import make_subplots

BG, SURF, BORDER = "rgba(0,0,0,0)", "#16191E", "#2A2F38"
TXT, MUTED = "#F3F4F6", "#9CA3AF"
SECURE, ALERT, CRIT, FAILSAFE, HUM = "#10B981", "#F59E0B", "#EF4444", "#3B82F6", "#38BDF8"
MONO = "JetBrains Mono, Consolas, monospace"


def zone_color(t, thr):
    if t is None:
        return FAILSAFE
    return CRIT if t >= thr else ALERT if t >= thr - 3 else SECURE


def _rgba(hex_, a):
    h = hex_.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def build_figure(rows, thr, window_s, show_hum=True):
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.44, 0.22, 0.34],
        specs=[[{"secondary_y": True}], [{}], [{}]],
        subplot_titles=("CABIN TEMPERATURE & HUMIDITY", "SEAT PROXIMITY HC-SR04", "ACTUATOR & LOCK TIMELINE"))
    x = [r["ts"] for r in rows]
    last_t = next((r["t"] for r in reversed(rows) if r["t"] is not None), None)
    col = zone_color(last_t, thr)

    # --- 1. thermal
    fig.add_hrect(y0=thr - 1, y1=thr, fillcolor=_rgba(CRIT, 0.12), line_width=0, row=1, col=1, secondary_y=False)
    fig.add_hline(y=thr, line=dict(color=CRIT, width=1, dash="dash"), row=1, col=1,
                  annotation_text=f"THRESHOLD {thr:g}°C", annotation_font=dict(size=10, color=MUTED, family=MONO),
                  annotation_position="top left")
    fig.add_trace(go.Scatter(
        x=x, y=[r["t"] for r in rows], name="Temp °C", mode="lines", connectgaps=False,
        line=dict(color=col, width=2.5, shape="spline", smoothing=0.5),
        fill="tozeroy", fillcolor=_rgba(col, 0.12),
        customdata=[[(r["t"] - thr) if r["t"] is not None else None, r["state"]] for r in rows],
        hovertemplate="Temp %{y:.1f} °C<br>ΔT %{customdata[0]:+.1f} °C<br>State %{customdata[1]}<extra></extra>"),
        row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(
        x=x, y=[r["h"] for r in rows], name="Humidity %", mode="lines", connectgaps=False,
        line=dict(color=HUM, width=1.5, dash="dash"), visible=True if show_hum else "legendonly",
        hovertemplate="Humidity %{y:.0f} %<extra></extra>"), row=1, col=1, secondary_y=True)
    fs = [r["ts"] for r in rows if r["t"] is None]
    if fs:
        fig.add_trace(go.Scatter(x=fs, y=[thr - 4] * len(fs), mode="markers+text", text=["FAIL-SAFE"] * len(fs),
                                 textposition="top center", textfont=dict(size=9, color=FAILSAFE, family=MONO),
                                 marker=dict(symbol="x", color=FAILSAFE, size=8), name="Fail-safe",
                                 hoverinfo="skip", showlegend=False), row=1, col=1, secondary_y=False)
    temps = [r["t"] for r in rows if r["t"] is not None] + [thr]
    fig.update_yaxes(range=[min(temps) - 3, max(temps) + 2], title_text="°C", row=1, col=1, secondary_y=False)
    fig.update_yaxes(range=[0, 100], title_text="% RH", showgrid=False, row=1, col=1, secondary_y=True)

    # --- 2. ultrasonic
    fig.add_hrect(y0=0, y1=12, fillcolor="rgba(245,158,11,0.10)", line_width=0, row=2, col=1)
    fig.add_hline(y=12, line=dict(color=ALERT, width=1, dash="dot"), row=2, col=1,
                  annotation_text="OCCUPIED THRESHOLD (< 12 cm)", annotation_position="top left",
                  annotation_font=dict(size=10, color=ALERT, family=MONO))
    fig.add_trace(go.Scatter(x=x, y=[r["d"] for r in rows], name="Distance cm", mode="lines",
                             line=dict(color=TXT, width=1.5, shape="hv"),
                             hovertemplate="Seat %{y:.1f} cm<extra></extra>"), row=2, col=1)
    fig.update_yaxes(range=[0, 40], title_text="cm", row=2, col=1)

    # --- 3. step ribbon (each track occupies a 1-unit lane)
    tracks = [("CAR LOCK", [r["lock"] for r in rows], 1, ALERT, 6, lambda v: "LOCKED" if v else "UNLOCKED"),
              ("COOLING FAN", [r["fan"] for r in rows], 1, SECURE, 4.5, lambda v: "ON" if v else "OFF"),
              ("WINDOW SERVO", [r["srv"] for r in rows], 90, FAILSAFE, 3, lambda v: f"{v:g}°"),
              ("ALARM BUZZER", [r["buz"] for r in rows], 2, CRIT, 1.5,
               lambda v: ["OFF", "PULSE", "CONTINUOUS"][int(v)])]
    for name, vals, vmax, c, base, lab in tracks:
        fig.add_trace(go.Scatter(x=x, y=[base] * len(x), mode="lines", line=dict(width=0), hoverinfo="skip",
                                 showlegend=False), row=3, col=1)
        fig.add_trace(go.Scatter(x=x, y=[base + 0.9 * v / vmax for v in vals], name=name, mode="lines",
                                 line=dict(color=c, width=1.5, shape="hv"), fill="tonexty",
                                 fillcolor=_rgba(c, 0.22), showlegend=False,
                                 text=[lab(v) for v in vals], hovertemplate=name + ": %{text}<extra></extra>"),
                      row=3, col=1)
    fig.update_yaxes(range=[1, 7.1], tickvals=[t[4] + 0.45 for t in tracks],
                     ticktext=[t[0] for t in tracks], showgrid=False, row=3, col=1)

    # --- shared styling
    if rows:
        end = rows[-1]["ts"]
        fig.update_xaxes(range=[end - timedelta(seconds=window_s), end + timedelta(seconds=1)])
    fig.update_xaxes(gridcolor=BORDER, linecolor=BORDER, tickformat="%H:%M:%S", showspikes=True,
                     spikecolor=MUTED, spikethickness=1, spikemode="across")
    fig.update_yaxes(gridcolor=BORDER, zeroline=False, linecolor=BORDER)
    fig.update_layout(
        height=760, margin=dict(l=10, r=10, t=36, b=10), paper_bgcolor=BG, plot_bgcolor=SURF,
        font=dict(family=MONO, size=11, color=MUTED), hovermode="x unified",
        hoverlabel=dict(bgcolor="#0E1013", bordercolor=BORDER, font=dict(family=MONO, size=11, color=TXT)),
        legend=dict(orientation="h", y=1.07, x=1, xanchor="right", bgcolor=BG),
        uirevision=f"cabinguard-telemetry-{window_s}",
        modebar=dict(bgcolor=BG, color=MUTED, activecolor=TXT))
    fig.update_annotations(font=dict(size=10, family=MONO, color=MUTED))
    for a in fig.layout.annotations[:3]:
        a.update(x=0, xanchor="left")
    return fig


CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": [
    "select2d", "lasso2d", "zoomIn2d", "zoomOut2d", "autoScale2d", "toImage"]}
