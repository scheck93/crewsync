#!/usr/bin/env python3
"""Build the static site published to GitHub Pages.

    _site/index.html          <- website/index.html (landing page)
    _site/<site_slug>/        <- one calendar page per client, built from
                                 that client's snapshot.txt

Only public settings (config.json) and the snapshot are used, so this runs
without any secrets.

Usage:
    python3 build_site.py              # writes ./_site
    python3 build_site.py --out DIR
"""
import argparse
import datetime
import glob
import html
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crewsync import HERE, read_snapshot, is_host_block, guest_label  # noqa: E402


def booking_json(records):
    out = []
    for r in sorted(records, key=lambda r: r["dtstart"]):
        out.append({
            "source": r["source"],
            "start": r["dtstart"].isoformat(),
            "end": r["dtend"].isoformat(),
            "label": guest_label(r),
            "block": is_host_block(r),
        })
    return out


def snapshot_updated(path):
    """The 'Last updated: YYYY-MM-DD' line the engine writes."""
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("# Last updated:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def render_calendar(cfg, records, updated):
    data = json.dumps({
        "bookings": booking_json(records),
        "updated": updated,
    }).replace("</", "<\\/")
    page = TEMPLATE
    page = page.replace("__TITLE__", html.escape(cfg["client_name"]))
    page = page.replace("__OWNER__", html.escape(cfg.get("owner_first_name") or "the owner"))
    page = page.replace("__DATA__", data)
    return page


def build(out_dir):
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    landing = os.path.join(HERE, "website", "index.html")
    if os.path.exists(landing):
        shutil.copy(landing, os.path.join(out_dir, "index.html"))
    # Plain static files: tell Pages not to run Jekyll.
    open(os.path.join(out_dir, ".nojekyll"), "w").close()

    for cfg_path in sorted(glob.glob(os.path.join(HERE, "clients", "*", "config.json"))):
        with open(cfg_path) as f:
            cfg = json.load(f)
        slug = cfg.get("site_slug")
        if not slug:
            continue
        snap = os.path.join(os.path.dirname(cfg_path), "snapshot.txt")
        records = read_snapshot(snap)
        page_dir = os.path.join(out_dir, slug)
        os.makedirs(page_dir, exist_ok=True)
        with open(os.path.join(page_dir, "index.html"), "w") as f:
            f.write(render_calendar(cfg, records, snapshot_updated(snap)))
        print(f"built /{slug}/ ({len(records)} bookings)")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>__TITLE__ Schedule</title>
<style>
  :root {
    --bg: #FAF8F3; --card: #FFFFFF; --ink: #2C2C2C; --muted: #6B6B6B;
    --line: #E5E0D5; --teal: #2D6A5F; --amber: #E8883A;
    --airbnb: #E0565B; --vrbo: #2F6FB5; --block: #B9B4AA;
    --today: #2D6A5F;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #161616; --card: #202020; --ink: #EDEDED; --muted: #A0A0A0;
      --line: #333; --teal: #6FC2B0; --amber: #F0A060;
      --airbnb: #E8676C; --vrbo: #5B93D6; --block: #5E5A54; --today: #6FC2B0;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    -webkit-text-size-adjust: 100%;
  }
  main { max-width: 760px; margin: 0 auto; padding: 20px 16px 48px; }
  h1 { font-size: 1.4rem; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: .9rem; margin: 0 0 16px; }
  .note {
    background: var(--card); border: 1px solid var(--line); border-left: 4px solid var(--amber);
    border-radius: 8px; padding: 10px 12px; font-size: .92rem; margin-bottom: 18px;
  }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: .82rem; color: var(--muted); margin: 0 0 10px; }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .sw { width: 14px; height: 14px; border-radius: 3px; display: inline-block; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 12px; }
  .nav { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  .nav h2 { font-size: 1.05rem; margin: 0; }
  .nav button {
    background: none; border: 1px solid var(--line); color: var(--ink); border-radius: 8px;
    font-size: 1.1rem; width: 40px; height: 36px; cursor: pointer;
  }
  .grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; }
  .dow { text-align: center; font-size: .72rem; color: var(--muted); padding: 2px 0 4px; }
  .day {
    position: relative; min-height: 58px; border-radius: 6px; padding: 3px 4px;
    font-size: .78rem; background: var(--bg); overflow: hidden;
  }
  .day.out { visibility: hidden; }
  .day.past { opacity: .45; }
  .day .n { font-weight: 600; position: relative; z-index: 1; }
  .day.today { outline: 2px solid var(--today); outline-offset: -2px; }
  .day .tag {
    position: absolute; right: 4px; bottom: 3px; z-index: 1;
    font-size: .64rem; font-weight: 700; line-height: 1.15;
  }
  /* Split cells: top-left half = last night's guest, bottom-right = tonight's. */
  .day.am .n, .day.pm .tag { color: #fff; text-shadow: 0 0 2px rgba(0,0,0,.35); }
  .flip { background: var(--amber); color: #fff; border-radius: 3px; padding: 0 3px; text-shadow: none; }
  h3 { font-size: 1.05rem; margin: 26px 0 8px; }
  ul.list { list-style: none; margin: 0; padding: 0; }
  ul.list li {
    background: var(--card); border: 1px solid var(--line); border-radius: 10px;
    padding: 10px 12px; margin-bottom: 8px; display: flex; gap: 10px; align-items: flex-start;
  }
  ul.list .bar { width: 5px; align-self: stretch; border-radius: 3px; flex: none; }
  ul.list .main { font-weight: 600; }
  ul.list .meta { color: var(--muted); font-size: .85rem; margin-top: 2px; }
  .empty { color: var(--muted); font-size: .9rem; }
  footer { color: var(--muted); font-size: .8rem; margin-top: 28px; }
</style>
</head>
<body>
<main>
  <h1>__TITLE__</h1>
  <p class="sub" id="updated"></p>
  <div class="note">Check the cleanings below. If anything changed, <strong>text __OWNER__ to confirm you can cover it.</strong></div>

  <div class="legend">
    <span><i class="sw" style="background:var(--airbnb)"></i>Airbnb</span>
    <span><i class="sw" style="background:var(--vrbo)"></i>VRBO</span>
    <span><i class="sw" style="background:var(--block)"></i>Host block</span>
    <span><i class="sw" style="background:var(--amber)"></i>Quick flip (same-day turnover)</span>
  </div>

  <div class="card">
    <div class="nav">
      <button id="prev" aria-label="Previous month">&#8249;</button>
      <h2 id="month"></h2>
      <button id="next" aria-label="Next month">&#8250;</button>
    </div>
    <div class="grid" id="grid"></div>
  </div>

  <h3>Upcoming cleanings</h3>
  <ul class="list" id="cleanings"></ul>

  <h3>All bookings</h3>
  <ul class="list" id="bookings"></ul>

  <footer>Updated automatically from the Airbnb and VRBO calendars.</footer>
</main>
<script>
const DATA = __DATA__;
const DOW = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
const MON = ["January","February","March","April","May","June","July","August","September","October","November","December"];

const parse = s => { const [y,m,d] = s.split("-").map(Number); return new Date(y, m-1, d); };
const key = d => d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate()+n);
const now = new Date(); const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
const fmt = d => DOW[d.getDay()]+" "+(d.getMonth()+1)+"/"+d.getDate()+(d.getFullYear()!==today.getFullYear() ? "/"+String(d.getFullYear()).slice(2) : "");
const nights = (a, b) => Math.round((b - a) / 86400000);

const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const colorOf = b => b.block ? "--block" : (b.source === "VRBO" ? "--vrbo" : "--airbnb");
const name = b => b.block ? "Host block" : (b.label === "Reserved" ? (b.source === "VRBO" ? "VRBO guest" : "Airbnb guest") : b.label + " (" + (b.source === "VRBO" ? "VRBO" : "Airbnb") + ")");

const bookings = DATA.bookings.map(b => ({...b, s: parse(b.start), e: parse(b.end)}))
  .filter(b => b.e >= today);
const real = bookings.filter(b => !b.block);

// Night of date d belongs to the booking with start <= d < end.
const nightOwner = d => bookings.find(b => b.s <= d && d < b.e);
const checkouts = new Map(real.map(b => [key(b.e), b]));
const checkins = new Map(real.map(b => [key(b.s), b]));
const isFlip = d => checkouts.has(key(d)) && checkins.has(key(d));

if (DATA.updated) {
  document.getElementById("updated").textContent = "Schedule last changed " + fmt(parse(DATA.updated));
}

let view = new Date(today.getFullYear(), today.getMonth(), 1);
function renderMonth() {
  document.getElementById("month").textContent = MON[view.getMonth()] + " " + view.getFullYear();
  const grid = document.getElementById("grid");
  grid.innerHTML = DOW.map(d => '<div class="dow">'+d.slice(0,2)+'</div>').join("");
  const first = view.getDay();
  for (let i = 0; i < first; i++) grid.insertAdjacentHTML("beforeend", '<div class="day out"></div>');
  const days = new Date(view.getFullYear(), view.getMonth()+1, 0).getDate();
  for (let n = 1; n <= days; n++) {
    const d = new Date(view.getFullYear(), view.getMonth(), n);
    const am = nightOwner(addDays(d, -1));   // guest who slept here last night
    const pm = nightOwner(d);                // guest who sleeps here tonight
    const cell = document.createElement("div");
    cell.className = "day" + (d < today ? " past" : "") + (+d === +today ? " today" : "");
    const a = am ? css(colorOf(am)) : null, p = pm ? css(colorOf(pm)) : null;
    if (a && p && am !== pm) cell.style.background = `linear-gradient(135deg, ${a} 50%, ${p} 50%)`;
    else if (p) cell.style.background = am === pm ? p : `linear-gradient(135deg, transparent 50%, ${p} 50%)`;
    else if (a) cell.style.background = `linear-gradient(135deg, ${a} 50%, transparent 50%)`;
    if (a) cell.classList.add("am");
    if (p) cell.classList.add("pm");
    let tag = "";
    if (isFlip(d)) tag = '<span class="flip">FLIP</span>';
    else if (checkouts.has(key(d))) tag = "Out";
    else if (checkins.has(key(d))) tag = "In";
    cell.innerHTML = '<span class="n">'+n+'</span>' + (tag ? '<span class="tag">'+tag+'</span>' : "");
    cell.title = [am && am !== pm ? name(am)+" checks out" : "", pm ? (am === pm ? name(pm) : name(pm)+" checks in") : ""].filter(Boolean).join(" / ");
    grid.appendChild(cell);
  }
}
document.getElementById("prev").onclick = () => { view = new Date(view.getFullYear(), view.getMonth()-1, 1); renderMonth(); };
document.getElementById("next").onclick = () => { view = new Date(view.getFullYear(), view.getMonth()+1, 1); renderMonth(); };
renderMonth();

function li(color, main, meta) {
  return '<li><span class="bar" style="background:var('+color+')"></span><div><div class="main">'+main+'</div><div class="meta">'+meta+'</div></div></li>';
}
const esc = s => s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

const cleanList = real.filter(b => b.e >= today).sort((x, y) => x.e - y.e).map(b => {
  const next = real.filter(n => n.s >= b.e).sort((x, y) => x.s - y.s)[0];
  let meta = esc(name(b)) + " checks out.";
  if (next && +next.s === +b.e) meta += ' <span class="flip">QUICK FLIP</span> next guest arrives the same day.';
  else if (next) meta += " Next guest arrives " + fmt(next.s) + ".";
  else meta += " No next booking yet.";
  return li(+b.e === +today ? "--today" : colorOf(b), fmt(b.e) + (+b.e === +today ? " (today)" : ""), meta);
});
document.getElementById("cleanings").innerHTML = cleanList.join("") || '<li class="empty">No upcoming cleanings.</li>';

const bookList = bookings.map(b => {
  const here = b.s <= today && today < b.e;
  const meta = (b.block ? "Owner/host hold" : nights(b.s, b.e) + " night" + (nights(b.s, b.e) === 1 ? "" : "s")) + (here ? " · in-house now" : "");
  return li(colorOf(b), fmt(b.s) + " to " + fmt(b.e) + " · " + esc(name(b)), meta);
});
document.getElementById("bookings").innerHTML = bookList.join("") || '<li class="empty">No upcoming bookings.</li>';
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Build the static site into a folder")
    ap.add_argument("--out", default=os.path.join(HERE, "_site"))
    args = ap.parse_args()
    build(args.out)


if __name__ == "__main__":
    main()
