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
    --bg: #FFFFFF; --ink: #1B1F2E; --muted: #6B7080; --line: #9EA3AE; --soft: #E6E8EC;
    --link: #1668E3; --amber: #E8883A;
    --vrbo: #191E3B; --vrbo-ink: #FFFFFF;
    --airbnb: #DCDDE3; --airbnb-ink: #1B1F2E; --airbnb-edge: #8A8F9C;
    --block: #F1F2F4; --block-edge: #B4B8C2;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #15171C; --ink: #ECEDF0; --muted: #A2A6B0; --line: #4A4E58; --soft: #262932;
      --link: #6FA4F5;
      --vrbo: #E4E6EE; --vrbo-ink: #15171C;
      --airbnb: #3A3E4A; --airbnb-ink: #ECEDF0; --airbnb-edge: #6A6F7C;
      --block: #23262E; --block-edge: #555A66;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    -webkit-text-size-adjust: 100%;
  }
  main { max-width: 1120px; margin: 0 auto; padding: 18px 16px 48px; }
  .prop { font-weight: 700; font-size: 1.05rem; }
  .sub { color: var(--muted); font-size: .85rem; margin-top: 2px; }
  .note { font-size: .9rem; margin: 12px 0 16px; padding: 10px 12px; border-radius: 8px; background: var(--soft); }

  .bar-top { display: flex; align-items: center; gap: 10px 14px; flex-wrap: wrap; margin-bottom: 14px; }
  .bar-top h1 { font-size: 1.35rem; margin: 0 6px 0 0; font-weight: 600; }
  .today-btn {
    border: 1px solid var(--link); color: var(--link); background: none; border-radius: 999px;
    padding: 5px 14px; font-size: .8rem; cursor: pointer;
  }
  .nav { display: flex; align-items: center; gap: 4px; }
  .nav button {
    background: none; border: 0; color: var(--ink); font-size: 1.5rem; line-height: 1;
    width: 36px; height: 36px; cursor: pointer; border-radius: 50%;
  }
  .nav button:hover { background: var(--soft); }
  .nav .label { font-size: 1.3rem; font-weight: 500; min-width: 9.5em; text-align: center; }

  .dows { display: grid; grid-template-columns: repeat(7, 1fr); }
  .dows div { text-align: center; font-size: .78rem; font-weight: 600; padding: 0 0 8px; }
  .weeks { border-top: 1px solid var(--line); border-left: 1px solid var(--line); }
  .week { position: relative; display: grid; grid-template-columns: repeat(7, 1fr); }
  .cell {
    border-right: 1px solid var(--line); border-bottom: 1px solid var(--line);
    min-height: 120px; padding: 8px; font-size: .78rem; position: relative;
  }
  .cell.blank { border-right-color: transparent; }
  .week:first-child .cell.blank { border-bottom-color: var(--line); }
  .cell .n { color: var(--muted); }
  .cell.booked .n { text-decoration: line-through; }
  .cell.today .n {
    display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px;
    border-radius: 50%; background: var(--link); color: #fff; text-decoration: none; font-size: .72rem;
  }
  .cell .flip {
    position: absolute; left: 8px; bottom: 8px; background: var(--amber); color: #fff;
    font-size: .64rem; font-weight: 700; border-radius: 4px; padding: 1px 5px; letter-spacing: .02em;
  }
  .pill {
    position: absolute; top: calc(50% - 15px); height: 30px; z-index: 1;
    display: flex; align-items: center; padding: 0 12px; font-size: .86rem;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-radius: 15px;
  }
  .pill span { overflow: hidden; text-overflow: ellipsis; }
  .pill.vrbo { background: var(--vrbo); color: var(--vrbo-ink); }
  .pill.airbnb { background: var(--airbnb); color: var(--airbnb-ink); border: 1px solid var(--airbnb-edge); }
  .pill.block {
    color: var(--muted); border: 1px solid var(--block-edge);
    background: repeating-linear-gradient(135deg, var(--block) 0 6px, var(--bg) 6px 12px);
  }
  .pill.cont-l { border-top-left-radius: 0; border-bottom-left-radius: 0; border-left: 0; }
  .pill.cont-r { border-top-right-radius: 0; border-bottom-right-radius: 0; border-right: 0; }

  .legend { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: .78rem; margin-top: 12px; }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .legend i { display: inline-block; width: 22px; height: 12px; border-radius: 6px; }

  h3 { font-size: 1.05rem; margin: 30px 0 8px; }
  ul.list { list-style: none; margin: 0; padding: 0; max-width: 640px; }
  ul.list li { border-bottom: 1px solid var(--soft); padding: 10px 2px; }
  ul.list .main { font-weight: 600; }
  ul.list .meta { color: var(--muted); font-size: .86rem; margin-top: 2px; }
  ul.list .tag { background: var(--amber); color: #fff; font-size: .7rem; font-weight: 700; border-radius: 4px; padding: 1px 5px; }
  footer { color: var(--muted); font-size: .78rem; margin-top: 28px; }

  @media (max-width: 640px) {
    .cell { min-height: 72px; padding: 4px; font-size: .72rem; }
    .pill { height: 24px; top: calc(50% - 12px); font-size: .7rem; padding: 0 6px; border-radius: 12px; }
    .cell .flip { left: 3px; bottom: 3px; font-size: .58rem; padding: 0 3px; }
    .nav .label { font-size: 1.1rem; min-width: 8.5em; }
    .bar-top h1 { font-size: 1.15rem; }
  }
</style>
</head>
<body>
<main>
  <div class="prop">__TITLE__</div>
  <div class="sub" id="updated"></div>
  <div class="note">If anything changed, <strong>text __OWNER__ to confirm you can cover the cleaning.</strong></div>

  <div class="bar-top">
    <h1>Calendar</h1>
    <button class="today-btn" id="today">Today</button>
    <div class="nav">
      <button id="prev" aria-label="Previous month">&#8249;</button>
      <span class="label" id="month"></span>
      <button id="next" aria-label="Next month">&#8250;</button>
    </div>
  </div>

  <div class="dows"><div>Sun</div><div>Mon</div><div>Tue</div><div>Wed</div><div>Thu</div><div>Fri</div><div>Sat</div></div>
  <div class="weeks" id="weeks"></div>

  <div class="legend">
    <span><i style="background:var(--vrbo)"></i>VRBO booking</span>
    <span><i style="background:var(--airbnb);border:1px solid var(--airbnb-edge)"></i>Airbnb booking</span>
    <span><i style="border:1px solid var(--block-edge);background:repeating-linear-gradient(135deg,var(--block) 0 4px,var(--bg) 4px 8px)"></i>Host block</span>
    <span><i style="background:var(--amber)"></i>Quick flip (same-day turnover)</span>
  </div>

  <h3>All bookings</h3>
  <ul class="list" id="bookings"></ul>

  <footer>Updated automatically from the Airbnb and VRBO calendars.</footer>
</main>
<script>
const DATA = __DATA__;
const DOW = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
const MON = ["January","February","March","April","May","June","July","August","September","October","November","December"];
const DAY = 86400000;

const parse = s => { const [y,m,d] = s.split("-").map(Number); return new Date(y, m-1, d); };
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate()+n);
const diff = (a, b) => Math.round((b - a) / DAY);
const now = new Date(); const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
const fmt = d => DOW[d.getDay()]+" "+(d.getMonth()+1)+"/"+d.getDate()+(d.getFullYear()!==today.getFullYear() ? "/"+String(d.getFullYear()).slice(2) : "");
const esc = s => s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

const bookings = DATA.bookings.map(b => ({...b, s: parse(b.start), e: parse(b.end)})).filter(b => b.e >= today);
const real = bookings.filter(b => !b.block);
const kind = b => b.block ? "block" : (b.source === "VRBO" ? "vrbo" : "airbnb");
const name = b => b.block ? "Host block" : (b.label === "Reserved" ? (b.source === "VRBO" ? "VRBO guest" : "Airbnb guest") : b.label);
const sameDay = (a, b) => +a === +b;
const isFlip = d => real.some(b => sameDay(b.e, d)) && real.some(b => sameDay(b.s, d));
const bookedNight = d => bookings.some(b => b.s <= d && d < b.e);

if (DATA.updated) document.getElementById("updated").textContent = "Schedule last changed " + fmt(parse(DATA.updated));

let view = new Date(today.getFullYear(), today.getMonth(), 1);
function render() {
  document.getElementById("month").textContent = MON[view.getMonth()] + " " + view.getFullYear();
  const weeks = document.getElementById("weeks");
  weeks.innerHTML = "";
  const first = view;
  const last = new Date(view.getFullYear(), view.getMonth()+1, 0);
  let rowStart = addDays(first, -first.getDay());
  while (rowStart <= last) {
    const row = document.createElement("div");
    row.className = "week";
    for (let i = 0; i < 7; i++) {
      const d = addDays(rowStart, i);
      const cell = document.createElement("div");
      if (d.getMonth() !== view.getMonth()) { cell.className = "cell blank"; row.appendChild(cell); continue; }
      cell.className = "cell" + (bookedNight(d) ? " booked" : "") + (sameDay(d, today) ? " today" : "");
      cell.innerHTML = '<span class="n">' + d.getDate() + '</span>' + (isFlip(d) ? '<span class="flip">FLIP</span>' : "");
      row.appendChild(cell);
    }
    // Bars run from mid-day of check-in to mid-day of checkout, clipped to the month.
    const rowEnd = addDays(rowStart, 7);
    const visFrom = rowStart < first ? first : rowStart;
    const visTo = rowEnd > addDays(last, 1) ? addDays(last, 1) : rowEnd;
    for (const b of bookings) {
      if (b.e < visFrom || b.s >= visTo) continue;
      let start, end, cls = "pill " + kind(b);
      if (b.s >= visFrom) start = diff(rowStart, b.s) + 0.5; else { start = diff(rowStart, visFrom); cls += " cont-l"; }
      if (b.e < visTo) end = diff(rowStart, b.e) + 0.5; else { end = diff(rowStart, visTo); cls += " cont-r"; }
      if (end <= start) continue;
      const p = document.createElement("div");
      p.className = cls;
      p.style.left = (start / 7 * 100) + "%";
      p.style.width = ((end - start) / 7 * 100) + "%";
      p.title = name(b) + ": " + fmt(b.s) + " to " + fmt(b.e);
      p.innerHTML = "<span>" + esc(name(b)) + "</span>";
      row.appendChild(p);
    }
    weeks.appendChild(row);
    rowStart = rowEnd;
  }
}
const go = m => { view = new Date(view.getFullYear(), view.getMonth()+m, 1); render(); };
document.getElementById("prev").onclick = () => go(-1);
document.getElementById("next").onclick = () => go(1);
document.getElementById("today").onclick = () => { view = new Date(today.getFullYear(), today.getMonth(), 1); render(); };
render();

const items = bookings.map(b => {
  const n = diff(b.s, b.e);
  const src = b.block ? "Host block" : (b.source === "VRBO" ? "VRBO" : "Airbnb");
  let meta = b.block ? "Owner/host hold" : src + " \u00b7 " + n + " night" + (n === 1 ? "" : "s");
  if (b.s <= today && today < b.e) meta += " \u00b7 in-house now";
  if (!b.block && real.some(o => o !== b && sameDay(o.s, b.e))) meta += ' <span class="tag">QUICK FLIP</span> on checkout';
  return '<li><div class="main">' + fmt(b.s) + " to " + fmt(b.e) + " \u00b7 " + esc(name(b)) + '</div><div class="meta">' + meta + '</div></li>';
});
document.getElementById("bookings").innerHTML = items.join("") || '<li class="meta">No upcoming bookings.</li>';
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
