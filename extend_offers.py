#!/usr/bin/env python3
"""Extend-your-stay nudges.

Run once a day (afternoon). For every booking that checks in today, lasts
1-5 nights, and has at least one open night right after checkout, text the
owner a ready-to-copy message inviting the guest to stay longer at a discount.

The owner sends it in Airbnb/VRBO; nothing goes to the guest automatically.
Each booking is offered once (UIDs are kept in clients/<name>/offers_sent.txt).

Usage:
    python3 extend_offers.py            # all clients, real texts
    python3 extend_offers.py --dry-run  # print, send nothing, save nothing
"""
import argparse
import datetime
import glob
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crewsync import (HERE, ConfigError, load_config, read_snapshot, is_host_block,  # noqa: E402
                      guest_label, fmt_dated, send_sms, get_auth_token)

DEFAULTS = {"enabled": True, "min_nights": 1, "max_nights": 5, "lookahead_nights": 7}


def find_opportunities(records, today, opts):
    """Bookings checking in today, min..max nights long, with open nights after checkout."""
    out = []
    for r in records:
        if is_host_block(r) or r["dtstart"] != today:
            continue
        nights = (r["dtend"] - r["dtstart"]).days
        if not (opts["min_nights"] <= nights <= opts["max_nights"]):
            continue
        # Anything (booking or host block) occupying the nights after checkout?
        later = [o["dtstart"] for o in records if o is not r and o["dtend"] > r["dtend"]]
        next_start = min([s for s in later if s >= r["dtend"]], default=None)
        overlapping = any(o["dtstart"] <= r["dtend"] < o["dtend"] for o in records if o is not r)
        if overlapping:
            continue
        free = (next_start - r["dtend"]).days if next_start else None
        if free is not None and free < 1:
            continue
        out.append((r, nights, free))
    return out


def guest_first_name(r):
    label = guest_label(r)
    return "" if label in ("Reserved", "Host block") else label.split()[0]


def guest_message(cfg, r, today, free=None):
    name = guest_first_name(r)
    owner = cfg.get("owner_first_name") or ""
    return (f"Hi{(' ' + name) if name else ' there'}! Hope you're settling in and enjoying the cabin :) "
            f"Just a heads up, the cabin is open after your checkout on {fmt_dated(r['dtend'], today)}, "
            f"so if you'd like to stay {'an extra night' if free == 1 else 'an extra night or two'}, I'd be happy to give you a great discounted rate. "
            f"Just let me know!" + (f" - {owner}" if owner else ""))


def owner_text(cfg, r, nights, free, today, lookahead):
    source = "VRBO" if r["source"] == "VRBO" else "Airbnb"
    who = guest_first_name(r) or f"Today's {source} guest"
    if free is None or free >= lookahead:
        open_for = f"open {lookahead}+ nights after"
    else:
        open_for = f"open {free} night{'s' if free != 1 else ''} after (next guest {fmt_dated(r['dtend'] + datetime.timedelta(days=free), today)})"
    return (f"{cfg['client_name']}: extend-stay chance. {who} ({source}, {nights} night"
            f"{'s' if nights != 1 else ''}) checks out {fmt_dated(r['dtend'], today)} and the cabin is "
            f"{open_for}. Copy and send in {source}:\n\n" + guest_message(cfg, r, today, free))


def run_client(cfg_path, dry_run):
    cfg = load_config(cfg_path)
    opts = {**DEFAULTS, **cfg.get("extension_offers", {})}
    if not opts["enabled"]:
        return 0
    today = datetime.datetime.now(ZoneInfo(cfg.get("timezone", "America/New_York"))).date()
    client_dir = os.path.dirname(os.path.abspath(cfg_path))
    records = read_snapshot(os.path.join(client_dir, "snapshot.txt"))
    sent_path = os.path.join(client_dir, "offers_sent.txt")
    sent = set(open(sent_path).read().split()) if os.path.exists(sent_path) else set()

    rc = 0
    for r, nights, free in find_opportunities(records, today, opts):
        if r["uid"] in sent:
            continue
        body = owner_text(cfg, r, nights, free, today, opts["lookahead_nights"])
        sid, _ = send_sms(cfg, cfg["owner_number"], body, dry_run)
        if not sid:
            rc = 1
            continue
        print(f"Offer texted for {r['uid']} ({fmt_dated(r['dtstart'], today)}-{fmt_dated(r['dtend'], today)})")
        if not dry_run:
            sent.add(r["uid"])
            with open(sent_path, "a") as f:
                f.write(r["uid"] + "\n")
    return rc


def main():
    ap = argparse.ArgumentParser(description="Text the owner extend-your-stay opportunities")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rc = 0
    for cfg_path in sorted(glob.glob(os.path.join(HERE, "clients", "*", "config.json"))):
        print(f"===== {os.path.basename(os.path.dirname(cfg_path))} =====")
        try:
            if not args.dry_run and not get_auth_token({}):
                raise ConfigError("TWILIO_AUTH_TOKEN is not set")
            rc = run_client(cfg_path, args.dry_run) or rc
        except ConfigError as e:
            print(f"FATAL: {e}", file=sys.stderr)
            rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
