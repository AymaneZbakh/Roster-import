# RAM Roster Viewer

A browser-based viewer for a Royal Air Maroc crew roster, kept in sync
automatically by a GitHub Action and viewed through a passphrase-locked,
single-file web app hosted on GitHub Pages.

## Features
- GitHub Action polls RAM CrewAccess on a schedule and publishes your roster
- View all activities (flights, standby, training, duties) with full
  timeline, crew, and training details
- Filter by activity type, month, or view a calendar layout
- **Export to iCalendar (.ics)** — subscribe to an auto-updating feed from
  Apple Calendar, Google Calendar, or Outlook
- Push notification (via [ntfy.sh](https://ntfy.sh)) whenever a duty is
  added, removed, or changed
- Works offline via a service worker + local cache once unlocked once

## How it works

```
GitHub Action (every 2h)          GitHub Pages (public repo)     Your browser
──────────────────────────        ──────────────────────────     ─────────────
Logs into RAM CrewAccess    -->    roster.enc.json          -->   You enter your
Diffs against last roster          (AES-256-GCM ciphertext,       passphrase
Sends ntfy push on changes          useless without it)           |
Encrypts with your passphrase                                    Web Crypto derives
Commits ONLY the encrypted    Secret Gist (NOT in the repo)        a key (PBKDF2) and
  file to the public repo    ─────────────────────────────         decrypts in-browser
                              roster-calendar.ics            |
Publishes .ics to a secret    (random gist ID, unlisted,    Roster renders —
  Gist via the GitHub API      not shown in any repo's       plaintext never
                                file browser)                 leaves your device
                                        |
                                Your calendar app subscribes
                                directly to the gist's raw URL
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

A second version tried to protect the calendar feed with an "unguessable
filename" committed into this public repo (e.g. `cal-<token>.ics`). **That
doesn't actually work** — a public repo's file browser lists every
filename in it, so the "secret" name is visible to anyone who opens the
repo page, completely defeating the point. Don't do this; it was a mistake
in an earlier iteration of this README.

The current design:
- **`roster.enc.json`** — the real roster, encrypted (AES-256-GCM, key
  derived via PBKDF2-HMAC-SHA256, 210,000 iterations) by the Action before
  it's ever written to git. The passphrase never touches git, GitHub
  Pages, or any log. It's fine for this file to be publicly listed in the
  repo, because without the passphrase it's unreadable ciphertext — the
  secrecy lives in the passphrase, not in hiding the file.
- **The calendar feed lives in a secret GitHub Gist, not in this repo at
  all.** Calendar apps can only do a plain, unauthenticated GET, so this
  file can't be encrypted the same way — but a secret gist gets a genuine
  random ID that is never listed anywhere (not on your repo page, not on
  your GitHub profile, not indexed by search). That randomness is real
  secrecy, unlike a filename sitting in a public repo's file list. Treat
  the gist's raw URL as a secret; anyone who has it can read your
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

1. **Create a secret Gist token.** GitHub -> your avatar -> **Settings** ->
   **Developer settings** -> **Personal access tokens** -> **Tokens
   (classic)** -> **Generate new token (classic)** -> check the **gist**
   scope only -> generate -> copy the token (you won't see it again).

2. **Repository secrets** (Settings -> Secrets and variables -> Actions):

   | Secret | Purpose |
   |---|---|
   | `RAM_USER` / `RAM_PASS` | RAM CrewAccess login used by the Action |
   | `ROSTER_PASSPHRASE` | Encrypts/decrypts `roster.enc.json`. Use a real random passphrase (8+ characters, ideally longer/random — not a 6-digit PIN) |
   | `GIST_TOKEN` | The personal access token from step 1 |
   | `GIST_ID` | Leave unset on your very first run — see step 3 |
   | `NTFY_TOPIC` | *(optional)* long random string for push notifications |

3. Push to `main`, then **Actions** -> **Automated RAM Roster Sync** ->
   **Run workflow**. On this first run (no `GIST_ID` set yet), the
   **"Publish calendar to secret Gist"** step creates a brand-new secret
   gist and prints its ID and raw URL in the logs — something like:
   ```
   Created new secret gist: a3f8e91b2c4d5e6f7890
   Subscribe your calendar app to: https://gist.githubusercontent.com/<you>/a3f8e91b2c4d5e6f7890/raw/roster-calendar.ics
   ```
   Copy that ID, go back to **Settings -> Secrets -> Actions**, and add it
   as the `GIST_ID` secret. Every run after that updates the *same* gist
   in place, so your calendar subscription URL never changes again.

4. Open the GitHub Pages URL, enter your `ROSTER_PASSPHRASE` to unlock.
5. Subscribe your calendar app to the raw gist URL from step 3 (see "How
   to subscribe" below).

### How to subscribe your calendar app
Calendar apps need `https://` (not `webcal://`) in most "Add by URL"
fields; on iPhone, **Settings -> Calendar -> Accounts -> Add Account ->
Other -> Add Subscribed Calendar** and paste the raw gist URL tends to be
more reliable than tapping a link directly.

### If you're migrating from an old plaintext or public-filename version
Delete `roster.json`/`roster_old.json`/`calendar.ics`/any old `*.ics`
filename you previously committed from git history (not just the latest
commit — every commit that ever contained them):
```bash
pip install git-filter-repo
git filter-repo --path roster.json --path roster_old.json --path calendar.ics --path <your-old-ics-filename> --invert-paths --force
git remote add origin https://github.com/<you>/Roster-import.git
git push origin --force --all
git push origin --force --tags
```
Then rotate your RAM CrewAccess password if you have any reason to think
the old repo/PIN were seen by anyone else — force-pushing rewrites what's
on GitHub going forward, but can't reach anyone who already cloned or
scraped the repo before you did this.

## Hosting
Still a single-file frontend (`index.html`) hosted via GitHub Pages, plus
one GitHub Action, two small Python scripts (`scripts/encrypt_roster.py`,
`scripts/decrypt_roster.py`) that never leave GitHub's infrastructure, and
one script (`scripts/publish_ics_gist.py`) that calls the GitHub Gists API.
No separate backend/server to run or pay for.
