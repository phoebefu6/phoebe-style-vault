#!/usr/bin/env python3
"""Build Phoebe's Style Vault website from the ONE style store.

Source of truth: ~/phoebe-skill-vault/MJ-Studio/Styles/SV-*.md, read through the shared
reader `styles.py` (mj-studio/scripts). This script never keeps its own style list - add or
edit a style in the store, then rerun:

    python3 build.py          # writes index.html, c/*.html, s/*.html, assets/
    python3 build.py --check  # exit 1 if any published text breaks a text rule
    python3 build.py --all    # LOCAL PREVIEW: include rendered visuals not yet approved

Three levels: home (audiences + categories) -> category page (style cards) -> style page.
A style appears only when its card has a rendered example (`own_visual:`) AND Phoebe has
approved it (`visual_approved: YYYY-MM-DD`, set only on her word). works.json is retired. Pasted
inspiration samples (Styles/_samples) are never published - some carry other creators' marks.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(Path.home() / ".claude/skills/mj-studio/scripts"))
import styles  # noqa: E402  the one reader

GALLERY = Path.home() / "Documents/Codex/sketch-ideas-with-phoebe/works"
GALLERY_URL = "https://phoebefu6.github.io/sketch-ideas-with-phoebe/"

# Audience labels and blurbs come ONLY from taxonomy.yml (via styles.registers()); this file
# owns nothing but the tag colours. An audience with no colour here falls back to neutral grey.
TAG_COLOURS = {
    "boardroom": ("#eef2f7", "#2c3e5c"), "stage": ("#fdeee7", "#9a3412"),
    "feed": ("#e8f5ef", "#1f6b4a"), "classroom": ("#fdf6e3", "#8a5a00"),
    "team": ("#fde9ef", "#9b2c55"), "gallery": ("#f4edf7", "#6b2e7a"),
}
REG = {k: (v.get("label", k), v.get("blurb", ""), *TAG_COLOURS.get(k, ("#f1f1f1", "#333333")))
       for k, v in styles.registers().items()}
BANNED = re.compile(r"—|–|\blottery\b|\bbetting\b", re.I)

# ------------------------------------------------------------------ helpers


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def inline(s: str) -> str:
    """Tiny markdown: **bold**, `code`, then escape everything else."""
    out = esc(s)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"`(.+?)`", r"<code>\1</code>", out)
    return out


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def section(body: str, title: str) -> str:
    m = re.search(rf"^##\s*{re.escape(title)}\s*\n(.*?)(?=^##\s|\Z)", body, flags=re.S | re.M)
    return m.group(1).strip() if m else ""


def bullets(text: str) -> list[str]:
    return [l[2:].strip() for l in text.splitlines() if l.startswith("- ")]


# Production fields stay private: credits, run history, tool routing, client colour mappings.
PRIVATE = re.compile(r"^(generation_notes|works_produced|inspired_by|maker|maker route|kill condition|"
                     r"tuning_rule|format|colour roles \(centience.*|\d.*)$", re.I)
# Chinese terms on an English page carry their English (Phoebe's standing rule).
GLOSS = {"仙气": "仙气 (xianqi, otherworldly air)", "意境": "意境 (yijing, poetic mood)",
         "古诗词": "古诗词 (classical Chinese poems)", "一、二、三": "一、二、三 (Chinese numerals)"}


def clean(s: str) -> str:
    s = re.sub(r"\s*-?\s*see \[\[[^\]]+\]\]", "", s)
    s = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    for k, v in GLOSS.items():
        if v not in s:
            s = s.replace(k, v)
    return s


def dna(body: str) -> dict:
    out = {}
    for b in bullets(section(body, "Style DNA")):
        m = re.match(r"\*\*(.+?):\*\*\s*(.*)", b)
        if m and not PRIVATE.match(m.group(1).strip()):
            out[m.group(1).strip()] = clean(m.group(2).strip())
    return out


def hexes(*texts: str) -> list[str]:
    seen = []
    for t in texts:
        for h in re.findall(r"#[0-9a-fA-F]{6}\b", t or ""):
            if h.lower() not in seen:
                seen.append(h.lower())
    return seen[:6]


def cat_label(c: str) -> str:
    known = styles.categories()
    return known.get(c, {}).get("label") or c.replace("-", " ").capitalize()


# ------------------------------------------------------------------ data


def load() -> list[dict]:
    cards = []
    for c in styles.load():
        tags = styles._list(c["fm"].get("tags"))
        if c["retired"] or "brand-locked" in tags:  # client brands never go public
            continue
        body = c["body"]
        d = dna(body)
        plain = section(body, "In plain words")
        topics = []
        for t in bullets(section(body, "Topics it fits")):
            m = re.match(r"\*\*(.+?)\*\*\s*-\s*(.*)", t)
            topics.append((m.group(1), m.group(2)) if m else (t, ""))
        reg = [r for r in c["register"] if r in REG] or ["gallery"]
        sid = c["id"]
        cards.append({
            "id": sid,
            "name": c["name"],
            "slug": slug(f"{sid} {c['name']}"),
            "register": reg,
            "category": c["category"],
            "format": c["format"],
            "maker": c["maker"],
            "axis": clean(c["axis"]),
            "dna": d,
            "elements": {k: clean(v) for k, v in c["elements"].items()},
            "plain": clean(plain),
            "topics": topics,
            "palette": hexes(d.get("palette", ""), c["elements"].get("palette", "")),
            "filed": (c["tried_on"][0] if isinstance(c["tried_on"], list) and c["tried_on"] else ""),
            # Only the rendered lifecycle example. The old design-build gallery charts
            # (works.json) were dropped 2026-11-08: Phoebe called them "so ugly".
            "works": own_visual(c),
            "approved": bool(str(c["fm"].get("visual_approved", "")).strip()),
        })
    # Phoebe 2026-11-08: "only display the style when there is actual visuals built",
    # and only once SHE has approved the visual (card field `visual_approved: YYYY-MM-DD`).
    # `--all` previews every rendered visual locally; never push an --all build.
    return [c for c in cards if c["works"] and (c["approved"] or "--all" in sys.argv)]


def own_visual(c: dict) -> list[dict]:
    """The card's own example visual (`own_visual:` path, relative to the Styles folder)."""
    rel = str(c["fm"].get("own_visual", "")).strip()
    src = styles.STYLES / rel if rel else None
    if not src or not src.is_file():
        return []
    return [{"folder": slug(f"{c['id']} own"), "src": str(src),
             "title": f"The data science lifecycle, set in {c['name']}"}]


# ------------------------------------------------------------------ images


def prep_images(cards: list[dict]) -> None:
    out = ROOT / "assets/works"
    out.mkdir(parents=True, exist_ok=True)
    for c in cards:
        for w in c["works"]:
            src = Path(w["src"]) if w.get("src") else GALLERY / w["folder"] / "full.png"
            for size, suffix in ((1600, ""), (640, "-thumb")):
                dst = out / f"{w['folder']}{suffix}.jpg"
                if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
                    continue
                subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "82",
                                "-Z", str(size), str(src), "--out", str(dst)],
                               check=True, capture_output=True)
    # prune: an image no longer shown (unapproved, dropped) must not stay public in assets/
    keep = {f"{w['folder']}{x}.jpg" for c in cards for w in c["works"] for x in ("", "-thumb")}
    for f in out.glob("*.jpg"):
        if f.name not in keep:
            f.unlink()


def plate(c: dict, big: bool = False) -> str:
    """Placeholder for a style with no finished work yet: its own palette as bands."""
    r = c["register"][0]
    bg, ink = REG[r][2], REG[r][3]
    pal = c["palette"][:5]
    bands = ""
    if pal:
        w = 100 / len(pal)
        bands = "".join(
            f'<rect x="{i * w:.2f}%" y="78%" width="{w + 0.1:.2f}%" height="22%" fill="{h}"/>'
            for i, h in enumerate(pal))
    else:
        bands = f'<rect x="0" y="78%" width="100%" height="22%" fill="{ink}" opacity="0.12"/>'
    num = c["id"].replace("SV-", "")
    fs = min(30 if big else 24, int(600 / max(len(c["name"]), 1)))
    return (f'<svg class="plate" viewBox="0 0 400 300" preserveAspectRatio="xMidYMid slice" role="img" '
            f'aria-label="{esc(c["name"])} - first render pending">'
            f'<rect width="400" height="300" fill="{bg}"/>{bands}'
            f'<text x="24" y="70" font-size="56" font-weight="700" fill="{ink}" opacity="0.18" '
            f'font-family="Georgia, serif">{num}</text>'
            f'<text x="24" y="150" font-size="{fs}" font-weight="600" fill="{ink}" '
            f'font-family="Georgia, serif">{esc(c["name"])}</text>'
            f'<text x="24" y="182" font-size="13" fill="{ink}" opacity="0.75" '
            f'font-family="-apple-system, Segoe UI, sans-serif">first render pending</text></svg>')


def thumb(c: dict, prefix: str) -> str:
    if c["works"]:
        w = c["works"][0]
        return (f'<img src="{prefix}assets/works/{w["folder"]}-thumb.jpg" alt="{esc(w["title"])}" '
                f'loading="lazy">')
    return plate(c)


# ------------------------------------------------------------------ page shell

CSS = """
:root{--bg:#fbfaf8;--card:#ffffff;--ink:#1d1b20;--soft:#5f5866;--line:#e7e2ea;--plum:#6b2e7a;
--plum-soft:#f4edf7;--r:14px}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 -apple-system,BlinkMacSystemFont,
"Segoe UI",Helvetica,Arial,sans-serif}
a{color:inherit}img{display:block;max-width:100%}
.wrap{max-width:1180px;margin:0 auto;padding:0 24px}
header.top{border-bottom:1px solid var(--line);background:#fff}
header.top .wrap{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:64px}
.brand{font-family:Georgia,"Times New Roman",serif;font-size:20px;font-weight:700;text-decoration:none}
.brand span{color:var(--plum)}
.toplink{font-size:14px;color:var(--soft);text-decoration:none}
.toplink:hover{color:var(--plum)}
h1{font-family:Georgia,"Times New Roman",serif;font-size:clamp(30px,4vw,44px);line-height:1.15;margin:36px 0 8px}
h2{font-family:Georgia,"Times New Roman",serif;font-size:24px;margin:44px 0 6px}
h3{font-size:17px;margin:28px 0 8px}
.lede{color:var(--soft);max-width:720px;margin:0 0 8px}
.crumb{font-size:14px;color:var(--soft);margin-top:24px}
.crumb a{text-decoration:none}.crumb a:hover{color:var(--plum)}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:22px 0 18px}
.tabs{display:flex;gap:4px;background:#f1edf3;border-radius:10px;padding:4px}
.tabs button{border:0;background:transparent;font:inherit;font-size:14px;padding:6px 12px;border-radius:7px;
cursor:pointer;color:var(--soft)}
.tabs button[aria-pressed=true]{background:#fff;color:var(--ink);box-shadow:0 1px 2px rgba(0,0,0,.08)}
.search{flex:1 1 220px;max-width:340px;margin-left:auto;border:1px solid var(--line);border-radius:10px;
padding:8px 12px;font:inherit;font-size:14px;background:#fff}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:4px 12px;font:inherit;
font-size:13px;cursor:pointer;color:var(--soft)}
.chip[aria-pressed=true]{background:var(--plum);border-color:var(--plum);color:#fff}
.tag{display:inline-block;font-size:12px;border-radius:999px;padding:2px 10px;margin:0 4px 4px 0;
background:#f1edf3;color:var(--soft)}
@@TAG_CSS@@
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);overflow:hidden;
text-decoration:none;display:flex;flex-direction:column;transition:box-shadow .15s,transform .15s}
.card:hover{box-shadow:0 8px 24px rgba(60,30,70,.10);transform:translateY(-2px)}
.card .pic{aspect-ratio:4/3;background:#f3f0f4;overflow:hidden}
.card .pic img,.card .pic svg{width:100%;height:100%;object-fit:cover}
.collage{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:2px}
.collage>*{overflow:hidden;min-height:0}
.collage img,.collage svg{width:100%;height:100%;object-fit:cover}
.card .meta{padding:14px 16px 16px}
.card .name{font-weight:600;font-size:16px;margin:0 0 4px}
.card .sub{font-size:13px;color:var(--soft);margin:0}
.list{display:none}.list table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);
border-radius:var(--r);overflow:hidden;font-size:14px}
.list th,.list td{text-align:left;padding:10px 14px;border-bottom:1px solid var(--line);vertical-align:top}
.list th{background:#f7f4f8;font-weight:600;color:var(--soft)}
.list a{text-decoration:none;font-weight:600}.list a:hover{color:var(--plum)}
.view-list .grid{display:none}.view-list .list{display:block}
.list-wrap{overflow-x:auto}
.empty{color:var(--soft);padding:24px 0;display:none}
.hero{background:#fff;border:1px solid var(--line);border-radius:var(--r);overflow:hidden;margin:20px 0 6px}
.hero img{width:100%;height:auto;max-height:620px;object-fit:contain;background:#f6f3f7}.hero svg{width:100%;height:auto;aspect-ratio:4/3;max-height:560px}
.cap{font-size:13px;color:var(--soft);margin:6px 0 0}
.cap a{color:var(--plum)}
.cols{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:40px;align-items:start}
.side{background:#fff;border:1px solid var(--line);border-radius:var(--r);padding:18px 20px;position:sticky;top:20px}
.side dt{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--soft);margin-top:12px}
.side dt:first-child{margin-top:0}.side dd{margin:2px 0 0}
.sw{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.sw span{width:28px;height:28px;border-radius:6px;border:1px solid rgba(0,0,0,.08)}
.plain{font-size:18px;line-height:1.65;max-width:720px}
.topics{list-style:none;padding:0;margin:0;display:grid;gap:10px}
.topics li{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 16px}
.topics strong{display:block}
.topics span{color:var(--soft);font-size:15px}
.dna{list-style:none;padding:0;margin:0;display:grid;gap:8px}
.dna li{overflow-wrap:anywhere;padding:10px 14px;background:#fff;border:1px solid var(--line);border-radius:10px;font-size:15px}
.dna b{display:inline-block;min-width:150px;color:var(--plum);font-weight:600}
pre{background:#fff;border:1px solid var(--line);border-radius:var(--r);padding:16px;overflow:auto;
font-size:13px;line-height:1.5;max-height:460px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em}
.copy{float:right;border:1px solid var(--line);background:#fff;border-radius:8px;padding:4px 10px;font:inherit;
font-size:13px;cursor:pointer}
footer{border-top:1px solid var(--line);margin-top:64px;padding:24px 0 40px;font-size:14px;color:var(--soft)}
footer a{color:var(--plum)}
.count{color:var(--soft);font-weight:400}
@media (max-width:860px){.cols{grid-template-columns:minmax(0,1fr)}.side{position:static}}
@media (max-width:560px){.wrap{padding:0 16px}.grid{grid-template-columns:1fr}.search{max-width:none;margin-left:0}
.dna b{display:block;min-width:0}}
"""
CSS = CSS.replace("@@TAG_CSS@@", "".join(
    f".tag.{k}{{background:{v[2]};color:{v[3]}}}" for k, v in REG.items()))

JS = """
document.querySelectorAll('[data-view]').forEach(function(b){b.addEventListener('click',function(){
var root=document.getElementById('lib');root.classList.toggle('view-list',b.dataset.view==='list');
document.querySelectorAll('[data-view]').forEach(function(x){x.setAttribute('aria-pressed',x===b)});});});
var q=document.getElementById('q'),chips=document.querySelectorAll('[data-reg]'),reg='';
function apply(){var t=(q&&q.value||'').toLowerCase().trim(),n=0;
document.querySelectorAll('[data-item]').forEach(function(el){
var ok=(!t||el.dataset.text.indexOf(t)>-1)&&(!reg||(' '+el.dataset.regs+' ').indexOf(' '+reg+' ')>-1);
el.style.display=ok?'':'none';if(ok&&el.classList.contains('card'))n++;});
var e=document.getElementById('empty');if(e)e.style.display=n?'none':'block';}
if(q)q.addEventListener('input',apply);
chips.forEach(function(c){c.addEventListener('click',function(){reg=reg===c.dataset.reg?'':c.dataset.reg;
chips.forEach(function(x){x.setAttribute('aria-pressed',x.dataset.reg===reg)});apply();});});
var cp=document.querySelector('.copy');if(cp)cp.addEventListener('click',function(){
navigator.clipboard.writeText(document.getElementById('json').innerText);cp.textContent='Copied';});
"""


def page(title: str, desc: str, body: str, prefix: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">
<style>{CSS}</style></head>
<body>
<header class="top"><div class="wrap">
<a class="brand" href="{prefix}index.html">Phoebe's <span>Style Vault</span></a>
<a class="toplink" href="{GALLERY_URL}">See the finished works</a>
</div></header>
<main class="wrap">
{body}
</main>
<footer><div class="wrap">A visual style library by Phoebe Fu. Each style is a recipe: what must stay, what may change,
and the topics it explains best. Finished pieces live in the
<a href="{GALLERY_URL}">Worth a Thousand Words gallery</a>.</div></footer>
<script>{JS}</script>
</body></html>
"""


def searchtext(c: dict) -> str:
    bits = [c["id"], c["name"], " ".join(c["register"]), " ".join(c["category"]),
            " ".join(c["format"]), c["plain"], " ".join(t for t, _ in c["topics"])]
    return esc(" ".join(bits).lower())


def style_card(c: dict, prefix: str) -> str:
    regs = "".join(f'<span class="tag {r}">{REG[r][0]}</span>' for r in c["register"])
    own = " - own work" if c["works"] else ""
    return (f'<a class="card" data-item data-regs="{" ".join(c["register"])}" data-text="{searchtext(c)}" '
            f'href="{prefix}s/{c["slug"]}.html"><div class="pic">{thumb(c, prefix)}</div>'
            f'<div class="meta"><p class="name">{esc(c["name"])}</p>'
            f'<p class="sub">{esc(c["id"])} - {esc(", ".join(c["format"][:3]))}{own}</p>'
            f'<div style="margin-top:8px">{regs}</div></div></a>')


def style_rows(cards: list[dict], prefix: str) -> str:
    rows = "".join(
        f'<tr data-item data-regs="{" ".join(c["register"])}" data-text="{searchtext(c)}">'
        f'<td><a href="{prefix}s/{c["slug"]}.html">{esc(c["name"])}</a><br>'
        f'<span class="count">{esc(c["id"])}</span></td>'
        f'<td>{esc(", ".join(REG[r][0] for r in c["register"]))}</td>'
        f'<td>{esc(", ".join(cat_label(x) for x in c["category"]))}</td>'
        f'<td>{esc(", ".join(c["format"]))}</td>'
        f'<td>{"yes" if c["works"] else "pending"}</td></tr>' for c in cards)
    return ('<div class="list"><div class="list-wrap"><table><thead><tr><th>Style</th><th>Audience</th>'
            '<th>Category</th><th>Formats</th><th>Own work</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></div>')


def toolbar(with_chips: bool, placeholder: str) -> str:
    chips = ""
    if with_chips:
        chips = '<div class="chips">' + "".join(
            f'<button class="chip" data-reg="{k}" aria-pressed="false">{v[0]}</button>'
            for k, v in REG.items()) + "</div>"
    return (f'<div class="bar"><div class="tabs"><button data-view="grid" aria-pressed="true">Gallery</button>'
            f'<button data-view="list" aria-pressed="false">List</button></div>{chips}'
            f'<input id="q" class="search" type="search" placeholder="{esc(placeholder)}" '
            f'aria-label="Search"></div>')


# ------------------------------------------------------------------ pages


def groups(cards: list[dict]) -> list[dict]:
    out = []
    for k, (label, blurb, *_r) in REG.items():
        out.append({"kind": "audience", "key": k, "label": label, "blurb": blurb,
                    "slug": f"audience-{k}", "cards": [c for c in cards if k in c["register"]]})
    cats = {}
    for c in cards:
        for x in c["category"]:
            cats.setdefault(x, []).append(c)
    known = list(styles.categories().keys())
    order = sorted(cats, key=lambda x: (known.index(x) if x in known else 99, x))
    for x in order:
        blurb = styles.categories().get(x, {}).get("blurb", "")
        out.append({"kind": "category", "key": x, "label": cat_label(x), "blurb": blurb,
                    "slug": f"category-{slug(x)}", "cards": cats[x]})
    return out


def collage(g: dict) -> str:
    picks = sorted(g["cards"], key=lambda c: (not c["works"], c["id"]))[:4]
    cells = "".join(f"<div>{thumb(c, '')}</div>" for c in picks)
    cells += "<div></div>" * (4 - len(picks))
    return f'<div class="pic collage">{cells}</div>'


def home(cards: list[dict], gs: list[dict]) -> str:
    def tile(g):
        text = esc(f'{g["label"]} {g["blurb"]} ' + " ".join(c["name"] for c in g["cards"])).lower()
        return (f'<a class="card" data-item data-regs="" data-text="{text}" href="c/{g["slug"]}.html">'
                f'{collage(g)}<div class="meta"><p class="name">{esc(g["label"])} '
                f'<span class="count">{len(g["cards"])}</span></p><p class="sub">{esc(g["blurb"])}</p></div></a>')

    def rows(kind):
        return "".join(
            f'<tr data-item data-regs="" data-text="{esc(g["label"].lower())}"><td><a href="c/{g["slug"]}.html">'
            f'{esc(g["label"])}</a></td><td>{len(g["cards"])}</td><td>{esc(g["blurb"])}</td></tr>'
            for g in gs if g["kind"] == kind)

    def block(kind, title, lede):
        tiles = "".join(tile(g) for g in gs if g["kind"] == kind)
        return (f'<h2>{title}</h2><p class="lede">{lede}</p><div class="grid">{tiles}</div>'
                f'<div class="list"><div class="list-wrap"><table><thead><tr><th>Group</th><th>Styles</th>'
                f'<th>What it is</th></tr></thead><tbody>{rows(kind)}</tbody></table></div></div>')

    own = sum(1 for c in cards if c["works"])
    body = (f'<h1>Style Vault</h1><p class="lede">{len(cards)} visual styles, each a recipe for explaining an '
            f'idea. Start from who you are talking to, or from the kind of picture you need. '
            f'Every style here has a finished example of my own; new styles appear once theirs is made.</p>'
            f'<div id="lib">{toolbar(False, "Search styles, topics, formats")}'
            + block("audience", "By audience", "Where the picture will be seen decides how it should look.")
            + block("category", "By category", "The kind of picture: chart, illustration, comic, poster and more.")
            + '<p id="empty" class="empty">Nothing matches that search.</p></div>')
    return page("Style Vault - Phoebe Fu", "A library of visual styles grouped by audience and category.",
                body, "")


def group_page(g: dict) -> str:
    cards = g["cards"]
    kind = "Audience" if g["kind"] == "audience" else "Category"
    body = (f'<p class="crumb"><a href="../index.html">Style Vault</a> / {kind} / {esc(g["label"])}</p>'
            f'<h1>{esc(g["label"])} <span class="count">{len(cards)}</span></h1><p class="lede">{esc(g["blurb"])}</p>'
            f'<div id="lib">{toolbar(g["kind"] == "category", "Search in " + g["label"])}'
            f'<div class="grid">{"".join(style_card(c, "../") for c in cards)}</div>'
            f'{style_rows(cards, "../")}<p id="empty" class="empty">No style matches.</p></div>')
    return page(f"{g['label']} - Style Vault", g["blurb"], body, "../")


def style_json(c: dict) -> str:
    d = {
        "id": c["id"], "name": c["name"], "audience": c["register"], "category": c["category"],
        "format": c["format"], "maker": c["maker"], "keep_and_swap": c["axis"],
    }
    if c["dna"]:
        d["style_dna"] = c["dna"]
    if c["elements"]:
        d["elements"] = c["elements"]
    if c["palette"]:
        d["palette_hex"] = c["palette"]
    if c["topics"]:
        d["topics"] = [{"topic": t, "why": w} for t, w in c["topics"]]
    return json.dumps(d, indent=2, ensure_ascii=False)


def style_page(c: dict, gs: list[dict]) -> str:
    if c["works"]:
        w = c["works"][0]
        art = (f'<div class="hero"><img src="../assets/works/{w["folder"]}.jpg" alt="{esc(w["title"])}"></div>'
               + (f'<p class="cap">Example: {esc(w["title"])}</p>' if w.get("src") else
               f'<p class="cap">My own work in this style: <a href="{GALLERY_URL}">{esc(w["title"])}</a></p>'))
        for extra in c["works"][1:]:
            art += (f'<div class="hero"><img loading="lazy" src="../assets/works/{extra["folder"]}.jpg" '
                    f'alt="{esc(extra["title"])}"></div><p class="cap">{esc(extra["title"])}</p>')
    else:
        art = (f'<div class="hero">{plate(c, big=True)}</div>'
               '<p class="cap">No finished piece in this style yet'
               + (' - the bands are its palette.' if c["palette"] else '.') + '</p>')
    plain = f'<p class="plain">{inline(c["plain"])}</p>' if c["plain"] else ""
    topics = ""
    if c["topics"]:
        topics = '<h2>Topics it fits</h2><ul class="topics">' + "".join(
            f"<li><strong>{inline(t)}</strong><span>{inline(w)}</span></li>" for t, w in c["topics"]) + "</ul>"
    look = c["dna"] or {k.capitalize(): v for k, v in c["elements"].items()}
    analysis = ""
    if look:
        analysis = ('<h2>Art style and layout</h2><ul class="dna">' + "".join(
            f"<li><b>{esc(k.replace('_', ' '))}</b> {inline(v)}</li>" for k, v in look.items()) + "</ul>")
    keep = f'<h3>What must stay, what may change</h3><p>{inline(c["axis"])}</p>' if c["axis"] else ""
    regs = "".join(f'<span class="tag {r}">{REG[r][0]}</span>' for r in c["register"])
    cats = "".join(
        f'<a class="tag" href="category-{slug(x)}.html">{esc(cat_label(x))}</a>'.replace(
            'href="', 'href="../c/') for x in c["category"])
    sw = ""
    if c["palette"]:
        sw = '<dt>Palette</dt><dd><div class="sw">' + "".join(
            f'<span title="{h}" style="background:{h}"></span>' for h in c["palette"]) + "</div></dd>"
    filed = f"<dt>First tried</dt><dd>{esc(c['filed'])}</dd>" if c["filed"] else ""
    side = (f'<aside class="side"><dl><dt>Audience</dt><dd>{regs}</dd><dt>Category</dt><dd>{cats}</dd>'
            f'<dt>Good as</dt><dd>{esc(", ".join(c["format"]))}</dd>'
            f'<dt>How it is made</dt><dd>{esc(c["maker"])}</dd>{filed}{sw}</dl></aside>')
    first = c["register"][0]
    body = (f'<p class="crumb"><a href="../index.html">Style Vault</a> / '
            f'<a href="../c/audience-{first}.html">{REG[first][0]}</a> / {esc(c["name"])}</p>'
            f'<h1>{esc(c["name"])}</h1><p class="lede">{esc(c["id"])}</p>'
            f'<div class="cols"><div>{art}<h2>In plain words</h2>{plain or "<p>Description coming.</p>"}'
            f'{topics}{analysis}{keep}<h2>As JSON</h2><p class="lede">Paste this into a prompt or a skill to '
            f'reuse the style.</p><button class="copy">Copy</button><pre><code id="json">{esc(style_json(c))}'
            f'</code></pre></div>{side}</div>')
    return page(f"{c['name']} - Style Vault", c["plain"][:160] or c["name"], body, "../")


# ------------------------------------------------------------------ main


def main() -> int:
    cards = load()
    gs = groups(cards)
    pages = {"index.html": home(cards, gs)}
    for g in gs:
        pages[f"c/{g['slug']}.html"] = group_page(g)
    for c in cards:
        pages[f"s/{c['slug']}.html"] = style_page(c, gs)
    bad = [(p, m.group(0)) for p, t in pages.items() for m in [BANNED.search(t)] if m]
    if "--check" in sys.argv:
        for p, w in bad:
            print(f"TEXT RULE: {p} contains {w!r}")
        return 1 if bad else 0
    if bad:
        print("refusing to write, text rules broken:", bad[:5])
        return 1
    for d in ("c", "s"):
        shutil.rmtree(ROOT / d, ignore_errors=True)
    prep_images(cards)
    for rel, text in pages.items():
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (ROOT / ".nojekyll").write_text("")
    print(f"built {len(pages)} pages - {len(cards)} styles, {len(gs)} groups, "
          f"{sum(1 for c in cards if c['works'])} with own work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
