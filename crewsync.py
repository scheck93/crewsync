#!/usr/bin/env python3
"""
CrewSync — short-term rental schedule sync + SMS notifier.

Polls one client's iCal feeds (Airbnb / VRBO), diffs against a saved
snapshot, and texts the crew via Twilio when bookings change. Stays
silent on quiet runs.

Usage:
    python3 crewsync.py clients/david-cozy-cabin/config.json
    python3 crewsync.py clients/david-cozy-cabin/config.json --dry-run

Private settings:
    config.json holds only public settings and is safe to commit. Phone
    numbers, feed URLs and the Twilio account live in a private JSON blob
    keyed by client folder name, read from the CREWSYNC_PRIVATE environment
    variable (GitHub Actions secret) or, locally, from private.json at the
    project root (gitignored). See private.example.json.

    The Twilio auth token is read from the TWILIO_AUTH_TOKEN environment
    variable.

Exit codes:
    0  success (whether or not changes were found)
    1  fatal error (feed fetch failed, config missing/invalid, etc.)

No third-party dependencies — Python 3.9+ standard library only
(zoneinfo requires 3.9+; on 3.9/3.10 you may need `pip install tzdata`
on minimal systems).
"""

import sys
import os
import json
import re
import math
import ssl
import argparse
import datetime
import base64
import urllib.request
import urllib.parse
import urllib.error
from zoneinfo import ZoneInfo

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ----------------------------------------------------------------------
# Config loading (public config.json + private settings)
# ----------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
PRIVATE_KEYS = ("feeds", "twilio", "owner_number", "operator_number",
                "notification_recipients")


class ConfigError(Exception):
    pass


def load_private():
    raw = os.environ.get("CREWSYNC_PRIVATE")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ConfigError(f"CREWSYNC_PRIVATE is not valid JSON: {e}") from e
    path = os.path.join(HERE, "private.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def client_key(config_path):
    return os.path.basename(os.path.dirname(os.path.abspath(config_path)))


def load_config(config_path, require_private=True):
    """Public config.json merged with this client's private settings."""
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"cannot read config {config_path}: {e}") from e
    key = client_key(config_path)
    priv = load_private().get(key, {})
    cfg.update(priv)
    if require_private:
        missing = [k for k in PRIVATE_KEYS if k not in cfg and k != "operator_number"]
        if missing:
            raise ConfigError(
                f"private settings for '{key}' missing {missing} — set "
                f"CREWSYNC_PRIVATE or create private.json (see private.example.json)")
    return cfg


# ----------------------------------------------------------------------
# iCal fetch + parse
# ----------------------------------------------------------------------

class FeedError(Exception):
    """Raised when a feed can't be fetched or isn't valid iCal (usually a
    rotated calendar token serving an HTML error page)."""


# Browser User-Agent — Airbnb/VRBO behind Akamai may reject non-browser agents.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0.0.0 Safari/537.36")


def fetch(url, timeout=30):
    """Real HTTP GET of an iCal feed. NOT an LLM/summarizing fetch — returns
    the raw bytes. Raises FeedError on HTTP/network failure or if the body
    isn't iCal (the tell-tale sign of a rotated token)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": BROWSER_UA,
        "Accept": "text/calendar, */*;q=0.5",
        "Accept-Language": "en-US,en;q=0.9",
    })
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            ctype = r.headers.get("Content-Type", "")
            body = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise FeedError(
            f"HTTP {e.code} from feed — calendar token has most likely been "
            f"ROTATED. Regenerate the export link in the host dashboard. URL: {url}"
        ) from e
    except urllib.error.URLError as e:
        raise FeedError(f"network error reaching feed: {e.reason}") from e
    if "BEGIN:VCALENDAR" not in body:
        raise FeedError(
            f"response is not iCal (Content-Type={ctype!r}); first 200 bytes: "
            f"{body[:200]!r} — treat as a rotated/invalid token."
        )
    return body


def _unfold(text):
    """iCal line folding: continuation lines start with a space or tab."""
    lines = []
    for line in text.splitlines():
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _parse_date(val):
    """Handle DTSTART/DTEND as VALUE=DATE (YYYYMMDD) or DATE-TIME (YYYYMMDDThhmmssZ)."""
    m = re.match(r"(\d{4})(\d{2})(\d{2})", val)
    if not m:
        return None
    return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def parse_ical(text, source):
    """Parse VEVENT blocks into records. `source` is e.g. 'VRBO' or 'AIRBNB'."""
    events, cur = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {"source": source}
        elif line == "END:VEVENT":
            if cur and cur.get("uid") and cur.get("dtstart") and cur.get("dtend"):
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, _, val = line.partition(":")
            key = head.split(";", 1)[0].upper()
            if key == "UID":
                cur["uid"] = val.strip()
            elif key == "DTSTART":
                cur["dtstart"] = _parse_date(val)
            elif key == "DTEND":
                cur["dtend"] = _parse_date(val)
            elif key == "DTSTAMP":
                cur["dtstamp"] = val.strip()
            elif key == "SUMMARY":
                cur["summary"] = val.strip()
    return events


# ----------------------------------------------------------------------
# Filtering
# ----------------------------------------------------------------------

def is_host_block(rec):
    return "Not available" in (rec.get("summary") or "")


def filter_records(records, today, far_future_days):
    """
    (a) drop bookings whose checkout is today or earlier (dtend <= today)
    (b) drop host blocks whose check-in is more than far_future_days out
        (Airbnb's rolling advance-booking-window block).
    """
    cutoff = today + datetime.timedelta(days=far_future_days)
    out = []
    for r in records:
        if not (r.get("dtstart") and r.get("dtend") and r.get("uid")):
            continue
        if r["dtend"] <= today:
            continue
        if is_host_block(r) and r["dtstart"] > cutoff:
            continue
        out.append(r)
    return out


# ----------------------------------------------------------------------
# Snapshot I/O
# ----------------------------------------------------------------------

def snapshot_path_for(config_path):
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), "snapshot.txt")


def read_snapshot(path):
    records = []
    if not os.path.exists(path):
        return records
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("#") or not line.strip():
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 5:
                try:
                    records.append({
                        "source": parts[0],
                        "uid": parts[1],
                        "dtstart": datetime.date.fromisoformat(parts[2]),
                        "dtend": datetime.date.fromisoformat(parts[3]),
                        "summary": parts[4],
                    })
                except ValueError:
                    pass
    return records


def write_snapshot(path, records, client_name, today):
    header = (
        f"# {client_name} — rental schedule snapshot\n"
        f"# Last updated: {today.isoformat()}\n"
        f"# Format: SOURCE | UID | CHECKIN | CHECKOUT | SUMMARY\n"
        f"# Auto-generated by crewsync.py — do not hand-edit unless recovering state\n"
    )
    rows = sorted(records, key=lambda r: r["dtstart"])
    with open(path, "w") as f:
        f.write(header + "\n")
        for r in rows:
            f.write(f"{r['source']:6s} | {r['uid']:55s} | {r['dtstart']} | {r['dtend']} | {r.get('summary','')}\n")


# ----------------------------------------------------------------------
# Diff + flip detection
# ----------------------------------------------------------------------

def compute_diff(snapshot, live):
    sbu = {r["uid"]: r for r in snapshot}
    lbu = {r["uid"]: r for r in live}
    changes = []
    for uid, r in lbu.items():
        if uid not in sbu:
            changes.append({"type": "NEW", "new": r})
        else:
            o = sbu[uid]
            if o["dtstart"] != r["dtstart"] or o["dtend"] != r["dtend"]:
                changes.append({"type": "DATE_CHANGE", "old": o, "new": r})
    for uid, r in sbu.items():
        if uid not in lbu:
            changes.append({"type": "CANCELLED", "old": r})
    return changes


def compute_flip_dates(records):
    """A real same-day turnover: a real reservation checks out AND a
    different real reservation checks in on the same date. Host blocks
    are excluded entirely."""
    checkout_real = {r["dtend"] for r in records if not is_host_block(r)}
    checkin_real = {r["dtstart"] for r in records if not is_host_block(r)}
    return checkout_real & checkin_real


# ----------------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------------

def fmt_date(d, today):
    suffix = f"/{d.year % 100:02d}" if d.year != today.year else ""
    return f"{d.month}/{d.day}{suffix}"


def fmt_dated(d, today):
    return f"{WEEKDAYS[d.weekday()]} {fmt_date(d, today)}"


def guest_label(r):
    summ = r.get("summary") or ""
    if is_host_block(r):
        return "Host block"
    # VRBO summaries look like "Reserved - Name"; Airbnb is just "Reserved".
    if r["source"] == "VRBO" and summ.startswith("Reserved - "):
        return summ.replace("Reserved - ", "").strip() or "Reserved"
    return "Reserved"


def short_change(c, today):
    """Compact one-item description, e.g. 'new booking Wed 12/3 to Sun 12/7'.
    Plain ASCII on purpose: a single non-GSM character (en dash, arrow)
    switches the whole SMS to UCS-2 and halves the characters per segment."""
    def span(r):
        return f"{fmt_dated(r['dtstart'], today)} to {fmt_dated(r['dtend'], today)}"
    if c["type"] == "NEW":
        kind = "new host block" if is_host_block(c["new"]) else "new booking"
        return f"{kind} {span(c['new'])}"
    if c["type"] == "CANCELLED":
        kind = "host block removed" if is_host_block(c["old"]) else "cancelled"
        return f"{kind} {span(c['old'])}"
    return f"dates changed from {span(c['old'])}, now {span(c['new'])}"


def format_update_sms(cfg, live, changes, today, max_items=3):
    """Short crew text: what changed (briefly), the calendar link, and a
    request to confirm coverage. Full details live on the web calendar."""
    ordered = sorted(changes, key=lambda c: (c.get("new") or c["old"])["dtstart"])
    items = [short_change(c, today) for c in ordered[:max_items]]
    if len(ordered) > max_items:
        items.append(f"+{len(ordered) - max_items} more")
    owner = cfg.get("owner_first_name") or "the owner"
    body = f"{cfg['client_name']} schedule changed: " + "; ".join(items) + "."
    if cfg.get("calendar_url"):
        body += f"\n\nSee the updated calendar: {cfg['calendar_url']}"
    body += f"\n\nPlease text {owner} to confirm you can cover the new schedule."
    if cfg.get("signature"):
        body += f"\n{cfg['signature']}"
    return body


def format_confirmation_sms(cfg, changes, recipient_count, now_local):
    new_n = sum(1 for c in changes if c["type"] == "NEW")
    canc_n = sum(1 for c in changes if c["type"] == "CANCELLED")
    chg_n = sum(1 for c in changes if c["type"] == "DATE_CHANGE")
    ts = now_local.strftime("%a %-m/%-d %-I:%M %p")
    return (f"Confirmation: {cfg['client_name']} schedule update SMS sent to "
            f"{recipient_count} recipient(s) at {ts}. {len(changes)} change(s): "
            f"{new_n} new, {canc_n} cancellations, {chg_n} date change.")


# ----------------------------------------------------------------------
# Twilio
# ----------------------------------------------------------------------

def get_auth_token(cfg):
    return os.environ.get("TWILIO_AUTH_TOKEN")


def send_sms(cfg, to, body, dry_run=False):
    if dry_run:
        print(f"\n[DRY-RUN] -> {to}\n{'-'*50}\n{body}\n{'-'*50}")
        return "DRYRUN", "dry-run"
    account_sid = cfg["twilio"]["account_sid"]
    token = get_auth_token(cfg)
    if not token:
        print("  ERROR: no Twilio auth token (set TWILIO_AUTH_TOKEN)", file=sys.stderr)
        return None, "no-token"
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    data = urllib.parse.urlencode({
        "From": cfg["twilio"]["from_number"], "To": to, "Body": body
    }).encode()
    auth = base64.b64encode(f"{account_sid}:{token}".encode()).decode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Authorization": f"Basic {auth}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
            return resp.get("sid"), resp.get("status")
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        print(f"  ERROR sending to {to}: HTTP {e.code} — {err[:300]}", file=sys.stderr)
        return None, f"error-{e.code}"


def confirmation_recipients(cfg):
    recips = [cfg["owner_number"]]
    op = cfg.get("operator_number")
    if op and op != cfg["owner_number"]:
        recips.append(op)
    return recips


# ----------------------------------------------------------------------
# Main run
# ----------------------------------------------------------------------

def run(config_path, dry_run=False, init_snapshot=False):
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    tz = ZoneInfo(cfg.get("timezone", "America/New_York"))
    now_local = datetime.datetime.now(tz)
    today = now_local.date()
    far_days = cfg.get("far_future_block_days", 180)
    snap_path = snapshot_path_for(config_path)

    # 1. Fetch + parse all feeds
    live_raw = []
    for feed in cfg["feeds"]:
        try:
            text = fetch(feed["url"])
        except Exception as e:
            print(f"FATAL: feed fetch failed ({feed['source']}): {e}", file=sys.stderr)
            return 1  # never touch snapshot / send SMS on a fetch failure
        live_raw += parse_ical(text, feed["source"])

    # 2. Filter live feed
    live = filter_records(live_raw, today, far_days)

    # --init-snapshot: write current state and exit (onboarding / re-init)
    if init_snapshot:
        write_snapshot(snap_path, live, cfg["client_name"], today)
        print(f"Snapshot initialized: {len(live)} booking(s) written to {snap_path}")
        return 0

    # 3. Read + filter snapshot (same filters on both sides of the diff)
    snap = filter_records(read_snapshot(snap_path), today, far_days)

    # 4. Diff
    changes = compute_diff(snap, live)

    # 5. Suspicious-diff guard
    cancels = sum(1 for c in changes if c["type"] == "CANCELLED")
    threshold = max(cfg.get("suspicious_cancel_min", 3),
                    math.ceil(cfg.get("suspicious_cancel_pct", 0.30) * len(snap)))
    if cancels > threshold:
        alert = (f"{cfg['client_name']} watchdog: suspicious schedule diff. "
                 f"{cancels} cancellations vs threshold {threshold} on a snapshot "
                 f"of {len(snap)} bookings. Skipping crew SMS — review the feed(s).")
        for to in confirmation_recipients(cfg):
            send_sms(cfg, to, alert, dry_run)
        print(f"Suspicious-diff guard tripped: {cancels} cancellations, "
              f"threshold {threshold}. Owner/operator alerted, snapshot unchanged.")
        return 0

    # 6. No changes -> silent
    if not changes:
        print("No changes.")
        return 0

    # 7. Schedule-update SMS to the crew
    update_body = format_update_sms(cfg, live, changes, today)
    sent = []
    for to in cfg["notification_recipients"]:
        sid, status = send_sms(cfg, to, update_body, dry_run)
        sent.append((to, sid, status))

    # 8-9. Confirmation SMS to owner (+ operator if present)
    conf_recips = confirmation_recipients(cfg)
    conf_body = format_confirmation_sms(cfg, changes, len(cfg["notification_recipients"]), now_local)
    for to in conf_recips:
        send_sms(cfg, to, conf_body, dry_run)

    # 10. Persist new snapshot (only on a real run)
    if not dry_run:
        write_snapshot(snap_path, live, cfg["client_name"], today)

    # 11. Status line
    sids = [s for _, s, _ in sent if s]
    print(f"Sent {len(changes)} change(s) to {len(cfg['notification_recipients'])} recipient(s) "
          f"(+ {len(conf_recips)} confirmation(s)). SIDs: {', '.join(sids)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="CrewSync rental schedule sync + SMS notifier")
    ap.add_argument("config", help="path to a client config.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + print messages, but do not send SMS or write the snapshot")
    ap.add_argument("--init-snapshot", action="store_true",
                    help="fetch feeds and (over)write the snapshot to current state; sends nothing")
    args = ap.parse_args()
    sys.exit(run(args.config, dry_run=args.dry_run, init_snapshot=args.init_snapshot))


if __name__ == "__main__":
    main()
