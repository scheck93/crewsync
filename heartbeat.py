#!/usr/bin/env python3
"""Weekly "still running" text to the owner(s).

Counts the CrewSync workflow's scheduled runs over the last N days (GitHub
API) and texts a short health report. If the weekly text stops arriving,
something is wrong (workflow disabled, secrets removed, Twilio broken).

Runs inside GitHub Actions; needs GITHUB_TOKEN, GITHUB_REPOSITORY and the
usual CREWSYNC_PRIVATE / TWILIO_AUTH_TOKEN.

Usage:
    python3 heartbeat.py [--days 7] [--dry-run]
"""
import argparse
import datetime
import glob
import json
import os
import sys
import urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crewsync import HERE, load_config, send_sms, confirmation_recipients  # noqa: E402

WORKFLOW = "crewsync.yml"
CHECKS_PER_DAY = 48  # every 30 minutes


def gh_get(path):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{path}",
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def scheduled_runs(since):
    """Automatic calendar checks: GitHub's own schedule, or the Apps Script
    timer that starts the workflow (shows up as workflow_dispatch)."""
    runs, page = [], 1
    while True:
        data = gh_get(f"/actions/workflows/{WORKFLOW}/runs"
                      f"?created=%3E%3D{since:%Y-%m-%dT%H:%M:%SZ}&per_page=100&page={page}")
        batch = data.get("workflow_runs", [])
        runs += [r for r in batch if r.get("event") in ("schedule", "workflow_dispatch")]
        if len(batch) < 100:
            return runs
        page += 1


def build_report(runs, days, tz):
    done = [r for r in runs if r.get("status") == "completed"]
    failed = [r for r in done if r.get("conclusion") not in ("success", "skipped")]
    expected = CHECKS_PER_DAY * days
    if not done:
        return (f"CrewSync WARNING: no automatic calendar checks ran in the last {days} days. "
                f"The crew is NOT getting schedule updates. Check the Actions tab on GitHub.")
    last = max(datetime.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) for r in done)
    last_local = last.astimezone(tz).strftime("%a %-m/%-d %-I:%M %p")
    msg = (f"CrewSync weekly check: running normally. {len(done)} calendar checks in the last "
           f"{days} days, {len(failed)} failed. Last check {last_local}.")
    if failed:
        msg = msg.replace("running normally", "needs a look")
        msg += " GitHub emailed you about each failure; see the Actions tab."
    elif len(done) < expected * 0.5:
        msg += (f" (Fewer than the ~{expected} expected; GitHub sometimes skips runs when busy, "
                f"but keep an eye on it.)")
    return msg


def main():
    ap = argparse.ArgumentParser(description="Text the owner a weekly CrewSync health report")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    configs = sorted(glob.glob(os.path.join(HERE, "clients", "*", "config.json")))
    cfgs = [load_config(p) for p in configs]
    tz = ZoneInfo(cfgs[0].get("timezone", "America/New_York")) if cfgs else datetime.timezone.utc

    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=args.days)
    report = build_report(scheduled_runs(since), args.days, tz)

    # One text per distinct owner/operator number across clients.
    sent, failed = set(), 0
    for cfg in cfgs:
        for to in confirmation_recipients(cfg):
            if to in sent:
                continue
            sent.add(to)
            sid, _ = send_sms(cfg, to, report, dry_run=args.dry_run)
            failed += sid is None
    print(report)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
