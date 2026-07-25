# RAM Roster Viewer

A browser-based viewer for a Royal Air Maroc crew roster, kept in sync
automatically by a GitHub Action and viewed through a passphrase-locked,
single-file web app hosted on GitHub Pages.

## Features
- GitHub Action polls RAM CrewAccess on a schedule and publishes your roster
- View all activities (flights, standby, training, duties) with full
  timeline, crew, and training details
- Filter by activity type, month, or view a calendar layout
- **Export to iCalendar (.ics)** — import into Apple Calendar, Google
  Calendar, or Outlook, or subscribe to the auto-updating feed URL
- Push notification (via [ntfy.sh](https://ntfy.sh)) whenever a duty is
  added, removed, or changed
- Works offline via a service worker + local cache once unlocked once

## How it works

```
GitHub Action (every 2h)          GitHub Pages (public)         Your browser
──────────────────────────        ──────────────────────        ─────────────
Logs into RAM CrewAccess    -->    roster.enc.json         -->   You enter your
Diffs against last roster          (AES-256-GCM ciphertext,      passphrase
Sends ntfy push on changes          useless without it)          |
Encrypts with your passphrase      cal-<token>.ics                Web Crypto derives
Commits ONLY the encrypted          (plain .ics — calendar         a key (PBKDF2) and
  file + the token-named .ics       apps can't decrypt, so         decrypts in-browser
                                     the filename is the secret)  |
                                                                  Roster renders —
                                                                  plaintext never
                                                                  leaves your device
```

## Security model — please read before deploying your own copy

An earlier version of this app committed **plaintext `roster.json`**
(real crew names, IDs, and flight data) to this public repo, gated by a
client-side numeric PIN. That PIN was checked entirely in the browser and
never protected the file itself — anyone with the raw GitHub URL could
read it directly, no PIN required. If you forked this repo before this
fix, treat any roster data you committed as **fully public and
compromised** — purge it from git history (see below) and treat any
credentials/PINs you used as burned.

The current design:
- **`roster.enc.json`** — the real roster, encrypted (AES-256-GCM, key
  derived via PBKDF2-HMAC-SHA256, 210,000 iterations) by the Action before
  it's ever written to git. The passphrase never touches git, GitHub
  Pages, or any log. Without the passphrase, the committed file is
  unreadable.
- **`cal-<token>.ics`** (or whatever `ICS_FILENAME` you choose) — calendar
  apps can only do a plain, unauthenticated GET, so this file can't be
  encrypted the same way. Its only protection is an unguessable filename —
  this is the same model Google Calendar's "private address" ICS links use.
  Treat this filename/URL as a secret; anyone who has it can read your
  schedule.
- **ntfy.sh push notifications** contain crew names and duty changes in
  plaintext, sent to a third-party service, readable by anyone who
  subscribes to your topic. Use a long, random `NTFY_TOPIC` (not something
  guessable like your name), or self-host ntfy, or skip this feature.

This is a real improvement over a bare PIN, but it's still **not** the same
as a real multi-user backend with server-side auth — it's appropriate for
a single-person personal tool where "the ciphertext/URL is public but
useless without a secret" is an acceptable tradeoff. If you want this for
more than one person, put it behind real authentication instead.

## Setup

1. **Repository secrets** (Settings -> Secrets and variables -> Actions):

   | Secret | Purpose |
   |---|---|
   | `RAM_USER` / `RAM_PASS` | RAM CrewAccess login used by the Action |
   | `ROSTER_PASSPHRASE` | Encrypts/decrypts `roster.enc.json`. Use a real random passphrase (8+ characters, ideally longer/random — not a 6-digit PIN) |
   | `ICS_FILENAME` | e.g. `cal-8f3a1c9d2b.ics` — pick a long random string |
   | `NTFY_TOPIC` | *(optional)* long random string for push notifications |

2. Push to `main` — the Action runs on its schedule (every 2 hours) or via
   **Actions -> Automated RAM Roster Sync -> Run workflow**.
3. Open the GitHub Pages URL, enter your `ROSTER_PASSPHRASE` to unlock.
4. If you have an existing calendar subscription pointed at the old
   `calendar.ics`, update it to your new `ICS_FILENAME`.

### If you're migrating from the old plaintext version
Delete `roster.json`/`calendar.ics` from git history (not just the latest
commit — every commit that ever contained them):
```bash
pip install git-filter-repo
git filter-repo --path roster.json --path roster_old.json --path calendar.ics --invert-paths --force
git push origin --force --all
```
Then rotate your RAM CrewAccess password if you have any reason to think
the old repo/PIN were seen by anyone else.

## Hosting
Still a single-file frontend (`index.html`) hosted via GitHub Pages, plus
one GitHub Action and two small Python scripts (`scripts/encrypt_roster.py`,
`scripts/decrypt_roster.py`) that never leave GitHub's infrastructure. No
separate backend/server to run or pay for.
