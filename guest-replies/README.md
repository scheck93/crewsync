# Guest-reply assistant

When an Airbnb guest messages you, Airbnb emails you a copy. This Google Apps
Script watches for those emails every 5 minutes, asks Claude whether the
message needs an answer, and if it does, sends **you** an email in the same
Gmail conversation with suggested replies and a **Copy** button for each.
You paste the one you like into the Airbnb chat.

- Bare reactions and "ok / sounds good" acknowledgments are skipped. Checkout and thank-you notes get a short goodbye reply in your style.
- If your playbook has the answer, you get one reply.
- If it doesn't, you get 2–3 options (e.g. yes / no / let me check), with
  `[placeholders]` for anything it doesn't know, plus a note on what to add
  to the playbook.
- When a guest says they've checked out, the email also has a **Text
  Brittany** button (and **Text someone else**, for a backup cleaner). It
  opens your Messages app with "the guests just checked out, next check-in is
  ..." filled in; you tap Send.
- It never messages the guest. It only emails you.

Claude's knowledge comes from the **CrewSync Cabin Playbook** Google Doc
(ID in `Code.gs`). Fill in the `[?]` items and keep adding answers; every
draft reads the latest version.

## Setup (about 5 minutes)

1. Go to <https://script.google.com>, click **New project**, name it
   "CrewSync guest replies".
2. Delete the sample code in `Code.gs` and paste in this folder's `Code.gs`.
   Save.
3. Left sidebar → **Project Settings** (gear) → **Script properties** →
   **Add script property**:
   - Property: `ANTHROPIC_API_KEY`
   - Value: your Anthropic API key

   And for the checkout "Text cleaner" button:
   - `CLEANER_NAME`: e.g. `Brittany`
   - `CLEANER_PHONE`: e.g. `+15185551234`

   Save. (These stay in your Google account, not in this public repo.)
4. Back in the **Editor**, choose `setup` in the function dropdown at the top
   and click **Run**. Google asks for permission (read Gmail, send email as
   you, read the playbook Doc, connect to the Anthropic API). Click through
   *Advanced → Go to CrewSync guest replies (unsafe)*: "unsafe" only means
   Google hasn't reviewed your personal script.
5. Optional test: pick `testLatest` and **Run**. It drafts replies for your
   newest Airbnb message even if it wouldn't normally need one, and emails
   them to you.

That's it. `setup` marks every existing Airbnb email as already handled, so
you only get drafts for new messages.

## Day to day

- **Turn it off:** in script.google.com, open **Triggers** (alarm clock icon)
  and delete the `checkAirbnbMessages` trigger. Run `setup` again to turn it
  back on.
- **See what it did:** **Executions** in the left sidebar shows each run's log
  (which messages it saw and whether they needed a reply).
- **Changing the code:** edit `Code.gs` here, then paste it into the Apps
  Script project again.

## Cost

Each guest message that gets checked is one Claude API call, a few cents at
most. Your playbook is cached between calls to keep it cheap.

## GitHub timers (calendar sync, extend-stay offers, heartbeat)

GitHub's own scheduled runs don't fire for this repo, so this script also
starts those GitHub workflows on a timer:

- calendar sync: every 30 minutes
- extend-stay offers: daily around 4 PM ET
- weekly heartbeat: Mondays around 9 AM ET

One-time setup:

1. Create a GitHub token: <https://github.com/settings/personal-access-tokens/new>
   - Token name: `crewsync-timer`; Expiration: 1 year (set a reminder to renew)
   - Repository access: **Only select repositories** → `scheck93/crewsync`
   - Permissions → Repository permissions → **Actions: Read and write**
   - **Generate token** and copy it.
2. In Apps Script: Project Settings → Script properties → add `GITHUB_TOKEN`
   with the token as the value.
3. In the editor, pick `setupGitHubTimers` and **Run**. It starts the timers
   and kicks off one calendar sync right away (you'll see it in GitHub's
   Actions tab within a minute).
