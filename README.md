# CrewSync

Automated short-term-rental schedule notifier. Polls each client's Airbnb/VRBO
iCal feeds a few times a day, diffs against a saved snapshot, and texts the
crew (cleaner/handyman/co-host) via Twilio **only when something changes** —
new booking, cancellation, or date change. Silent on quiet runs.

This is the standalone version of the system originally built in Claude Cowork,
ported to plain Python so it can run anywhere (a laptop, a VPS, a Raspberry Pi,
a cron box) with no Claude/Cowork runtime.

---

## What's in the box

```
crewsync/
├── crewsync.py            # the engine — runs one client's sync
├── run_all.py             # runs every client under clients/
├── send_message.py        # ad-hoc one-off sends (intros, trial reminders)
├── run.sh                 # loads .env then runs the engine (used by cron)
├── clients/
│   ├── david-cozy-cabin/
│   │   ├── config.json    # feeds, recipients, Twilio account, options
│   │   └── snapshot.txt   # last-known booking state (auto-managed)
│   └── conor-backman/
│       ├── config.json
│       └── snapshot.txt
├── crontab.example        # schedule entries (8/6/9 for David, 9/12/8 for Conor)
├── .env.example           # template for the Twilio secret
├── .env                   # real Twilio token (gitignored — don't commit)
├── .gitignore
├── requirements.txt       # (stdlib only — see notes)
├── logs/                  # cron output lands here
└── README.md
```

---

## Requirements

- **Python 3.9+** (uses `zoneinfo`). Nothing else — the engine is pure standard
  library. No `pip install` needed in most environments.
- On a minimal box that throws `ZoneInfoNotFoundError`, run `pip install tzdata`.
- A **Twilio account** with an SMS-capable `from` number (already configured).

Check your version:

```bash
python3 --version   # need 3.9 or newer
```

---

## One-time setup

1. **Drop in the Twilio secret.** Copy the template and confirm the token:

   ```bash
   cp .env.example .env      # then edit .env
   ```

   `.env` already contains your existing token. It is listed in `.gitignore`
   so it won't be committed. The engine reads `TWILIO_AUTH_TOKEN` from the
   environment first, and only falls back to the config if the env var is
   unset. **Keep the token out of `config.json` and out of git.**

2. **Make the wrappers executable** (if not already):

   ```bash
   chmod +x run.sh
   ```

3. **Test without sending anything** (see "Dry run" below).

---

## Running it

### Dry run (recommended first)

Computes the diff and prints exactly what *would* be sent, but sends no SMS
and does not modify the snapshot:

```bash
python3 crewsync.py clients/conor-backman/config.json --dry-run
```

### Real run, one client

```bash
# Token from your shell environment:
TWILIO_AUTH_TOKEN=xxxxxxxx python3 crewsync.py clients/conor-backman/config.json

# ...or let run.sh load it from .env:
./run.sh clients/conor-backman/config.json
```

### All clients at once

```bash
python3 run_all.py            # real
python3 run_all.py --dry-run  # preview
```

A run prints one of:

- `No changes.` — nothing moved; no SMS sent, snapshot untouched.
- `Sent N change(s) to M recipient(s) (+ K confirmation(s)). SIDs: ...`
- `Suspicious-diff guard tripped: ...` — too many cancellations at once;
  the crew is **not** texted, only owner/operator get a watchdog alert, and
  the snapshot is left unchanged so it keeps flagging until you intervene.

---

## Scheduling (cron)

The original cadence was **three checks per day** per client:

- David's Cozy Cabin -> **8 AM, 6 PM, 9 PM ET**
- Conor / 267 Anthony Ave -> **9 AM, 12 PM, 8 PM ET**

To replicate:

1. Set the server timezone to Eastern (or convert the hours to your zone):

   ```bash
   sudo timedatectl set-timezone America/New_York
   ```

2. Edit `crontab.example` — replace `/ABSOLUTE/PATH/TO/crewsync` with the real
   path — then install it:

   ```bash
   crontab crontab.example
   crontab -l         # verify
   ```

Each cron line `cd`s into the project, runs `./run.sh <client>` (which loads
`.env`), and appends output to `logs/<client>.log`.

> Note: scheduled jobs only run when the machine is on. On a laptop that
> sleeps, use an always-on host (VPS / Pi) for reliable delivery.

---

## One-off messages (intros, trial reminders, announcements)

`send_message.py` sends arbitrary text to a client's people without touching
the sync logic.

```bash
# Welcome/intro text to the crew + owner:
python3 send_message.py clients/conor-backman/config.json \
  --to crew,owner --body-file intro.txt

# Trial-end reminder to owner + operator only:
python3 send_message.py clients/conor-backman/config.json \
  --to owner,operator --body "Heads up — your trial ends 6/1..."

# Always preview first:
python3 send_message.py clients/conor-backman/config.json --to all --body "..." --dry-run
```

`--to` accepts `crew`, `owner`, `operator`, `all`, and/or raw `+E164` numbers,
comma-separated and de-duplicated.

For a true one-shot at a future time (e.g. Conor's trial-end reminder on
May 29), use `at` instead of cron so it fires exactly once, or just run
`send_message.py` manually that day.

---

## Configuring a client

Each `clients/<name>/config.json`:

```jsonc
{
  "client_name": "267 Anthony Ave",                 // used in confirmation + watchdog text
  "sms_title": "267 Anthony Ave Schedule Update",   // header line of the crew SMS
  "signature": "— Conor",                           // last line of the crew SMS
  "timezone": "America/New_York",                   // property's local zone ("today" basis)
  "feeds": [                                         // one or more iCal feeds
    { "source": "AIRBNB", "url": "https://www.airbnb.com/calendar/ical/...ics?t=..." }
    // add { "source": "VRBO", "url": "..." } for dual-source listings
  ],
  "twilio": {
    "account_sid": "ACxxxxxxxx",
    "from_number": "+1...",
    "_auth_token_note": "token comes from TWILIO_AUTH_TOKEN env, not here"
  },
  "owner_number": "+1...",            // gets the confirmation SMS
  "operator_number": "+1...",         // CrewSync operator; CCed on confirmation + watchdog. null if none.
  "notification_recipients": [        // who gets the schedule-update SMS (crew, + operator if you want them to see it)
    "+1...", "+1..."
  ],
  "far_future_block_days": 180,       // host blocks starting beyond this are ignored (rolling-window noise)
  "suspicious_cancel_min": 3,         // guard trips if cancellations > max(this, pct * snapshot size)
  "suspicious_cancel_pct": 0.30
}
```

**To add a new client:** copy a `clients/<name>/` folder, edit `config.json`,
empty the `snapshot.txt` data rows, then do one real run during a quiet period
to initialize state, and add a cron line.

---

## How a run works (engine logic)

1. **Fetch** every feed. If any fetch fails, abort — never report a transient
   feed error as a pile of cancellations.
2. **Parse** VEVENTs (handles iCal line-folding and `VALUE=DATE` vs `DATE-TIME`).
3. **Filter** both the live feed and the snapshot identically: drop past
   checkouts, drop host blocks starting more than `far_future_block_days` out.
4. **Diff** by UID -> NEW / CANCELLED / DATE CHANGE.
5. **Suspicious-diff guard:** if cancellations exceed
   `max(suspicious_cancel_min, suspicious_cancel_pct x snapshot_size)`, skip the
   crew SMS, alert owner/operator, and leave the snapshot intact. (Protects
   against a broken/partial feed nuking real bookings.)
6. **No changes ->** exit silently.
7. **Changes ->** compose one schedule-update SMS:
   - chronological, `Wed, 5/13` style dates, `/YY` suffix only for other years
   - VRBO uses guest names; Airbnb shows "Reserved"; host blocks show "Host block"
   - "checks in today" / "in-house" annotations relative to today
   - **QUICK FLIP** tag only when *two real bookings* share a turnover date
     (a Reserved -> Host block boundary is **not** a flip)
8. Send the update to `notification_recipients`, a confirmation to
   `owner_number` (+ `operator_number` if set).
9. **Overwrite the snapshot** with the new state (real runs only).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ZoneInfoNotFoundError` | `pip install tzdata` |
| `ERROR ... HTTP 401` from Twilio | wrong/missing `TWILIO_AUTH_TOKEN` |
| `ERROR ... HTTP 21610` | recipient replied STOP; they unsubscribed at the carrier |
| Crew got a flood of "NEW" on first run | snapshot was empty — initialize it with one real run during a quiet period, or pre-seed `snapshot.txt` |
| Daily "1 cancelled + 1 new" host-block churn | Airbnb's rolling advance-booking-window block is inside `far_future_block_days`; lower that value (e.g. 60) and re-init the snapshot |
| Want to pause a client | comment out its cron line |

---

## Security notes

- The Twilio **auth token is a credential**. It lives only in `.env`
  (gitignored). Don't paste it into `config.json` or commit it.
- `config.json` does contain phone numbers and the account SID — if you push
  this to a shared/public repo, treat those as sensitive too (use a private repo).
- `snapshot.txt` contains booking dates and iCal UIDs but no guest PII beyond
  first names that the feeds themselves expose.

---

## Migration notes

- Ported from the Claude Cowork scheduled tasks `cozy-cabin-rental-sync` and
  `conor-backman-rental-sync`. The natural-language SKILL.md logic is now
  deterministic Python in `crewsync.py`.
- Snapshots were copied from the live Cowork state as of 2026-05-18, so the
  first run here will see **no changes** (no duplicate "NEW" blast) as long as
  you run it before the next real booking change.
- Once this is running on your own scheduler, **disable the Cowork scheduled
  tasks** so the two systems don't both text the crew.
- Behavior parity included: suspicious-diff guard, real-to-real QUICK FLIP,
  180-day host-block filter, operator CC pattern, owner-only confirmations.
