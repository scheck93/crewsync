# CrewSync

Automated short-term-rental schedule notifier. Every 30 minutes it checks a
property's Airbnb/VRBO calendar feeds, compares them with the last saved
state, and — **only when something changed** — texts the crew (cleaner,
handyman, co-host) a short note with a link to a live calendar page.

Everything runs for free on GitHub: **GitHub Actions** does the checking and
texting, **GitHub Pages** hosts the calendar. No laptop or server needed.

---

## What the crew gets

A short text:

```
David's Cozy Cabin schedule changed: cancelled Fri 11/20 to Sun 11/22; new booking Thu 12/3 to Mon 12/7.

See the updated calendar: https://scheck93.github.io/crewsync/david/

Please text David to confirm you can cover the new schedule.
- David
```

The link opens a mobile-friendly calendar (no login) with Airbnb, VRBO and
host-block nights color-coded, a list of upcoming cleanings (checkout days,
with **QUICK FLIP** when the next guest arrives the same day) and all
upcoming bookings. The owner gets a separate confirmation text.

---

## What's in the box

```
crewsync/
├── crewsync.py              # the engine — runs one client's sync
├── run_all.py               # runs every client under clients/
├── build_site.py            # builds the GitHub Pages site into _site/
├── send_message.py          # ad-hoc one-off sends (intros, announcements)
├── heartbeat.py             # weekly "still running" text to the owner
├── extend_offers.py         # daily "invite today's guest to stay longer" text to the owner
├── guest-replies/           # Gmail -> Claude suggested replies to Airbnb guests (Apps Script)
├── run.sh                   # local helper: loads .env, runs the engine
├── clients/
│   └── david-cozy-cabin/
│       ├── config.json      # PUBLIC settings (name, link, options)
│       └── snapshot.txt     # last-known booking state (auto-managed)
├── website/                 # landing page (site root) + /copy/ page for reply drafts
├── private.example.json     # template for the PRIVATE settings
├── .github/workflows/crewsync.yml   # schedule + deploy
└── README.md
```

### Public vs private settings

This repo is public, so anything sensitive stays out of it:

| Where | What |
|---|---|
| `clients/<name>/config.json` (committed) | client name, owner first name, signature, timezone, calendar link, filter/guard options |
| `CREWSYNC_PRIVATE` GitHub secret (or `private.json` locally, gitignored) | calendar feed URLs, phone numbers, Twilio account SID + from number |
| `TWILIO_AUTH_TOKEN` GitHub secret (or `.env` locally, gitignored) | Twilio auth token |

`CREWSYNC_PRIVATE` is one JSON object keyed by client folder name — see
`private.example.json`.

---

## One-time setup on GitHub

1. **Secrets** — repo *Settings → Secrets and variables → Actions → New
   repository secret*:
   - `TWILIO_AUTH_TOKEN` — the token from your local `.env`
   - `CREWSYNC_PRIVATE` — the full contents of `private.json`
2. **Pages** — *Settings → Pages → Build and deployment → Source:
   GitHub Actions*.
3. **Reset the snapshot** — *Actions → CrewSync → Run workflow*, tick
   **"Reset snapshot"**. This saves the current calendars without texting
   anyone, so the first real run doesn't announce every change since the
   last time it ran. It also publishes the calendar page.
4. Optional: run it again with **"Dry run"** ticked and read the log to see
   what would be sent.

From then on it runs every 30 minutes by itself. If a run fails (e.g. a
calendar link was rotated), GitHub emails you.

**Extend-stay offers:** every afternoon (about 4-5 PM ET), for each guest
who checked in today on a 1-5 night stay with the cabin open the night after
checkout, the owner gets a text with a ready-to-copy "stay longer at a
discount" message to send the guest in Airbnb/VRBO. Each booking is offered
once (`clients/<name>/offers_sent.txt`). Tune it per client in `config.json`:
`"extension_offers": {"enabled": true, "min_nights": 1, "max_nights": 5}`.

**Weekly heartbeat:** every Monday morning the owner gets a text like
"CrewSync weekly check: running normally. 331 calendar checks in the last 7
days, 0 failed." If that text stops showing up, something is wrong. Test it
any time from *Actions → Weekly heartbeat → Run workflow*.

> **Twilio + links:** US carriers filter texts with links unless your
> Twilio A2P 10DLC campaign says messages include embedded links. If crew
> texts stop arriving (Twilio error 30007), update the campaign in the
> Twilio console.

---

## Running locally (optional)

Python 3.9+, standard library only. Put the private settings in
`private.json` and the token in `.env`, then:

```bash
python3 crewsync.py clients/david-cozy-cabin/config.json --dry-run   # preview, sends nothing
./run.sh clients/david-cozy-cabin/config.json                        # real run
python3 run_all.py --dry-run                                         # every client
python3 build_site.py                                                # site -> ./_site
```

A run prints one of:

- `No changes.` — nothing moved; no SMS sent, snapshot untouched.
- `Sent N change(s) to M recipient(s) (+ K confirmation(s)). SIDs: ...`
- `Suspicious-diff guard tripped: ...` — too many cancellations at once;
  the crew is **not** texted, only owner/operator get a watchdog alert, and
  the snapshot is left unchanged so it keeps flagging until you intervene.

---

## One-off messages

`send_message.py` sends arbitrary text to a client's people without touching
the sync logic (needs the private settings locally):

```bash
python3 send_message.py clients/david-cozy-cabin/config.json --to crew,owner --body-file intro.txt
python3 send_message.py clients/david-cozy-cabin/config.json --to all --body "..." --dry-run
```

`--to` accepts `crew`, `owner`, `operator`, `all`, and/or raw `+E164` numbers.

---

## Adding a client

1. Copy `clients/david-cozy-cabin/` to `clients/<new-name>/`, edit
   `config.json` (new `site_slug` and `calendar_url`), and empty
   `snapshot.txt`.
2. Add a `"<new-name>": {...}` entry to the `CREWSYNC_PRIVATE` secret.
3. Run the workflow once with **"Reset snapshot"**.

### `config.json` fields

```jsonc
{
  "client_name": "David's Cozy Cabin",   // used in texts and page title
  "owner_first_name": "David",           // "Please text David to confirm..."
  "signature": "- David",                // last line of the crew text (keep it ASCII)
  "timezone": "America/New_York",        // property's local zone ("today" basis)
  "site_slug": "david",                  // page lives at /<slug>/
  "calendar_url": "https://scheck93.github.io/crewsync/david/",
  "far_future_block_days": 180,          // ignore host blocks starting beyond this
  "suspicious_cancel_min": 3,            // guard trips if cancellations > max(min, pct * snapshot size)
  "suspicious_cancel_pct": 0.30
}
```

---

## How a run works

1. **Fetch** every feed. If any fetch fails, abort — never report a transient
   feed error as a pile of cancellations.
2. **Parse** VEVENTs (handles iCal line-folding and `VALUE=DATE` vs `DATE-TIME`).
3. **Filter** live feed and snapshot identically: drop past checkouts, drop
   host blocks starting more than `far_future_block_days` out.
4. **Diff** by UID -> NEW / CANCELLED / DATE CHANGE.
5. **Suspicious-diff guard** (see above).
6. **No changes ->** exit silently.
7. **Changes ->** short crew text (up to 3 changes listed, then "+N more"),
   plus a confirmation to the owner (+ operator if set).
8. **Save the snapshot.** The workflow commits it and redeploys the calendar.

Airbnb and VRBO don't offer webhooks for calendar changes, so polling every
30 minutes is as close to instant as it gets. Scheduled runs can start a few
minutes late when GitHub is busy.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Run fails with `HTTP 4xx from feed` | calendar link was rotated — regenerate it in Airbnb/VRBO and update `CREWSYNC_PRIVATE` |
| `ERROR ... HTTP 401` from Twilio | wrong/missing `TWILIO_AUTH_TOKEN` secret |
| `ERROR ... HTTP 21610` | recipient replied STOP |
| Texts accepted by Twilio but never arrive (30007) | enable embedded links on the A2P campaign |
| Crew got a flood of "new booking" | snapshot was stale — run the workflow with "Reset snapshot" |
| Daily host-block churn | lower `far_future_block_days` (e.g. 60) and reset the snapshot |
| Pause everything | *Actions → CrewSync → ⋯ → Disable workflow* |

---

## Notes

- The calendar page is public to anyone with the link (marked `noindex` so
  search engines skip it). It shows booking dates and the guest first names
  VRBO includes in its feed.
- Snapshots are committed to the repo so state survives between runs; they
  contain dates, iCal UIDs and those same first names.
- If the repo goes 45 days with no commits, the workflow commits
  `.github/keepalive`, because GitHub pauses scheduled workflows in public
  repos after 60 days of inactivity.
