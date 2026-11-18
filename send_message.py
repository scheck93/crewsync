#!/usr/bin/env python3
"""Send an ad-hoc SMS to a client's people via Twilio.

Use for one-off messages — welcome/intro texts, trial-end reminders,
service announcements — outside the automated schedule-sync flow.

Usage:
    # Send a message to a client's crew + owner + operator:
    python3 send_message.py clients/david-cozy-cabin/config.json --to crew,owner,operator --body "Your message"

    # Read body from a file (handy for long/multiline messages):
    python3 send_message.py clients/david-cozy-cabin/config.json --to owner,operator --body-file intro.txt

    # Dry-run (print, don't send):
    python3 send_message.py clients/david-cozy-cabin/config.json --to crew --body "Hi" --dry-run

--to is a comma-separated list of audiences:
    crew      -> notification_recipients
    owner     -> owner_number
    operator  -> operator_number (if set)
    all       -> crew + owner + operator (de-duplicated)
You can also pass raw E.164 numbers, e.g. --to "+15551234567,owner".
"""
import os
import sys
import argparse

# Reuse the Twilio sender from the engine
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crewsync import send_sms, load_config  # noqa: E402


def resolve_recipients(cfg, spec):
    out = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if token == "crew":
            out += cfg.get("notification_recipients", [])
        elif token == "owner":
            if cfg.get("owner_number"):
                out.append(cfg["owner_number"])
        elif token == "operator":
            if cfg.get("operator_number"):
                out.append(cfg["operator_number"])
        elif token == "all":
            out += cfg.get("notification_recipients", [])
            if cfg.get("owner_number"):
                out.append(cfg["owner_number"])
            if cfg.get("operator_number"):
                out.append(cfg["operator_number"])
        elif token.startswith("+"):
            out.append(token)
        else:
            print(f"  WARNING: unknown audience '{token}', skipping", file=sys.stderr)
    # de-dupe, preserve order
    seen, deduped = set(), []
    for n in out:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    return deduped


def main():
    ap = argparse.ArgumentParser(description="Send an ad-hoc SMS via a client's Twilio config")
    ap.add_argument("config", help="path to client config.json")
    ap.add_argument("--to", required=True, help="comma list: crew,owner,operator,all or raw +E164 numbers")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--body", help="message text")
    g.add_argument("--body-file", help="path to a file containing the message text")
    ap.add_argument("--dry-run", action="store_true", help="print, don't send")
    args = ap.parse_args()

    cfg = load_config(args.config)

    body = args.body if args.body is not None else open(args.body_file).read().rstrip("\n")
    recipients = resolve_recipients(cfg, args.to)
    if not recipients:
        print("No recipients resolved.", file=sys.stderr)
        sys.exit(1)

    print(f"Sending to {len(recipients)} recipient(s): {recipients}")
    failed = 0
    for to in recipients:
        sid, status = send_sms(cfg, to, body, dry_run=args.dry_run)
        print(f"  {to}: {sid} ({status})")
        failed += sid is None
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
