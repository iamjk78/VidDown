"""Generátor návrhů GUI VidDown (HTML stránky 1440x960, převod do PDF dělá render_pdf.swift).

Použití:  python3 design/build_mockups.py   -> design/build/*.html
"""
from pathlib import Path

OUT = Path(__file__).parent / "build"
OUT.mkdir(exist_ok=True)

# ---------------------------------------------------------------- ikony
ICONS = {
    "play": '<path d="M7 4v16l13-8z"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "grip": '<path d="M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01" stroke-width="3"/>',
    "down": '<path d="M6 9l6 6 6-6"/>',
    "right": '<path d="M9 6l6 6-6 6"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "settings": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 3"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    "download": '<path d="M12 4v12M7 11l5 5 5-5M5 20h14"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.9-3M4 4v4h4M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4"/>',
    "check": '<path d="M5 12l5 5L20 7"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "send": '<path d="M21 3L3 10.5l7 2.5 2.5 7z"/><path d="M10 13l4-4"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "film": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
    "undo": '<path d="M4 4v5h5"/><path d="M4.5 13A8 8 0 1 0 6 7L4 9"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "bolt": '<path d="M13 3L5 14h6l-1 7 8-11h-6z"/>',
    "hdd": '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5 13l2-8h10l2 8M7 16.5h.01"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M13 15h4"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "cookie": '<path d="M12 3a9 9 0 1 0 9 9 4 4 0 0 1-4-4 4 4 0 0 1-5-5z"/><path d="M8.5 13.5h.01M12 17h.01M15.5 13h.01"/>',
    "palette": '<path d="M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.2-1.7-.4-1.1.3-2.3 1.5-2.3H17a4 4 0 0 0 4-4c0-5.5-4-10-9-10z"/><path d="M7.5 11h.01M10 7.5h.01M14.5 7.5h.01"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "tag": '<path d="M3 12V4h8l10 10-8 8z"/><path d="M7.5 7.5h.01"/>',
}


def ic(name, size=16, cls=""):
    return (f'<svg class="ic {cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')


# ---------------------------------------------------------------- styly
CSS = r"""
:root{--bg:#F5F6F8;--surface:#FFFFFF;--surface2:#F9FAFB;--border:#E4E7EC;--border2:#D0D5DD;--text:#101828;--text2:#475467;--muted:#98A2B3;
--accent:#4F46E5;--accent-soft:#EEF2FF;--accent-text:#3730A3;--ok:#067647;--ok-soft:#ECFDF3;--warn:#B54708;--warn-soft:#FFFAEB;--err:#C01048;--err2:#D92D20;--err-soft:#FEF3F2;
--track:#EAECF0;--page:#DDE1E7;--cap:#475467;--shadow:0 24px 60px rgba(16,24,40,.18),0 4px 12px rgba(16,24,40,.08);--title:#ECEEF2}
.dark{--bg:#0E1016;--surface:#161922;--surface2:#1B1F2A;--border:#272C3A;--border2:#353B4C;--text:#F2F4F7;--text2:#A5ADBD;--muted:#6B7385;
--accent:#7F78FF;--accent-soft:#25234A;--accent-text:#C7C4FF;--ok:#47CD89;--ok-soft:#0F2A1D;--warn:#FDB022;--warn-soft:#2E2210;--err:#F97066;--err2:#F97066;--err-soft:#2D1515;
--track:#262B38;--page:#05060A;--cap:#8A93A6;--shadow:0 24px 60px rgba(0,0,0,.6);--title:#1A1D26}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1440px;height:960px;overflow:hidden}
body{font-family:-apple-system,"SF Pro Text","Helvetica Neue",Arial,sans-serif;color:var(--text);background:var(--page);font-size:13px;-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
.page{width:1440px;height:960px;padding:0 40px;display:flex;flex-direction:column}
.cap{height:52px;display:flex;align-items:center;gap:10px;color:var(--cap);font-size:13px}
.cap b{color:var(--text);font-weight:600}
.cap .sep{opacity:.5}
.win{width:1360px;height:868px;border-radius:12px;overflow:hidden;box-shadow:var(--shadow);background:var(--bg);display:flex;flex-direction:column;border:1px solid var(--border)}
.titlebar{height:38px;flex:none;background:var(--title);border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 14px;position:relative}
.lights{display:flex;gap:8px}.lights i{width:12px;height:12px;border-radius:50%;display:block}
.lights i:nth-child(1){background:#FF5F57}.lights i:nth-child(2){background:#FEBC2E}.lights i:nth-child(3){background:#28C840}
.url{position:absolute;left:50%;transform:translateX(-50%);height:24px;width:360px;border-radius:6px;background:var(--surface);border:1px solid var(--border);color:var(--text2);font-size:12px;display:flex;align-items:center;justify-content:center;gap:6px}
.app{flex:1;min-height:0;display:flex;flex-direction:column;position:relative}
.ic{flex:none;display:block}
.row{display:flex;align-items:center}
.gap4{gap:4px}.gap6{gap:6px}.gap8{gap:8px}.gap10{gap:10px}.gap12{gap:12px}.gap16{gap:16px}
.grow{flex:1;min-width:0}
.t2{color:var(--text2)}.muted{color:var(--muted)}.err{color:var(--err2)}.ok{color:var(--ok)}
.fs11{font-size:11px}.fs12{font-size:12px}.fs14{font-size:14px}.fs15{font-size:15px}
.b5{font-weight:500}.b6{font-weight:600}
.mono{font-family:"SF Mono",Menlo,monospace}
.ell{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
h1{font-size:22px;font-weight:650;letter-spacing:-.01em}
h2{font-size:15px;font-weight:600}
.logo{display:flex;align-items:center;gap:9px;font-weight:700;font-size:16px;letter-spacing:-.01em}
.logo .mk{width:28px;height:28px;border-radius:8px;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;height:34px;padding:0 14px;border-radius:8px;border:1px solid var(--border2);background:var(--surface);color:var(--text);font-size:13px;font-weight:500;white-space:nowrap}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.sm{height:28px;padding:0 10px;font-size:12px}
.btn.ghost{border-color:transparent;background:transparent;color:var(--text2)}
.ibtn{width:30px;height:30px;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;color:var(--text2);flex:none}
.ibtn.b{border:1px solid var(--border2);background:var(--surface)}
.input{height:40px;border:1px solid var(--border2);border-radius:10px;background:var(--surface);display:flex;align-items:center;gap:8px;padding:0 12px;color:var(--muted);font-size:14px;min-width:0}
.input.sm{height:32px;border-radius:8px;font-size:13px;padding:0 10px}
.input .val{color:var(--text)}
.input.focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.badge{display:inline-flex;align-items:center;gap:4px;height:20px;padding:0 7px;border-radius:6px;font-size:11px;font-weight:600;white-space:nowrap}
.b-yt{background:var(--accent-soft);color:var(--accent-text)}
.b-sn{background:var(--warn-soft);color:var(--warn)}
.b-ok{background:var(--ok-soft);color:var(--ok)}
.b-err{background:var(--err-soft);color:var(--err2)}
.b-warn{background:var(--warn-soft);color:var(--warn)}
.b-n{background:var(--surface2);color:var(--text2);border:1px solid var(--border)}
.chip{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 10px;border-radius:99px;border:1px solid var(--border);background:var(--surface);font-size:12px;color:var(--text2)}
.chip b{color:var(--text);font-weight:600}
.chip.on{background:var(--accent-soft);border-color:transparent;color:var(--accent-text)}
.bar{height:6px;border-radius:99px;background:var(--track);overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent);border-radius:99px}
.bar.sn i{background:#F79009}
.bar.thick{height:8px}
.bar.ind i{width:35%;margin-left:30%;opacity:.6}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px}
.toggle{width:36px;height:20px;border-radius:99px;background:var(--track);position:relative;flex:none}
.toggle::after{content:"";position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25)}
.toggle.on{background:var(--accent)}.toggle.on::after{left:18px}
.seg{display:inline-flex;border:1px solid var(--border);border-radius:8px;padding:2px;background:var(--surface2)}
.seg span{padding:4px 12px;font-size:12px;border-radius:6px;color:var(--text2);white-space:nowrap}
.seg span.on{background:var(--surface);color:var(--text);box-shadow:0 1px 2px rgba(0,0,0,.12);font-weight:600}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;flex:none}
.dot.g{background:#17B26A;box-shadow:0 0 0 3px rgba(23,178,106,.18)}
.spin{width:14px;height:14px;border-radius:50%;border:2px solid var(--track);border-top-color:var(--accent);flex:none}
/* miniatury */
.th{position:relative;border-radius:8px;overflow:hidden;flex:none;background:#2a2f3a}
.th .dur{position:absolute;right:4px;bottom:4px;background:rgba(0,0,0,.75);color:#fff;font-size:10px;line-height:14px;padding:0 4px;border-radius:4px;font-weight:600}
.th .res{position:absolute;left:4px;top:4px;background:rgba(0,0,0,.6);color:#fff;font-size:9px;line-height:13px;padding:0 4px;border-radius:3px;font-weight:700}
.th .scene{position:absolute;inset:0}
.ph{background:var(--surface2);border:1px dashed var(--border2);display:flex;align-items:center;justify-content:center;color:var(--muted)}
.stack{box-shadow:4px -4px 0 -1px var(--border2),8px -8px 0 -2px var(--border)}
.tk1{background:linear-gradient(180deg,#8EC5E8 0%,#D7ECF7 48%,#9BB7C6 49%,#42687A 100%)}
.tk1 .scene{background:#34515F;clip-path:polygon(0 52%,14% 26%,26% 44%,40% 18%,55% 46%,66% 30%,80% 50%,100% 28%,100% 100%,0 100%);}
.tk2{background:#1E1E2E}
.tk2 .scene{background:
 linear-gradient(#F38BA8,#F38BA8) 10% 22%/30% 7% no-repeat,linear-gradient(#89B4FA,#89B4FA) 44% 22%/22% 7% no-repeat,
 linear-gradient(#A6E3A1,#A6E3A1) 16% 38%/44% 7% no-repeat,linear-gradient(#CDD6F4,#CDD6F4) 16% 54%/26% 7% no-repeat,
 linear-gradient(#FAB387,#FAB387) 46% 54%/20% 7% no-repeat,linear-gradient(#89B4FA,#89B4FA) 10% 70%/36% 7% no-repeat,
 linear-gradient(90deg,#FFD43B 0 50%,#3776AB 50% 100%) 88% 80%/18% 26% no-repeat}
.tk3{background:linear-gradient(180deg,#0B1030 0%,#2B1E55 55%,#6B3A6E 100%)}
.tk3::before{content:"";position:absolute;right:14%;top:12%;width:9%;padding-top:9%;border-radius:50%;background:#F5F0D8}
.tk3 .scene{background:#110E24;clip-path:polygon(0 100%,0 62%,8% 62%,8% 48%,15% 48%,15% 66%,22% 66%,22% 40%,26% 30%,30% 40%,30% 58%,40% 58%,40% 46%,48% 46%,48% 64%,58% 64%,58% 36%,63% 36%,63% 54%,72% 54%,72% 44%,80% 44%,80% 60%,90% 60%,90% 50%,100% 50%,100% 100%)}
.tk3::after{content:"";position:absolute;inset:0;background:radial-gradient(circle,#FFD58A 0 1px,transparent 1.5px) 0 0/9px 11px;opacity:.55;clip-path:polygon(0 100%,0 70%,100% 70%,100% 100%)}
.tk4{background:radial-gradient(ellipse at 50% 58%,#F2C27B 0 30%,#C47A35 31% 38%,#7A3E17 39% 52%,#3B2414 53%)}
.tk4 .scene{display:none}
.tk5{background:#F8FAFC}
.tk5 .scene{background:linear-gradient(#1D4ED8,#1D4ED8) 0 0/100% 22% no-repeat,
 linear-gradient(#93C5FD,#93C5FD) 14% 82%/9% 30% no-repeat,linear-gradient(#60A5FA,#60A5FA) 28% 82%/9% 42% no-repeat,
 linear-gradient(#3B82F6,#3B82F6) 42% 82%/9% 52% no-repeat,linear-gradient(#2563EB,#2563EB) 56% 82%/9% 36% no-repeat,
 linear-gradient(#CBD5E1,#CBD5E1) 76% 40%/30% 5% no-repeat,linear-gradient(#CBD5E1,#CBD5E1) 76% 54%/26% 5% no-repeat,linear-gradient(#CBD5E1,#CBD5E1) 76% 68%/30% 5% no-repeat}
.tk6{background:linear-gradient(180deg,#B8651F 0%,#5A2E10 45%,#120B07 100%)}
.tk6 .scene{background:#000;clip-path:polygon(28% 100%,30% 62%,34% 52%,40% 50%,44% 56%,45% 70%,52% 72%,58% 66%,60% 54%,66% 50%,72% 56%,73% 100%)}
.tk7{background:linear-gradient(180deg,#3E2D5C 0%,#E0617A 38%,#F7A65A 56%,#2C4C6B 57%,#13283D 100%)}
.tk7::before{content:"";position:absolute;left:43%;top:42%;width:14%;padding-top:14%;border-radius:50%;background:#FFE3A3;clip-path:inset(0 0 50% 0)}
.tk7 .scene{display:none}
.tk8{background:linear-gradient(180deg,#CFE8D5 0%,#7FB58D 40%,#24533A 100%)}
.tk8 .scene{background:#1B3D2B;clip-path:polygon(0 100%,4% 60%,8% 100%,10% 100%,16% 44%,22% 100%,26% 100%,32% 54%,38% 100%,42% 100%,50% 36%,58% 100%,60% 100%,66% 50%,72% 100%,76% 100%,84% 40%,92% 100%,94% 100%,98% 62%,100% 70%,100% 100%)}
.tk9{background:linear-gradient(180deg,#B9D7F0 0%,#EAF2F8 46%,#C8C9C2 47%,#7D7A6C 100%)}
.tk9 .scene{background:#5D6157;clip-path:polygon(0 70%,22% 40%,34% 52%,52% 22%,70% 50%,82% 38%,100% 60%,100% 100%,0 100%)}
"""


def thumb(kind, w, h, dur=None, res=None, extra=""):
    if kind == "ph":
        return f'<div class="th ph {extra}" style="width:{w}px;height:{h}px"><div class="spin"></div></div>'
    d = f'<span class="dur">{dur}</span>' if dur else ""
    r = f'<span class="res">{res}</span>' if res else ""
    return f'<div class="th tk{kind[1:]} {extra}" style="width:{w}px;height:{h}px"><div class="scene"></div>{r}{d}</div>'


def page(name, caption, body, dark=False, tab_url="localhost:8765"):
    html = f"""<!doctype html><html class="{'dark' if dark else ''}"><head><meta charset="utf-8"><style>{CSS}{EXTRA_CSS}</style></head>
<body><div class="page"><div class="cap">{caption}</div>
<div class="win"><div class="titlebar"><div class="lights"><i></i><i></i><i></i></div>
<div class="url">{ic('lock', 11)} {tab_url}</div></div><div class="app">{body}</div></div></div></body></html>"""
    (OUT / f"{name}.html").write_text(html, encoding="utf-8")


def cap(variant, screen, dark):
    mode = "Tmavý režim" if dark else "Světlý režim"
    return f'<b>Varianta {variant}</b><span class="sep">·</span>{screen}<span class="sep">·</span>{mode}'


EXTRA_CSS = ""

# ---------------------------------------------------------------- data
RUN = [
    dict(t="t1", dur="12:47", title="Islandské fjordy z dronu – 4K", ch="Nordic Drone Films", res="2160p",
         m="yt-dlp", pct=78, done="1,43 GB", size="1,84 GB", speed="6,2 MB/s", eta="1:02", src="GUI"),
    dict(t="t3", dur="3:58", title="Noční Praha – timelapse", ch="prahavecer.cz", res="1080p",
         m="sniffer", pct=34, done="140 MB", size="412 MB", speed="2,4 MB/s", eta="1:51", src="Telegram"),
]
WAIT = [
    dict(t="t4", dur="24:10", title="Domácí kváskový chléb krok za krokem", ch="Pekárna u Hanky", res="1080p", m="yt-dlp", size="1,1 GB", src="Telegram"),
    dict(t="t6", dur="1:32:05", title="Jazz na Vltavě – živý koncert", ch="Jazz Dock", res="1440p", m="yt-dlp", size="5,8 GB", src="GUI"),
    dict(t="t7", dur="8:31", title="Západ slunce nad Jadranem", ch="Slow TV Europe", res="2160p", m="yt-dlp", size="2,2 GB", src="CLI"),
]
PAUSED = dict(t="t5", dur="1:28:44", title="Úvod do strojového učení – přednáška 1", ch="Matfyz přednášky", res="1080p", m="yt-dlp", size="1,6 GB", src="GUI")
PL_CHILDREN = ["Lekce 1: Instalace a první program", "Lekce 2: Proměnné a datové typy", "Lekce 3: Podmínky a cykly"]


def mbadge(m):
    return f'<span class="badge {"b-yt" if m == "yt-dlp" else "b-sn"}">{m}</span>'


def src_ic(src):
    return {"Telegram": ic("send", 12), "CLI": ic("terminal", 12), "GUI": ic("download", 12)}[src]


def footer_status():
    return f"""<div class="statusbar">
<span class="row gap6">{ic('hdd', 14)} Volné místo <b>184 GB</b></span>
<span class="row gap6">{ic('folder', 14)} ~/Videa/VidDown</span>
<span class="row gap6"><span class="dot g"></span> Telegram bot připojen</span>
<span class="grow"></span>
<span class="row gap6 muted">{ic('cpu', 14)} yt-dlp 2026.11.05 · Deno 2.6.3 · ffmpeg 9.0.1</span></div>"""


EXTRA_CSS += """
.statusbar{height:34px;flex:none;border-top:1px solid var(--border);background:var(--surface);display:flex;align-items:center;gap:22px;padding:0 20px;font-size:12px;color:var(--text2)}
.statusbar b{color:var(--text);font-weight:600}
"""

# ================================================================ VARIANTA A
EXTRA_CSS += """
.a-head{height:58px;flex:none;background:var(--surface);border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 20px;gap:28px}
.tabs{display:flex;height:100%;gap:4px}
.tab{height:100%;display:flex;align-items:center;gap:7px;padding:0 12px;color:var(--text2);font-weight:500;font-size:14px;border-bottom:2px solid transparent;margin-bottom:-1px}
.tab.on{color:var(--text);border-bottom-color:var(--accent)}
.tab .n{font-size:11px;font-weight:700;background:var(--accent-soft);color:var(--accent-text);border-radius:99px;padding:1px 7px}
.a-body{flex:1;min-height:0;padding:20px 24px 0;display:flex;flex-direction:column;gap:16px;overflow:hidden}
.tbl{overflow:hidden;flex:1;min-height:0;border-bottom-left-radius:0;border-bottom-right-radius:0;border-bottom:none}
.tr{display:grid;grid-template-columns:22px minmax(0,1fr) 84px 230px 84px 64px 70px;align-items:center;gap:14px;padding:10px 16px;border-top:1px solid var(--border)}
.tr.h{border-top:none;background:var(--surface2);padding-top:9px;padding-bottom:9px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.tr.child{padding-left:16px;background:var(--surface2)}
.tr.dim .fade{opacity:.5}
.tr.sel{background:var(--accent-soft)}
.vid{display:flex;align-items:center;gap:12px;min-width:0}
.vid .tt{font-size:14px;font-weight:600;line-height:18px}
.vid .mm{font-size:12px;color:var(--text2);margin-top:3px;display:flex;align-items:center;gap:6px;white-space:nowrap}
.grip{color:var(--muted)}
.pg .l{font-size:11px;color:var(--text2);margin-top:5px;display:flex;justify-content:space-between}
.acts{display:flex;justify-content:flex-end;gap:2px}
"""


def a_head(active, dark):
    tabs = [("Fronta", "list", "20"), ("Historie", "history", None), ("Nastavení", "settings", None), ("Enginy", "cpu", None)]
    t = "".join(
        f'<div class="tab {"on" if n == active else ""}">{ic(i, 16)}{n}{f"<span class=n>{c}</span>" if c else ""}</div>'
        for n, i, c in tabs)
    return f"""<div class="a-head"><div class="logo"><div class="mk">{ic('download', 16)}</div>VidDown</div>
<div class="tabs">{t}</div><div class="grow"></div>
<span class="row gap6 t2 fs12">{ic('bolt', 14)} Celkem <b style="color:var(--text)">8,6 MB/s</b></span>
<span class="btn sm">{ic('pause', 14)} Pozastavit frontu</span>
<span class="ibtn b">{ic('sun' if dark else 'moon', 15)}</span>
<span class="btn sm ghost">CS {ic('down', 12)}</span></div>"""


def a_queue(dark):
    rows = []
    for i, r in enumerate(RUN):
        rows.append(f"""<div class="tr {'sel' if i == 0 and False else ''}"><span class="grip">{ic('grip')}</span>
<div class="vid">{thumb(r['t'], 112, 63, r['dur'])}<div class="grow"><div class="tt ell">{r['title']}</div>
<div class="mm">{r['ch']} · {r['res']} · {src_ic(r['src'])} {r['src']}</div></div></div>
<div>{mbadge(r['m'])}</div>
<div class="pg"><div class="bar {'sn' if r['m'] == 'sniffer' else ''}"><i style="width:{r['pct']}%"></i></div>
<div class="l"><span><b style="color:var(--text)">{r['pct']} %</b></span><span>{r['done']} / {r['size']}</span></div></div>
<div class="b5">{r['speed']}</div><div class="t2">{r['eta']}</div>
<div class="acts"><span class="ibtn">{ic('pause', 15)}</span><span class="ibtn">{ic('x', 15)}</span></div></div>""")
    # kontrola URL
    rows.append(f"""<div class="tr"><span class="grip">{ic('grip')}</span>
<div class="vid">{thumb('ph', 112, 63)}<div class="grow"><div class="tt ell">vimeo.com/824119370</div>
<div class="mm"><span class="row gap6">Kontroluji URL…</span> · {src_ic('Telegram')} Telegram</div></div></div>
<div><span class="badge b-n">—</span></div>
<div class="pg"><div class="bar ind"><i></i></div><div class="l"><span>Zjišťuji počet videí a kvalitu</span><span></span></div></div>
<div class="muted">—</div><div class="muted">—</div>
<div class="acts"><span class="ibtn">{ic('pause', 15)}</span><span class="ibtn">{ic('x', 15)}</span></div></div>""")
    # playlist
    rows.append(f"""<div class="tr"><span class="grip">{ic('grip')}</span>
<div class="vid"><span class="muted">{ic('down', 14)}</span>{thumb('t2', 98, 55, None, None, 'stack')}<div class="grow"><div class="tt ell">Python pro začátečníky</div>
<div class="mm"><span class="badge b-n" style="height:18px">Playlist · 12 videí</span> Kódovna · {src_ic('Telegram')} Telegram</div></div></div>
<div>{mbadge('yt-dlp')}</div>
<div class="pg"><div class="bar"><i style="width:0%"></i></div><div class="l"><span>Čeká · 3. ve frontě</span><span>0 / 12</span></div></div>
<div class="muted">—</div><div class="muted">—</div>
<div class="acts"><span class="ibtn">{ic('pause', 15)}</span><span class="ibtn">{ic('x', 15)}</span></div></div>""")
    for n, title in enumerate(PL_CHILDREN):
        rows.append(f"""<div class="tr child"><span></span>
<div class="vid" style="padding-left:30px">{thumb('t2', 72, 40, ['14:02', '18:47', '22:15'][n])}<div class="grow"><div class="b5 ell fs13">{title}</div>
<div class="mm">1080p · ~{['310', '402', '488'][n]} MB</div></div></div>
<div></div><div class="t2 fs12">Čeká</div><div></div><div></div><div class="acts"><span class="ibtn">{ic('pause', 14)}</span></div></div>""")
    rows.append(f"""<div class="tr child" style="padding-top:7px;padding-bottom:7px"><span></span><div style="padding-left:30px" class="fs12 b5"><span style="color:var(--accent)">Zobrazit dalších 9 videí</span></div><div></div><div></div><div></div><div></div><div></div></div>""")
    for r in WAIT[:1]:
        rows.append(f"""<div class="tr"><span class="grip">{ic('grip')}</span>
<div class="vid">{thumb(r['t'], 112, 63, r['dur'])}<div class="grow"><div class="tt ell">{r['title']}</div>
<div class="mm">{r['ch']} · {r['res']} · ~{r['size']} · {src_ic(r['src'])} {r['src']}</div></div></div>
<div>{mbadge(r['m'])}</div><div class="pg"><div class="bar"><i style="width:0%"></i></div><div class="l"><span>Čeká · 4. ve frontě</span><span></span></div></div>
<div class="muted">—</div><div class="muted">—</div>
<div class="acts"><span class="ibtn">{ic('pause', 15)}</span><span class="ibtn">{ic('x', 15)}</span></div></div>""")
    p = PAUSED
    rows.append(f"""<div class="tr dim"><span class="grip">{ic('grip')}</span>
<div class="vid"><div class="fade">{thumb(p['t'], 112, 63, p['dur'])}</div><div class="grow"><div class="tt ell fade">{p['title']}</div>
<div class="mm"><span class="badge b-warn">{ic('pause', 11)} Pozastaveno · přeskakuje se</span> <span class="fade">{p['ch']} · {p['res']}</span></div></div></div>
<div class="fade">{mbadge(p['m'])}</div><div class="pg fade"><div class="bar"><i style="width:0%"></i></div><div class="l"><span>Pozastaveno</span><span></span></div></div>
<div class="muted">—</div><div class="muted">—</div>
<div class="acts"><span class="btn sm">{ic('play', 12)} Povolit</span></div></div>""")
    for r in WAIT[1:]:
        rows.append(f"""<div class="tr"><span class="grip">{ic('grip')}</span>
<div class="vid">{thumb(r['t'], 112, 63, r['dur'])}<div class="grow"><div class="tt ell">{r['title']}</div>
<div class="mm">{r['ch']} · {r['res']} · ~{r['size']} · {src_ic(r['src'])} {r['src']}</div></div></div>
<div>{mbadge(r['m'])}</div><div class="pg"><div class="bar"><i style="width:0%"></i></div><div class="l"><span>Čeká</span><span></span></div></div>
<div class="muted">—</div><div class="muted">—</div>
<div class="acts"><span class="ibtn">{ic('pause', 15)}</span><span class="ibtn">{ic('x', 15)}</span></div></div>""")

    body = f"""{a_head('Fronta', dark)}<div class="a-body">
<div class="card" style="padding:14px;display:flex;gap:10px;align-items:center">
<div class="input focus grow">{ic('link', 16)}<span class="val">https://www.youtube.com/playlist?list=PL9kX2fQ</span><span style="width:1px;height:18px;background:var(--accent)"></span></div>
<div class="input" style="width:190px;color:var(--text)">{ic('film', 15)}<span class="grow fs13">Nejvyšší kvalita</span>{ic('down', 14)}</div>
<span class="btn primary" style="height:40px;padding:0 18px">{ic('plus', 15)} Přidat do fronty</span></div>
<div class="row gap10"><h2>Fronta</h2>
<span class="chip"><span class="dot g" style="box-shadow:none"></span>Probíhá <b>2 / 2</b></span><span class="chip">Čeká <b>17</b></span><span class="chip">Pozastaveno <b>1</b></span>
<span class="grow"></span><span class="t2 fs12 row gap6">{ic('grip', 14)} Přetažením změníte pořadí · stahuje se v pořadí přidání</span></div>
<div class="card tbl"><div class="tr h"><span></span><span>Video</span><span>Metoda</span><span>Průběh</span><span>Rychlost</span><span>Zbývá</span><span></span></div>
{''.join(rows)}</div></div>{footer_status()}"""
    return body


EXTRA_CSS += ".fs13{font-size:13px}"


def a_history(dark):
    H = [
        dict(t="t8", dur="10:00:00", title="Lesní ticho – 10 hodin přírody", ch="Calm Earth", res="1080p", st="ok", m="yt-dlp", size="3,2 GB", when="dnes 14:32", src="Telegram"),
        dict(t="t9", dur="17:22", title="Výstup na Sněžku v zimě – vlog", ch="Hory s Tomem", res="2160p", st="ok", m="yt-dlp", size="2,7 GB", when="dnes 11:05", src="GUI"),
        dict(t="t6", dur="2:01:40", title="Exkluzivní koncert pro členy", ch="Jazz Dock", res="—", st="err", m="yt-dlp", size="—", when="dnes 09:48", src="Telegram",
             err="Vyžadováno přihlášení. Nastavte cookies v Nastavení › Přístup."),
        dict(t="t3", dur="6:12", title="Pražské mosty v noci", ch="prahavecer.cz", res="1080p", st="ok", m="sniffer", size="640 MB", when="včera 22:17", src="GUI"),
        dict(t="t7", dur="45:03", title="Chorvatsko: plavba mezi ostrovy", ch="Slow TV Europe", res="1440p", st="ok", m="yt-dlp", size="4,1 GB", when="včera 21:40", src="CLI"),
        dict(t="t5", dur="58:10", title="Neuronové sítě – přednáška 4", ch="Matfyz přednášky", res="1080p", st="cancel", m="yt-dlp", size="—", when="včera 18:02", src="GUI"),
        dict(t="t4", dur="15:47", title="Perfektní pizza z domácí trouby", ch="Pekárna u Hanky", res="1080p", st="ok", m="yt-dlp", size="820 MB", when="7. 11. 2026", src="Telegram"),
        dict(t="t1", dur="9:12", title="Lofoty – polární záře", ch="Nordic Drone Films", res="2160p", st="ok", m="yt-dlp", size="1,9 GB", when="6. 11. 2026", src="GUI"),
        dict(t="t2", dur="31:20", title="Git za 30 minut", ch="Kódovna", res="1080p", st="ok", m="yt-dlp", size="540 MB", when="6. 11. 2026", src="GUI"),
    ]
    st = {"ok": '<span class="badge b-ok">' + ic('check', 11) + ' Hotovo</span>',
          "err": '<span class="badge b-err">' + ic('alert', 11) + ' Chyba</span>',
          "cancel": '<span class="badge b-n">' + ic('x', 11) + ' Zrušeno</span>'}
    rows = []
    for h in H:
        sub = (f'<div class="mm err" style="white-space:normal">{ic("alert", 12)} {h["err"]}</div>' if h.get("err")
               else f'<div class="mm">{h["ch"]} · {h["res"]} · {src_ic(h["src"])} {h["src"]}</div>')
        act = (f'<span class="btn sm">{ic("refresh", 12)} Znovu</span>' if h["st"] != "ok"
               else f'<span class="ibtn" title="Otevřít složku">{ic("folder", 15)}</span><span class="ibtn">{ic("play", 15)}</span>')
        rows.append(f"""<div class="hr">{thumb(h['t'], 104, 58, h['dur'])}<div style="min-width:0"><div class="tt ell b6 fs14">{h['title']}</div>{sub}</div>
<div>{st[h['st']]}</div><div>{mbadge(h['m'])}</div><div class="b5">{h['size']}</div><div class="t2">{h['when']}</div><div class="acts">{act}</div></div>""")
    return f"""{a_head('Historie', dark)}<div class="a-body">
<div class="row gap10"><h1 style="font-size:20px">Historie</h1><span class="t2" style="margin-left:6px">142 stažených videí · 186 GB</span><span class="grow"></span>
<div class="input sm" style="width:280px">{ic('search', 15)}<span>Hledat v historii…</span></div>
<span class="seg"><span class="on">Vše</span><span>Hotovo</span><span>Chyby</span><span>Zrušeno</span></span>
<div class="input sm" style="width:196px;color:var(--text)">{ic('calendar', 14)}<span class="grow ell">Posledních 30 dní</span>{ic('down', 13)}</div>
<span class="btn sm">{ic('trash', 13)} Vymazat historii</span></div>
<div class="card tbl"><div class="hr h"><span></span><span>Video</span><span>Stav</span><span>Metoda</span><span>Velikost</span><span>Dokončeno</span><span></span></div>
{''.join(rows)}</div></div>{footer_status()}"""


EXTRA_CSS += """
.hr{display:grid;grid-template-columns:104px minmax(0,1fr) 96px 80px 80px 110px 110px;gap:16px;align-items:center;padding:10px 16px;border-top:1px solid var(--border)}
.hr.h{border-top:none;background:var(--surface2);padding-top:9px;padding-bottom:9px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.mm{font-size:12px;color:var(--text2);margin-top:3px;display:flex;align-items:center;gap:6px}
.mm.err{color:var(--err2)}
"""

# ================================================================ VARIANTA B
EXTRA_CSS += """
.b-wrap{flex:1;min-height:0;display:flex}
.side{width:232px;flex:none;background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;padding:18px 14px}
.nav{display:flex;align-items:center;gap:10px;height:38px;padding:0 12px;border-radius:9px;color:var(--text2);font-weight:500;font-size:14px}
.nav.on{background:var(--accent-soft);color:var(--accent-text)}
.nav .n{margin-left:auto;font-size:11px;font-weight:700;color:var(--text2);background:var(--surface2);border:1px solid var(--border);border-radius:99px;padding:0 7px}
.nav.on .n{background:var(--surface);border-color:transparent;color:var(--accent-text)}
.b-main{flex:1;min-width:0;padding:24px 28px;display:flex;flex-direction:column;gap:18px;overflow:hidden}
.stat{padding:14px 16px}
.stat .k{font-size:12px;color:var(--text2);display:flex;align-items:center;gap:6px}
.stat .v{font-size:24px;font-weight:700;margin-top:6px;letter-spacing:-.02em}
.stat .s{font-size:12px;color:var(--muted);margin-top:2px}
.run{display:flex;gap:18px;padding:16px;align-items:center}
.qr{display:grid;grid-template-columns:18px 26px 96px minmax(0,1fr) 90px 160px 64px;gap:14px;align-items:center;padding:9px 16px;border-top:1px solid var(--border)}
.qr:first-child{border-top:none}
.pos{font-size:12px;color:var(--muted);font-weight:600;text-align:right}
.sec{display:flex;align-items:center;gap:10px}
"""


def b_side(active):
    items = [("Fronta", "list", "20"), ("Historie", "history", None), ("Nastavení", "settings", None), ("Enginy", "cpu", None)]
    nav = "".join(f'<div class="nav {"on" if n == active else ""}">{ic(i, 17)}{n}{f"<span class=n>{c}</span>" if c else ""}</div>' for n, i, c in items)
    return f"""<div class="side"><div class="logo" style="padding:0 6px 22px">{'<div class="mk">' + ic('download', 16) + '</div>'}VidDown</div>
<div style="display:flex;flex-direction:column;gap:3px">{nav}</div><div class="grow"></div>
<div class="card" style="padding:12px;background:var(--surface2)"><div class="row fs12 t2" style="justify-content:space-between"><span class="row gap6">{ic('hdd', 14)} Disk</span><span><b style="color:var(--text)">184 GB</b> volno</span></div>
<div class="bar" style="margin-top:8px"><i style="width:63%;background:var(--text2)"></i></div><div class="fs11 muted" style="margin-top:6px">~/Videa/VidDown</div></div>
<div class="row gap8 fs12 t2" style="padding:14px 6px 4px"><span class="dot g"></span>Telegram bot připojen</div>
<div class="row gap8 fs12 t2" style="padding:6px 6px"><span class="row gap6">{ic('moon', 14)} Tmavý režim</span><span class="grow"></span><span class="toggle"></span></div>
<div class="fs11 muted" style="padding:6px 6px 0">VidDown 0.1.0 · CS</div></div>"""


def b_queue(dark):
    runs = ""
    for r in RUN:
        runs += f"""<div class="card run">{thumb(r['t'], 176, 99, r['dur'], r['res'])}
<div class="grow"><div class="row gap8"><span class="b6 fs15 ell">{r['title']}</span>{mbadge(r['m'])}</div>
<div class="t2 fs12" style="margin-top:4px" class_="row">{r['ch']} · {r['res']} · přidáno přes {r['src']}</div>
<div class="bar thick {'sn' if r['m'] == 'sniffer' else ''}" style="margin-top:14px"><i style="width:{r['pct']}%"></i></div>
<div class="row fs12 t2" style="margin-top:8px;gap:18px"><span><b style="color:var(--text);font-size:13px">{r['pct']} %</b></span><span>{r['done']} z {r['size']}</span>
<span class="row gap4">{ic('bolt', 13)} {r['speed']}</span><span class="row gap4">{ic('clock', 13)} zbývá {r['eta']}</span></div></div>
<div class="row gap6" style="align-self:flex-start"><span class="ibtn b">{ic('pause', 15)}</span><span class="ibtn b">{ic('x', 15)}</span></div></div>"""
    q = []
    q.append(f"""<div class="qr"><span class="grip">{ic('grip', 15)}</span><span class="pos">1</span>{thumb('ph', 96, 54)}
<div style="min-width:0"><div class="b6 ell">vimeo.com/824119370</div><div class="mm"><span class="spin" style="width:11px;height:11px"></span> Kontroluji URL… · {src_ic('Telegram')} Telegram</div></div>
<div><span class="badge b-n">—</span></div><div class="t2 fs12">—</div><div class="acts"><span class="ibtn">{ic('pause', 15)}</span><span class="ibtn">{ic('x', 15)}</span></div></div>""")
    q.append(f"""<div class="qr"><span class="grip">{ic('grip', 15)}</span><span class="pos">2</span>{thumb('t2', 96, 54, None, None, 'stack')}
<div style="min-width:0"><div class="b6 ell">Python pro začátečníky</div><div class="mm"><span class="badge b-n" style="height:18px">Playlist · 12 videí</span> Kódovna · {src_ic('Telegram')} Telegram</div></div>
<div>{mbadge('yt-dlp')}</div><div class="t2 fs12">~5,4 GB · 1080p</div><div class="acts"><span class="ibtn">{ic('down', 15)}</span><span class="ibtn">{ic('pause', 15)}</span><span class="ibtn">{ic('x', 15)}</span></div></div>""")
    pos = 3
    for r in WAIT[:1]:
        q.append(f"""<div class="qr"><span class="grip">{ic('grip', 15)}</span><span class="pos">{pos}</span>{thumb(r['t'], 96, 54, r['dur'])}
<div style="min-width:0"><div class="b6 ell">{r['title']}</div><div class="mm">{r['ch']} · {src_ic(r['src'])} {r['src']}</div></div>
<div>{mbadge(r['m'])}</div><div class="t2 fs12">~{r['size']} · {r['res']}</div><div class="acts"><span class="ibtn">{ic('pause', 15)}</span><span class="ibtn">{ic('x', 15)}</span></div></div>""")
        pos += 1
    p = PAUSED
    q.append(f"""<div class="qr" style="background:var(--warn-soft)"><span class="grip">{ic('grip', 15)}</span><span class="pos">{pos}</span><div style="opacity:.5">{thumb(p['t'], 96, 54, p['dur'])}</div>
<div style="min-width:0"><div class="b6 ell" style="opacity:.6">{p['title']}</div><div class="mm"><span class="badge b-warn">{ic('pause', 11)} Pozastaveno · přeskakuje se</span></div></div>
<div style="opacity:.5">{mbadge(p['m'])}</div><div class="t2 fs12" style="opacity:.6">~{p['size']} · {p['res']}</div><div class="acts"><span class="btn sm">{ic('play', 12)} Povolit</span></div></div>""")
    pos += 1
    for r in WAIT[1:]:
        q.append(f"""<div class="qr"><span class="grip">{ic('grip', 15)}</span><span class="pos">{pos}</span>{thumb(r['t'], 96, 54, r['dur'])}
<div style="min-width:0"><div class="b6 ell">{r['title']}</div><div class="mm">{r['ch']} · {src_ic(r['src'])} {r['src']}</div></div>
<div>{mbadge(r['m'])}</div><div class="t2 fs12">~{r['size']} · {r['res']}</div><div class="acts"><span class="ibtn">{ic('pause', 15)}</span><span class="ibtn">{ic('x', 15)}</span></div></div>""")
        pos += 1

    return f"""<div class="b-wrap">{b_side('Fronta')}<div class="b-main">
<div class="row gap16"><div><h1>Fronta</h1><div class="t2" style="margin-top:3px">Stahuje se postupně v pořadí přidání</div></div><div class="grow"></div>
<div class="input" style="width:520px">{ic('link', 16)}<span>Vložte URL videa, playlistu nebo kanálu…</span></div>
<span class="btn primary" style="height:40px">{ic('plus', 15)} Přidat</span></div>
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px">
<div class="card stat"><div class="k">{ic('download', 14)} Probíhá</div><div class="v">2 <span class="t2" style="font-size:15px;font-weight:500">/ 2</span></div><div class="s">souběžná stahování</div></div>
<div class="card stat"><div class="k">{ic('list', 14)} Ve frontě</div><div class="v">17</div><div class="s">~ 21,4 GB · 1 pozastaveno</div></div>
<div class="card stat"><div class="k">{ic('bolt', 14)} Rychlost</div><div class="v">8,6 <span class="t2" style="font-size:15px;font-weight:500">MB/s</span></div><div class="s">limit 10 MB/s</div></div>
<div class="card stat"><div class="k">{ic('check', 14)} Dnes staženo</div><div class="v">6</div><div class="s">1 chyba · 9,8 GB</div></div></div>
<div class="sec"><h2>Právě se stahuje</h2></div>
<div style="display:flex;flex-direction:column;gap:10px">{runs}</div>
<div class="sec"><h2>Čeká ve frontě</h2><span class="chip"><b>17</b></span><span class="grow"></span><span class="t2 fs12 row gap6">{ic('grip', 14)} Přetažením změníte pořadí</span></div>
<div class="card" style="overflow:hidden;flex:1;min-height:0">{''.join(q)}</div>
</div></div>"""


def b_settings(dark):
    def fld(label, ctrl, hint=None):
        h = f'<div class="fs12 muted" style="margin-top:2px">{hint}</div>' if hint else ""
        return f'<div class="fld"><div><div class="b5">{label}</div>{h}</div><div class="row gap8">{ctrl}</div></div>'

    def sect(icon, title, inner):
        return f'<div class="card sect"><div class="row gap8 sh">{ic(icon, 16)}<h2>{title}</h2></div>{inner}</div>'

    days = "".join(f'<span class="chip on" style="height:24px;padding:0 8px">{d}</span>' for d in ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"])
    tokens = "".join(f'<span class="chip mono" style="height:22px;font-size:11px">{t}</span>' for t in ["{název}", "{kanál}", "{playlist}", "{datum}", "{rozlišení}", "{id}"])

    s1 = sect("download", "Stahování",
              fld("Cílová složka", f'<div class="input sm mono fs12" style="width:230px"><span class="val">~/Videa/VidDown</span></div><span class="btn sm">{ic("folder", 13)} Změnit</span>')
              + fld("Souběžná stahování", f'<span class="ibtn b">{ic("minus", 14)}</span><span class="b6 fs15" style="width:22px;text-align:center">2</span><span class="ibtn b">{ic("plus", 14)}</span>', "Platí okamžitě")
              + fld("Kvalita", '<span class="seg"><span class="on">Maximální</span><span>Kompatibilita</span></span>', "Kompatibilita = MP4 / H.264")
              + fld("Z kanálu stahovat", '<span class="chip on">' + ic('check', 12) + ' Videa</span><span class="chip">Shorts</span><span class="chip">Živé přenosy</span>')
              + fld("Potvrdit playlist nad", '<div class="input sm" style="width:70px"><span class="val">50</span></div><span class="t2">videí</span>'))
    s2 = sect("tag", "Pojmenování a složky",
              f'<div class="fld" style="display:block"><div class="b5">Šablona názvu souboru</div>'
              f'<div class="input sm mono" style="margin-top:8px"><span class="val">{{kanál}}_{{název}}</span></div>'
              f'<div class="row gap6" style="margin-top:8px;flex-wrap:wrap">{tokens}</div>'
              f'<div class="fs12 t2" style="margin-top:8px">Náhled: <span class="mono" style="color:var(--text)">Nordic Drone Films_Islandské fjordy z dronu – 4K.mp4</span></div></div>'
              + fld("Samostatná složka pro playlist", '<span class="toggle on"></span>', "Složka pojmenovaná podle playlistu")
              + fld("Samostatná složka pro kanál", '<span class="toggle on"></span>', "Složka pojmenovaná podle kanálu")
              + fld("Miniatura JPG vedle videa", '<span class="badge b-n">' + ic('lock', 11) + ' Vždy</span>'))
    s3 = sect("clock", "Rychlost a plánování",
              fld("Omezit rychlost", '<div class="input sm" style="width:90px"><span class="val">10</span><span class="grow"></span><span>MB/s</span></div><span class="toggle on"></span>', "Celkem pro všechna stahování")
              + fld("Stahovat jen v časovém okně", '<div class="input sm mono" style="width:130px"><span class="val">22:00 – 06:00</span></div><span class="toggle on"></span>')
              + f'<div class="fld"><div class="b5">Dny</div><div class="row gap4">{days}</div></div>')
    s4 = sect("cookie", "Přístup a síť",
              fld("Cookies", f'<span class="badge b-ok">{ic("check", 11)} cookies.txt · 3. 11.</span><span class="btn sm">Nahradit</span>', "Pro členský a věkově omezený obsah")
              + fld("Proxy", '<span class="t2 fs12">vypnuto</span><span class="toggle"></span>')
              + fld("Heslo do GUI", '<span class="mono t2">••••••••</span><span class="btn sm">Změnit</span>')
              + fld("Přístup ze sítě", '<span class="t2 fs12">jen tento počítač</span><span class="toggle"></span>'))
    s5 = sect("send", "Telegram",
              fld("Bot", '<span class="dot g"></span><span class="b5">@viddown_jk_bot</span><span class="btn sm">Změnit token</span>')
              + fld("Povolené chat ID", '<span class="mono t2">18•••••42</span>')
              + fld("Po kontrole URL", '<span class="seg"><span class="on">Stáhnout hned</span><span>Zeptat se</span></span>')
              + fld("Oznámení", '<span class="seg"><span class="on">Jen chyby</span><span>Vše</span></span>'))
    s6 = sect("palette", "Vzhled a jazyk",
              fld("Jazyk", '<span class="seg"><span class="on">Čeština</span><span>English</span></span>')
              + fld("Motiv", '<span class="seg"><span>Světlý</span><span>Tmavý</span><span class="on">Podle systému</span></span>'))
    return f"""<div class="b-wrap">{b_side('Nastavení')}<div class="b-main" style="gap:16px">
<div class="row gap16"><div><h1>Nastavení</h1><div class="t2" style="margin-top:3px">Změny se ukládají automaticky a platí okamžitě</div></div><div class="grow"></div>
<span class="btn sm">{ic('download', 13)} Exportovat</span><span class="btn sm">Importovat</span></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:start">
<div style="display:flex;flex-direction:column;gap:14px">{s1}{s3}</div>
<div style="display:flex;flex-direction:column;gap:14px">{s2}{s4}</div></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:start">{s5}{s6}</div>
</div></div>"""


EXTRA_CSS += """
.sect{padding:6px 18px 6px}
.sect .sh{padding:12px 0 10px;color:var(--text2)}
.sect .sh h2{color:var(--text)}
.fld{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:10px 0;border-top:1px solid var(--border)}
"""

# ================================================================ VARIANTA C
EXTRA_CSS += """
.c-top{height:70px;flex:none;display:flex;align-items:center;gap:18px;padding:0 28px;background:var(--surface);border-bottom:1px solid var(--border)}
.c-body{flex:1;min-height:0;padding:22px 28px;display:flex;flex-direction:column;gap:16px;overflow:hidden}
.big{position:relative;border-radius:14px;overflow:hidden;height:232px}
.big .th{position:absolute;inset:0;border-radius:0}
.big .ov{position:absolute;left:0;right:0;bottom:0;padding:16px 18px;background:rgba(8,10,16,.72);color:#fff}
.big .ov .bar{background:rgba(255,255,255,.25)}
.big .top{position:absolute;left:14px;top:14px;right:14px;display:flex;gap:6px}
.big .top .badge{background:rgba(0,0,0,.55);color:#fff}
.glass{width:32px;height:32px;border-radius:9px;background:rgba(0,0,0,.5);color:#fff;display:flex;align-items:center;justify-content:center}
.qc{overflow:hidden;position:relative}
.qc .th{border-radius:0}
.qc .bd{padding:10px 12px}
.qc .over{position:absolute;left:0;right:0;top:0;height:131px;display:flex;align-items:center;justify-content:center}
.posb{position:absolute;left:8px;top:8px;background:rgba(0,0,0,.6);color:#fff;font-size:11px;font-weight:700;border-radius:6px;padding:1px 7px}
"""


def c_top(active, dark):
    icons = [("Fronta", "list"), ("Historie", "history"), ("Enginy", "cpu"), ("Nastavení", "settings")]
    nav = "".join(f'<span class="btn sm {"" if n == active else "ghost"}" style="{"background:var(--accent-soft);color:var(--accent-text);border-color:transparent" if n == active else ""}">{ic(i, 15)} {n}</span>' for n, i in icons)
    return f"""<div class="c-top"><div class="logo"><div class="mk">{ic('download', 16)}</div>VidDown</div>
<div class="input" style="height:44px;border-radius:12px;flex:0 0 600px;margin-left:12px">{ic('link', 17)}<span class="grow ell">Vložte odkaz a stiskněte Enter</span><span class="chip" style="height:26px">{ic('film', 13)} Nejvyšší kvalita {ic('down', 12)}</span></div>
<div class="grow"></div><div class="row gap4">{nav}</div><span class="ibtn b">{ic('sun' if dark else 'moon', 15)}</span></div>"""


def c_queue(dark):
    bigs = ""
    for r in RUN:
        bigs += f"""<div class="big">{thumb(r['t'], 10, 10).replace('width:10px;height:10px', 'width:100%;height:100%')}
<div class="top">{mbadge(r['m']).replace('class="badge', 'class="badge')}<span class="badge">{r['res']}</span><span class="grow"></span><span class="glass">{ic('pause', 15)}</span><span class="glass">{ic('x', 15)}</span></div>
<div class="ov"><div class="row" style="justify-content:space-between;align-items:flex-end"><div style="min-width:0"><div class="b6" style="font-size:17px">{r['title']}</div>
<div class="fs12" style="opacity:.8;margin-top:3px">{r['ch']} · přidáno přes {r['src']}</div></div><div style="font-size:26px;font-weight:700">{r['pct']} %</div></div>
<div class="bar thick" style="margin-top:10px"><i style="width:{r['pct']}%;{'background:#F79009' if r['m'] == 'sniffer' else 'background:#fff'}"></i></div>
<div class="row fs12" style="gap:16px;margin-top:8px;opacity:.85"><span>{r['done']} z {r['size']}</span><span>{r['speed']}</span><span>zbývá {r['eta']}</span></div></div></div>"""

    cards = []
    cards.append(f"""<div class="card qc">{thumb('ph', 10, 10).replace('width:10px;height:10px', 'width:100%;height:131px')}<span class="posb">1</span>
<div class="bd"><div class="b6 ell">vimeo.com/824119370</div><div class="mm"><span class="spin" style="width:11px;height:11px"></span>Kontroluji URL…</div></div></div>""")
    cards.append(f"""<div class="card qc">{thumb('t2', 10, 10).replace('width:10px;height:10px', 'width:100%;height:131px')}<span class="posb">2</span>
<span class="badge" style="position:absolute;right:8px;top:8px;background:rgba(0,0,0,.65);color:#fff">{ic('list', 11)} 12 videí</span>
<div class="bd"><div class="b6 ell">Python pro začátečníky</div><div class="mm">Playlist · Kódovna · {src_ic('Telegram')}</div></div></div>""")
    cards.append(f"""<div class="card qc">{thumb(WAIT[0]['t'], 10, 10, WAIT[0]['dur']).replace('width:10px;height:10px', 'width:100%;height:131px')}<span class="posb">3</span>
<div class="bd"><div class="b6 ell">{WAIT[0]['title']}</div><div class="mm">{WAIT[0]['ch']} · {WAIT[0]['res']}</div></div></div>""")
    p = PAUSED
    cards.append(f"""<div class="card qc">{thumb(p['t'], 10, 10, p['dur']).replace('width:10px;height:10px', 'width:100%;height:131px;opacity:.35')}<span class="posb">4</span>
<div class="over"><span class="btn sm">{ic('play', 12)} Povolit</span></div>
<div class="bd"><div class="b6 ell" style="opacity:.6">{p['title']}</div><div class="mm"><span class="badge b-warn">{ic('pause', 11)} Pozastaveno</span></div></div></div>""")
    for i, r in enumerate(WAIT[1:]):
        cards.append(f"""<div class="card qc">{thumb(r['t'], 10, 10, r['dur']).replace('width:10px;height:10px', 'width:100%;height:131px')}<span class="posb">{5 + i}</span>
<div class="bd"><div class="b6 ell">{r['title']}</div><div class="mm">{r['ch']} · {r['res']}</div></div></div>""")
    extra = [("t9", "11:40", "Krkonoše – podzimní hřebenovka", "Hory s Tomem", "2160p"),
             ("t8", "3:00:00", "Déšť v lese – 3 hodiny", "Calm Earth", "1080p"),
             ("t1", "7:25", "Faerské ostrovy z výšky", "Nordic Drone Films", "2160p"),
             ("t4", "19:02", "Croissanty jako z Paříže", "Pekárna u Hanky", "1080p")]
    for i, (t, d, ti, ch, res) in enumerate(extra):
        cards.append(f"""<div class="card qc">{thumb(t, 10, 10, d).replace('width:10px;height:10px', 'width:100%;height:131px')}<span class="posb">{7 + i}</span>
<div class="bd"><div class="b6 ell">{ti}</div><div class="mm">{ch} · {res}</div></div></div>""")
    return f"""{c_top('Fronta', dark)}<div class="c-body">
<div class="row gap10"><h2 style="font-size:17px">Právě se stahuje</h2><span class="chip">Souběžně <b>2</b></span><span class="grow"></span>
<span class="row gap6 t2 fs12">{ic('bolt', 14)} 8,6 MB/s celkem</span><span class="btn sm">{ic('pause', 13)} Pozastavit frontu</span></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">{bigs}</div>
<div class="row gap10" style="margin-top:4px"><h2 style="font-size:17px">Ve frontě</h2><span class="chip"><b>17</b></span><span class="chip">1 pozastaveno</span><span class="grow"></span>
<span class="t2 fs12 row gap6">{ic('grip', 14)} Přetažením karet změníte pořadí</span></div>
<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:14px">{''.join(cards)}</div>
</div>{footer_status()}"""


def c_engines(dark):
    def eng(name, desc, ver, status, history, note=None, upd=None):
        hist = ""
        for v, d, active in history:
            right = '<span class="badge b-yt">Aktivní</span>' if active else f'<span class="btn sm">{ic("undo", 12)} Vrátit</span>'
            hist += f'<div class="row" style="padding:8px 0;border-top:1px solid var(--border);gap:10px"><span class="mono b5">{v}</span><span class="fs12 muted">{d}</span><span class="grow"></span>{right}</div>'
        n = f'<div class="fs12" style="margin-top:10px;padding:8px 10px;border-radius:8px;background:var(--warn-soft);color:var(--warn)">{note}</div>' if note else ""
        u = f'<span class="badge b-yt">{upd}</span>' if upd else ""
        return f"""<div class="card" style="padding:18px"><div class="row gap10"><div class="mk" style="width:36px;height:36px;border-radius:10px;background:var(--accent-soft);color:var(--accent-text);display:flex;align-items:center;justify-content:center">{ic('cpu', 18)}</div>
<div class="grow"><div class="b6 fs15">{name}</div><div class="fs12 t2">{desc}</div></div>{status}</div>
<div class="row" style="margin-top:16px;align-items:baseline;gap:10px"><span class="mono" style="font-size:22px;font-weight:700">{ver}</span>{u}</div>
<div class="fs12 muted" style="margin-top:2px">aktivní verze · test prošel dnes 06:00</div>{n}
<div class="row gap8" style="margin-top:14px"><span class="btn sm primary">{ic('refresh', 12)} Aktualizovat</span><span class="btn sm">{ic('check', 12)} Spustit test</span></div>
<div style="margin-top:14px"><div class="fs11 muted b6" style="text-transform:uppercase;letter-spacing:.04em;padding-bottom:6px">Uchované verze</div>{hist}</div></div>"""

    ok = f'<span class="badge b-ok">{ic("check", 11)} Funkční</span>'
    e1 = eng("yt-dlp", "YouTube a tisíce dalších webů", "2026.11.05", ok,
             [("2026.11.05", "nainstalováno 5. 11.", True), ("2026.10.22", "22. 10.", False), ("2026.10.01", "1. 10.", False)],
             note="Verze 2026.11.09 neprošla testem (HTTP 403 u testovací URL). Ponechána 2026.11.05.")
    e2 = eng("Deno", "JavaScript runtime pro YouTube", "2.6.3", ok,
             [("2.6.3", "nainstalováno 2. 11.", True), ("2.6.1", "14. 10.", False)])
    e3 = eng("ffmpeg", "Spojování a převod videa", "9.0.1", ok,
             [("9.0.1", "nainstalováno 28. 10.", True), ("9.0.0", "2. 9.", False), ("8.0.1", "11. 7.", False)])
    log = [
        ("06:00:02", "yt-dlp", "nalezena nová verze 2026.11.09"),
        ("06:00:09", "yt-dlp", "stažena 2026.11.09 do engines/yt-dlp/2026.11.09"),
        ("06:00:10", "test", "2026.11.09 --version … <span class=lok>OK</span>"),
        ("06:00:17", "test", "2026.11.09 metadata testovací URL … <span class=lerr>CHYBA (HTTP 403)</span>"),
        ("06:00:24", "test", "2026.11.05 metadata testovací URL … <span class=lok>OK</span>"),
        ("06:00:24", "rollback", "nová verze selhala, stará prošla → ponechána 2026.11.05, 2026.11.09 smazána"),
        ("06:00:25", "telegram", "odesláno oznámení o neúspěšné aktualizaci"),
        ("06:00:31", "ffmpeg", "aktuální verze 9.0.1 je nejnovější"),
        ("06:00:33", "deno", "aktuální verze 2.6.3 je nejnovější"),
    ]
    logh = "".join(f'<div><span class="lt">{t}</span> <span class="lc">{c:<8}</span> {m}</div>' for t, c, m in log)
    return f"""{c_top('Enginy', dark)}<div class="c-body">
<div class="row gap16"><div><h1>Enginy</h1><div class="t2" style="margin-top:3px">Každá aktualizace se otestuje. Když nová verze selže, zůstane předchozí funkční.</div></div><div class="grow"></div>
<span class="row gap8 t2 fs12">Automatické aktualizace <span class="toggle on"></span> každých 24 h</span><span class="btn">{ic('refresh', 14)} Zkontrolovat aktualizace</span></div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;align-items:start">{e1}{e2}{e3}</div>
<div class="card" style="padding:0;overflow:hidden;flex:1;min-height:0"><div class="row gap8" style="padding:12px 16px;border-bottom:1px solid var(--border)">{ic('terminal', 15)}<h2>Protokol poslední kontroly</h2><span class="fs12 muted">dnes 06:00</span><span class="grow"></span><span class="fs12 t2">Chromium 141 · aktualizuje se s aplikací</span></div>
<div class="log mono">{logh}</div></div>
</div>{footer_status()}"""


EXTRA_CSS += """
.log{padding:12px 16px;font-size:12px;line-height:21px;background:#0B0E14;color:#C9D1E0;height:100%;white-space:pre}
.log .lt{color:#6B7385}.log .lc{color:#8B85FF}.lok{color:#47CD89;font-weight:700}.lerr{color:#F97066;font-weight:700}
"""

# ================================================================ titulní strana
def cover():
    def tile(v, name, desc, pages, kind):
        return f"""<div class="card" style="padding:22px"><div class="row gap10"><span class="logo"><span class="mk" style="width:34px;height:34px">{v}</span></span>
<div><div class="b6 fs15">{name}</div><div class="fs12 t2">{pages}</div></div></div>
<div class="t2" style="margin-top:14px;line-height:20px">{desc}</div>
<div style="margin-top:16px;display:flex;gap:8px">{kind}</div></div>"""
    t = lambda k: thumb(k, 96, 54)
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}{EXTRA_CSS}
.cv{{width:1440px;height:960px;background:var(--bg);padding:90px 110px;display:flex;flex-direction:column}}</style></head><body><div class="cv">
<div class="logo" style="font-size:20px"><div class="mk" style="width:40px;height:40px;border-radius:11px">{ic('download', 22)}</div>VidDown</div>
<h1 style="font-size:44px;margin-top:44px;letter-spacing:-.02em">Návrhy grafického rozhraní</h1>
<div class="t2" style="font-size:17px;margin-top:12px;max-width:820px;line-height:26px">Tři varianty vzhledu webového GUI. Každá je ukázaná na obrazovce Fronta ve světlém i tmavém režimu a na jedné další obrazovce. Ve výsledné aplikaci budou všechny obrazovky (Fronta, Historie, Nastavení, Enginy) v kterékoli zvolené variantě.</div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-top:48px">
{tile('A', 'Klasický seznam', 'Záložky nahoře, fronta jako tabulka s malými miniaturami. Nejvíc položek na obrazovce, nejúspornější.', 'Strany 2–4 · Fronta, Historie', t('t1') + t('t2') + t('t3'))}
{tile('B', 'Postranní panel a přehled', 'Navigace vlevo, souhrnné ukazatele nahoře, běžící stahování jako velké řádky a fronta pod nimi. Nejpřehlednější.', 'Strany 5–7 · Fronta, Nastavení', t('t4') + t('t5') + t('t6'))}
{tile('C', 'Karty s náhledy', 'Běžící stahování přes celou šířku s velkým náhledem, fronta jako mřížka karet. Nejvizuálnější, méně položek najednou.', 'Strany 8–10 · Fronta, Enginy', t('t7') + t('t8') + t('t9'))}
</div><div class="grow"></div>
<div class="row fs12 muted" style="justify-content:space-between"><span>Návrh · listopad 2026 · data ve snímcích jsou ilustrativní</span><span>github.com/iamjk78/VidDown</span></div>
</div></body></html>"""
    (OUT / "00_cover.html").write_text(html, encoding="utf-8")


# ================================================================ sestavení
cover()
page("01_A_fronta_light", cap("A", "Fronta", False), a_queue(False))
page("02_A_fronta_dark", cap("A", "Fronta", True), a_queue(True), dark=True)
page("03_A_historie_light", cap("A", "Historie", False), a_history(False))
page("04_B_fronta_light", cap("B", "Fronta", False), b_queue(False))
page("05_B_fronta_dark", cap("B", "Fronta", True), b_queue(True), dark=True)
page("06_B_nastaveni_light", cap("B", "Nastavení", False), b_settings(False))
page("07_C_fronta_light", cap("C", "Fronta", False), c_queue(False))
page("08_C_fronta_dark", cap("C", "Fronta", True), c_queue(True), dark=True)
page("09_C_enginy_light", cap("C", "Enginy", False), c_engines(False))
print("hotovo:", len(list(OUT.glob("*.html"))), "stran ->", OUT)
