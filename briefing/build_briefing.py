"""
Energy Market Briefing — PDF builder
AD International Consulting

Usage:
  python build_briefing.py --data path/to/data.json --content content.md --out briefing.pdf

- data.json  comes from the Energy & FX Market Monitor pipeline (fetch_and_analyze.py).
- content.md holds the month's text. Pages are separated by a line `<!-- page -->`.
  Inside the text:
    {{brent.last}}, {{brent.chg_ytd}}, {{eurusd.vol_30d}} ...   numbers from data.json
    {{spread.last}}, {{spread.avg_1y}}, {{fc.brent.lo80}} ...
    [[chart:oil]] [[chart:spread]] [[chart:gas]] [[chart:fx]] [[chart:vol]] [[chart:fan]]
    [[table:kpis]] [[table:ranges]] [[table:brent_ccy]]
  Front matter between the first two `---` lines: issue, title, subtitle, asof.
Numbers are always read from the data, never typed by hand, so text and charts agree.
"""
import argparse, asyncio, base64, io, json, re
from pathlib import Path

import markdown
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
FONTS = HERE / "fonts"
for f in FONTS.glob("Montserrat-*.ttf"):
    font_manager.fontManager.addfont(str(f))

INK, INK2, INK3 = "#17140F", "#5B5346", "#8C8272"
GOLD, BRONZE, SLATE, SAND = "#A97C2F", "#7A5524", "#5E7180", "#C9B48A"
RULE, PAPER = "#D9CFBF", "#F6F1E8"
UP, DOWN = "#2F6B4F", "#9B3A2E"

plt.rcParams.update({
    "font.family": "Montserrat", "font.size": 8.5, "text.color": INK2,
    "axes.edgecolor": RULE, "axes.labelcolor": INK2, "axes.linewidth": 0.6,
    "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
    "axes.grid": True, "grid.color": RULE, "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": "none", "axes.facecolor": "none", "svg.fonttype": "path",
    "legend.frameon": False, "legend.fontsize": 7.5,
})

SHORT = {"brent": "Brent", "wti": "WTI", "henry_hub": "Henry Hub", "eurusd": "EUR/USD", "usdcny": "USD/CNY"}
UNIT = {"brent": "USD/bbl", "wti": "USD/bbl", "henry_hub": "USD/MMBtu", "eurusd": "USD per EUR", "usdcny": "CNY per USD"}
DEC = {"brent": 2, "wti": 2, "henry_hub": 2, "eurusd": 4, "usdcny": 4}


# ---------- data ----------
class Data:
    def __init__(self, path):
        self.d = json.loads(Path(path).read_text())
        self.s = {k: pd.Series(v["v"], index=pd.to_datetime(v["d"])) for k, v in self.d["prices"].items()}
        self.vol = {k: pd.Series(v["v"], index=pd.to_datetime(v["d"])) for k, v in self.d["volatility"].items()}
        self.spread = pd.Series(self.d["spread"]["v"], index=pd.to_datetime(self.d["spread"]["d"]))

    def at(self, k, when):
        return float(self.s[k][:when].iloc[-1])

    def value(self, key):
        """Resolve {{...}} keys to formatted strings."""
        parts = key.split(".")
        if parts[0] in self.d["kpis"]:
            k, field = parts
            v = self.d["kpis"][k][field]
            if field == "vol_30d":
                return f"{v*100:.1f}%"
            if field.startswith("chg"):
                return pct(v)
            if field == "last_date":
                return pd.Timestamp(v).strftime("%Y年%-m月%-d日" if LANG == "zh" else "%-d %B %Y")
            return num(k, v)
        if parts[0] == "spread":
            return f"${self.d['spread'][parts[1]]:.2f}"
        if parts[0] == "fc":  # fc.brent.lo80
            k, field = parts[1], parts[2]
            f = self.d["forecast"][k]
            if field in ("lo80", "hi80", "lo95", "hi95"):
                return num(k, f[field][-1])
            if field == "end":
                return pd.Timestamp(f["d"][-1]).strftime("%-d %B")
            if field == "coverage":
                return f"{f['backtest']['coverage_80']*100:.0f}%"
            if field == "mape":
                return f"±{f['backtest']['mape']*100:.1f}%"
        if parts[0] == "corr":  # corr.recent.brent.usdcny
            M, keys = self.d["corr_matrix"][parts[1]], self.d["corr_matrix"]["keys"]
            return f"{M[keys.index(parts[2])][keys.index(parts[3])]:.2f}"
        if parts[0] == "volrank":
            v = self.vol[parts[1]]
            return f"{(v <= v.iloc[-1]).mean()*100:.0f}%"
        raise KeyError(key)


def pct(x, d=1):
    return "—" if x is None else ("+" if x >= 0 else "−") + f"{abs(x)*100:.{d}f}%"


def num(k, x):
    return f"{x:,.{DEC[k]}f}"


# ---------- charts ----------
def svg(fig):
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    s = buf.getvalue()
    return s[s.index("<svg"):]


def fmt_dates(ax, months=2):
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=months))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))


def endlabel(ax, x, y, text, color, dy=0):
    ax.annotate(text, (x, y), xytext=(4, dy), textcoords="offset points", va="center",
                fontsize=7.5, fontweight="semibold", color=color)


def chart_oil(D, start="2025-10-01"):
    fig, ax = plt.subplots(figsize=(6.9, 2.6))
    for k, c, w in [("wti", INK, 1.1), ("brent", GOLD, 1.6)]:
        s = D.s[k][start:]
        ax.plot(s.index, s.values, color=c, lw=w, label=SHORT[k])
        endlabel(ax, s.index[-1], s.iloc[-1], f"{SHORT[k]} {s.iloc[-1]:.2f}", c)
    war = pd.Timestamp("2026-02-28")
    ax.axvline(war, color=INK3, lw=0.8, ls=(0, (3, 3)))
    ax.text(war, ax.get_ylim()[0], " War begins, 28 Feb", va="bottom", fontsize=7, color=INK3)
    pk = D.s["brent"][start:].idxmax()
    ax.annotate(f"Brent peak {D.s['brent'][pk]:.2f}\n{pk:%-d %b}", (pk, D.s["brent"][pk]),
                xytext=(26, -18), textcoords="offset points", fontsize=7, color=INK2,
                arrowprops=dict(arrowstyle="-", color=INK3, lw=0.6))
    ax.set_ylabel("USD per barrel")
    fmt_dates(ax)
    ax.margins(x=0.01)
    ax.legend(loc="upper left", ncol=2, bbox_to_anchor=(0, 1.12))
    return svg(fig)


def chart_spread(D, start="2026-01-01"):
    fig, ax = plt.subplots(figsize=(6.9, 1.9))
    s = D.spread[start:]
    ax.fill_between(s.index, 0, s.values, color=GOLD, alpha=0.18, lw=0)
    ax.plot(s.index, s.values, color=GOLD, lw=1.1)
    ax.axhline(D.d["spread"]["avg_1y"], color=INK3, lw=0.8, ls=(0, (3, 3)))
    ax.text(s.index[0], D.d["spread"]["avg_1y"], f" 1-year average {D.d['spread']['avg_1y']:.2f}",
            va="bottom", fontsize=7, color=INK3)
    pk = s.idxmax()
    ax.annotate(f"{s[pk]:.2f} on {pk:%-d %b}", (pk, s[pk]), xytext=(-70, -4), textcoords="offset points",
                fontsize=7, color=INK2, arrowprops=dict(arrowstyle="-", color=INK3, lw=0.6))
    ax.set_ylabel("USD per barrel")
    fmt_dates(ax)
    ax.margins(x=0.01)
    return svg(fig)


def chart_gas(D, jkm, jkm_date, start="2026-02-01"):
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(6.9, 2.2), gridspec_kw={"width_ratios": [2.3, 1]})
    s = D.s["henry_hub"][start:]
    ax.plot(s.index, s.values, color=SLATE, lw=1.3)
    endlabel(ax, s.index[-1], s.iloc[-1], f"{s.iloc[-1]:.2f}", SLATE)
    ax.set_ylim(0, max(4.5, s.max() * 1.15))
    ax.set_ylabel("USD per MMBtu")
    ax.set_title("Henry Hub spot, U.S.", loc="left", fontsize=8, color=INK, fontweight="semibold")
    fmt_dates(ax)
    hh = float(D.s["henry_hub"].iloc[-1])
    bars = bx.bar(["Henry Hub\nU.S.", "JKM\nAsia LNG"], [hh, jkm], color=[SLATE, GOLD], width=0.55)
    for b, v in zip(bars, [hh, jkm]):
        bx.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}", ha="center", va="bottom",
                fontsize=8, fontweight="semibold", color=INK)
    bx.set_ylim(0, jkm * 1.2)
    bx.set_title(f"Latest, {jkm_date}", loc="left", fontsize=8, color=INK, fontweight="semibold")
    bx.grid(axis="x", visible=False)
    fig.tight_layout(w_pad=2)
    return svg(fig)


def chart_fx(D, base="2025-12-31"):
    fig, ax = plt.subplots(figsize=(6.9, 2.3))
    ends = {}
    for k, c in [("eurusd", BRONZE), ("usdcny", INK)]:
        s = D.s[k][base:]
        r = s / D.at(k, base) * 100
        ax.plot(r.index, r.values, color=c, lw=1.3, label=SHORT[k])
        ends[k] = (r.index[-1], r.iloc[-1], c)
    hi = max(ends, key=lambda k: ends[k][1])
    for k, (x, y, c) in ends.items():
        endlabel(ax, x, y, f"{SHORT[k]} {y:.1f}", c, dy=5 if k == hi else -5)
    ax.axhline(100, color=INK3, lw=0.7)
    ax.set_ylabel("Index, 31 Dec 2025 = 100")
    fmt_dates(ax)
    ax.margins(x=0.01)
    ax.text(0.0, -0.2, "Below 100, EUR/USD means the euro has lost value against the dollar; USD/CNY means the yuan has gained value against it.",
            transform=ax.transAxes, fontsize=6.5, color=INK3, va="top")
    return svg(fig)


def chart_vol(D, start="2025-10-01"):
    fig, ax = plt.subplots(figsize=(6.9, 2.2))
    for k, c in [("brent", GOLD), ("eurusd", BRONZE), ("usdcny", INK)]:
        s = D.vol[k][start:] * 100
        ax.plot(s.index, s.values, color=c, lw=1.2, label=SHORT[k])
        endlabel(ax, s.index[-1], s.iloc[-1], f"{SHORT[k]} {s.iloc[-1]:.1f}%", c)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}%"))
    ax.set_ylabel("30-day volatility, annualised")
    fmt_dates(ax)
    ax.margins(x=0.01)
    return svg(fig)


def chart_fan(D, k="brent", months=6):
    f = D.d["forecast"][k]
    h = D.s[k][D.s[k].index[-1] - pd.DateOffset(months=months):]
    x = [h.index[-1]] + list(pd.to_datetime(f["d"]))
    last = float(h.iloc[-1])
    fig, ax = plt.subplots(figsize=(6.9, 2.4))
    ax.fill_between(x, [last] + f["lo95"], [last] + f["hi95"], color=GOLD, alpha=0.13, lw=0, label="95% range")
    ax.fill_between(x, [last] + f["lo80"], [last] + f["hi80"], color=GOLD, alpha=0.30, lw=0, label="80% range")
    ax.plot(h.index, h.values, color=INK, lw=1.3, label="Brent")
    ax.plot(x, [last] * len(x), color=GOLD, lw=1, ls=(0, (3, 2)))
    for v in (f["lo80"][-1], f["hi80"][-1]):
        endlabel(ax, x[-1], v, f"{v:.0f}", INK)
    ax.set_ylabel("USD per barrel")
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.legend(loc="upper left", ncol=3, bbox_to_anchor=(0, 1.13))
    ax.margins(x=0.01)
    return svg(fig)


# ---------- tables ----------
I18N = {
    "en": dict(market="Market", last="Last", asof="As of", m1="1 month", ytd="Year to date", r52="52-week range", vol="Volatility",
               names=SHORT, units=UNIT, brand="AD International Consulting · Market Intelligence",
               h1="<b>Energy</b> Market Briefing", data_to="Data to", footer="AD International Consulting · Energy Market Briefing · {issue}",
               page="Page <span class=\"pageNumber\"></span> of <span class=\"totalPages\"></span>", date="%-d %b"),
    "zh": dict(market="市场", last="最新", asof="截至", m1="近1个月", ytd="年初至今", r52="52周区间", vol="波动率",
               names={"brent": "布伦特原油", "wti": "WTI原油", "henry_hub": "亨利港天然气", "eurusd": "欧元/美元", "usdcny": "美元/人民币"},
               units={"brent": "美元/桶", "wti": "美元/桶", "henry_hub": "美元/百万英热", "eurusd": "每欧元兑美元", "usdcny": "每美元兑人民币"},
               brand="AD International Consulting · 市场情报", h1="<b>能源</b>市场简报", data_to="数据截至",
               footer="AD International Consulting · 能源市场简报 · {issue}",
               page="第 <span class=\"pageNumber\"></span> / <span class=\"totalPages\"></span> 页", date="%-m月%-d日"),
}
LANG = "en"


def table_kpis(D):
    T = I18N[LANG]
    rows = []
    for k in ["brent", "wti", "henry_hub", "eurusd", "usdcny"]:
        q = D.d["kpis"][k]
        def cell(x):
            cls = "up" if x is not None and x >= 0 else "down"
            return f'<td class="n {cls}">{pct(x)}</td>'
        rows.append(f"<tr><th>{T['names'][k]}<span>{T['units'][k]}</span></th><td class='n b'>{num(k, q['last'])}</td>"
                    f"<td class='n'>{pd.Timestamp(q['last_date']).strftime(T['date'])}</td>{cell(q['chg_1m'])}{cell(q['chg_ytd'])}"
                    f"<td class='n'>{num(k, q['low_52w'])} – {num(k, q['high_52w'])}</td>"
                    f"<td class='n'>{q['vol_30d']*100:.1f}%</td></tr>")
    return (f"<table class='data'><thead><tr><th>{T['market']}</th><th>{T['last']}</th><th>{T['asof']}</th><th>{T['m1']}</th>"
            f"<th>{T['ytd']}</th><th>{T['r52']}</th><th>{T['vol']}</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")


def table_ranges(D):
    rows = []
    for k in ["brent", "eurusd", "usdcny"]:
        f = D.d["forecast"][k]; bt = f["backtest"]
        rows.append(f"<tr><th>{SHORT[k]}</th><td class='n b'>{num(k, D.d['kpis'][k]['last'])}</td>"
                    f"<td class='n'>{num(k, f['lo80'][-1])} – {num(k, f['hi80'][-1])}</td>"
                    f"<td class='n'>{num(k, f['lo95'][-1])} – {num(k, f['hi95'][-1])}</td>"
                    f"<td class='n'>{pd.Timestamp(f['d'][-1]):%-d %b}</td>"
                    f"<td class='n'>{bt['coverage_80']*100:.0f}% of {bt['n_forecasts']}</td></tr>")
    return ("<table class='data'><thead><tr><th>Market</th><th>Last</th><th>80% range</th><th>95% range</th>"
            "<th>Horizon</th><th>80% band hit rate, 3 years</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def table_brent_ccy(D, end, starts=(("2025-12-31", "Since 31 Dec 2025"), ("2026-02-27", "Since 27 Feb 2026, pre-war"))):
    b, e, c = (lambda t: D.at("brent", t)), (lambda t: D.at("eurusd", t)), (lambda t: D.at("usdcny", t))
    head = "<tr><th>Brent priced in</th><th>Price, " + pd.Timestamp(end).strftime("%-d %b") + "</th>" + "".join(f"<th>{l}</th>" for _, l in starts) + "</tr>"
    def row(name, f, fmt):
        cells = "".join(f"<td class='n'>{pct(f(end) / f(t) - 1)}</td>" for t, _ in starts)
        return f"<tr><th>{name}</th><td class='n b'>{fmt(f(end))}</td>{cells}</tr>"
    return ("<table class='data'><thead>" + head + "</thead><tbody>"
            + row("US dollars", lambda t: b(t), lambda v: f"$ {v:,.2f}")
            + row("Euros", lambda t: b(t) / e(t), lambda v: f"€ {v:,.2f}")
            + row("Chinese yuan", lambda t: b(t) * c(t), lambda v: f"¥ {v:,.1f}")
            + "</tbody></table>")


# ---------- page assembly ----------
def render(D, content_md, meta):
    charts = {
        "oil": lambda: chart_oil(D), "spread": lambda: chart_spread(D),
        "gas": lambda: chart_gas(D, float(meta["jkm"]), meta["jkm_date"]),
        "fx": lambda: chart_fx(D), "vol": lambda: chart_vol(D), "fan": lambda: chart_fan(D),
    }
    tables = {"kpis": lambda: table_kpis(D), "ranges": lambda: table_ranges(D),
              "brent_ccy": lambda: table_brent_ccy(D, D.d["kpis"]["brent"]["last_date"])}

    def blocks(text):
        text = re.sub(r"\{\{([a-z0-9_.]+)\}\}", lambda m: D.value(m.group(1)), text)
        out = []
        for part in re.split(r"^\[\[(chart|table):([a-z_]+)\]\]\s*$", text, flags=re.M):
            out.append(part)
        html, i = [], 0
        while i < len(out):
            if i + 2 < len(out) and out[i + 1] in ("chart", "table"):
                html.append(markdown.markdown(out[i], extensions=["tables", "md_in_html"]))
                kind, name = out[i + 1], out[i + 2]
                html.append(f"<figure class='{kind}'>{(charts if kind == 'chart' else tables)[name]()}</figure>")
                i += 3
            else:
                html.append(markdown.markdown(out[i], extensions=["tables", "md_in_html"]))
                i += 1
        return "".join(html)

    pages = [p for p in re.split(r"^<!-- page -->\s*$", content_md, flags=re.M) if p.strip()]
    body = "".join(f"<section class='page{' first' if n == 0 else ''}'>{blocks(p)}</section>" for n, p in enumerate(pages))
    return body


CSS = """
@font-face{font-family:Montserrat;font-weight:300;src:url(fonts/Montserrat-Light.ttf)}
@font-face{font-family:Montserrat;font-weight:400;src:url(fonts/Montserrat-Regular.ttf)}
@font-face{font-family:Montserrat;font-weight:500;src:url(fonts/Montserrat-Medium.ttf)}
@font-face{font-family:Montserrat;font-weight:600;src:url(fonts/Montserrat-SemiBold.ttf)}
@font-face{font-family:Montserrat;font-weight:700;src:url(fonts/Montserrat-Bold.ttf)}
@font-face{font-family:Plex;font-weight:400;src:url(fonts/ibm-plex-mono-latin-400-normal.woff2)}
@font-face{font-family:Plex;font-weight:500;src:url(fonts/ibm-plex-mono-latin-500-normal.woff2)}
@font-face{font-family:"Noto Sans SC";font-weight:400;src:url(fonts/NotoSansSC-Regular.otf)}
@font-face{font-family:"Noto Sans SC";font-weight:500 600;src:url(fonts/NotoSansSC-Medium.otf)}
@font-face{font-family:"Noto Sans SC";font-weight:700;src:url(fonts/NotoSansSC-Bold.otf)}
:root{--paper:#F6F1E8;--ink:#17140F;--ink2:#5B5346;--ink3:#8C8272;--rule:#D9CFBF;--gold:#A97C2F;--up:#2F6B4F;--down:#9B3A2E}
@page{size:A4;margin:16mm 16mm 18mm;background:#F6F1E8}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact;background:var(--paper)}
body{margin:0;font-family:Montserrat,"Noto Sans SC",sans-serif;font-size:9.4pt;line-height:1.55;color:var(--ink)}
.page{break-after:page}
.page:last-child{break-after:auto}
h1,h2,h3{text-wrap:balance;margin:0}
.mast{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:1.6pt solid var(--ink);padding-bottom:9pt;margin-bottom:14pt}
.brand{font-size:7pt;letter-spacing:.24em;text-transform:uppercase;color:var(--gold);font-weight:600}
.mast h1{font-size:25pt;font-weight:300;line-height:1.05;margin-top:5pt}
.mast h1 b{font-weight:700}
.issue{text-align:right;font-size:8pt;color:var(--ink2);line-height:1.5}
.issue b{color:var(--ink);font-weight:600}
h2{font-size:14pt;font-weight:600;margin:0 0 6pt;padding-top:2pt}
h2 + p.kicker, p.kicker{font-size:10.5pt;font-weight:500;color:var(--ink);margin:0 0 9pt;line-height:1.45}
h3{font-size:7.5pt;letter-spacing:.18em;text-transform:uppercase;color:var(--ink3);font-weight:600;margin:12pt 0 5pt}
p{margin:0 0 7pt;max-width:172mm}
ul{margin:0 0 8pt;padding-left:0;list-style:none}
li{padding-left:12pt;position:relative;margin-bottom:4pt}
li::before{content:"";position:absolute;left:0;top:.72em;width:6pt;height:.8pt;background:var(--gold)}
strong{font-weight:600}
figure{margin:6pt 0 10pt}
figure.chart svg{width:100%;height:auto;display:block}
table.data{width:100%;border-collapse:collapse;font-size:8.2pt;margin:2pt 0}
table.data th,table.data td{padding:5pt 6pt;border-bottom:.6pt solid var(--rule);text-align:left;vertical-align:baseline}
table.data thead th{font-size:6.8pt;letter-spacing:.12em;text-transform:uppercase;color:var(--ink3);font-weight:600;border-bottom:1pt solid var(--ink)}
table.data tbody th{font-weight:600}
table.data tbody th span{display:block;font-weight:400;font-size:6.8pt;color:var(--ink3)}
td.n{font-family:Plex,monospace;font-variant-numeric:tabular-nums;white-space:nowrap}
td.b{font-weight:500;color:var(--ink)}
td.up{color:var(--up)} td.down{color:var(--down)}
table:not(.data){width:100%;border-collapse:collapse;font-size:8.4pt}
table:not(.data) th,table:not(.data) td{padding:4.5pt 6pt;border-bottom:.6pt solid var(--rule);text-align:left;vertical-align:top}
table:not(.data) th{font-size:6.8pt;letter-spacing:.12em;text-transform:uppercase;color:var(--ink3);font-weight:600;border-bottom:1pt solid var(--ink)}
table:not(.data) td:first-child{font-weight:500;color:var(--ink);width:24%}
.box{border:.8pt solid var(--rule);background:#FBF8F2;padding:9pt 11pt;margin:8pt 0}
.note{font-size:7.6pt;color:var(--ink2)}
.sources{font-size:7pt;color:var(--ink2)}
.sources ol{columns:2;column-gap:14pt;margin:0;padding-left:14pt}
.sources li{break-inside:avoid;padding-left:0}
.sources li::before{display:none}
.sources li{margin-bottom:2.5pt}
a{color:var(--gold);text-decoration:none}
.disclaimer{font-size:7pt;color:var(--ink3);border-top:.6pt solid var(--rule);padding-top:6pt;margin-top:10pt}
"""

FOOTER = """<div style="width:100%;font-family:Montserrat,sans-serif;font-size:6.5pt;color:#8C8272;padding:0 16mm;display:flex;justify-content:space-between">
<span>{footer}</span><span>{page}</span></div>"""


def front_matter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    meta = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    return {k.strip(): v.strip() for k, v in meta.items()}, text[m.end():]


async def to_pdf(html_path, pdf_path, issue):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page()
        await pg.goto(Path(html_path).resolve().as_uri())
        await pg.evaluate("document.fonts.ready")
        await pg.pdf(path=str(pdf_path), format="A4", print_background=True, prefer_css_page_size=True,
                     display_header_footer=True, header_template="<span></span>",
                     footer_template=FOOTER.format(footer=I18N[LANG]["footer"].format(issue=issue), page=I18N[LANG]["page"]),
                     margin={"top": "16mm", "bottom": "18mm", "left": "16mm", "right": "16mm"})
        await b.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--content", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    D = Data(a.data)
    meta, body_md = front_matter(Path(a.content).read_text())
    global LANG
    LANG = meta.get("lang", "en")
    T = I18N[LANG]
    mast = (f"<header class='mast'><div><div class='brand'>{T['brand']}</div>"
            f"<h1>{T['h1']}</h1></div><div class='issue'><b>{meta['issue']}</b><br>"
            f"{meta.get('subtitle', '')}<br>{T['data_to']} {meta['asof']}</div></header>")
    body = render(D, body_md, meta)
    body = body.replace("<section class='page first'>", "<section class='page first'>" + mast, 1)
    html = f"<!doctype html><html lang='{LANG}'><head><meta charset='utf-8'><title>{meta['title']}</title><style>{CSS}</style></head><body>{body}</body></html>"
    html_path = HERE / (Path(a.out).stem + ".html")
    html_path.write_text(html)
    asyncio.run(to_pdf(html_path, a.out, meta["issue"]))
    print("Wrote", a.out)


if __name__ == "__main__":
    main()
