#!/usr/bin/env python3
"""
Publishes an .ics file to a SECRET GitHub Gist instead of committing it to
the public repo. A secret gist gets a random, non-guessable, non-indexed
ID in its URL and is never listed on your repo page or GitHub profile —
unlike a filename inside a public repo, which is always visible in the
file browser regardless of how random the name is.

First run (no GIST_ID secret set yet): creates a new secret gist and
prints its ID + the stable subscribable raw URL. You then need to save
that ID as the GIST_ID repository secret so future runs update the same
gist instead of creating a new one each time.

Every subsequent run: updates the existing gist's file content in place,
so the raw URL for calendar apps stays exactly the same, forever.

Usage:
    python scripts/publish_ics_gist.py <path-to-ics-file>
Requires env vars:
    GIST_TOKEN  - a GitHub Personal Access Token with the 'gist' scope
    GIST_ID     - (optional on first run) the gist to update
"""
import os
import sys
import json
import requests

GIST_FILENAME = "roster-calendar.ics"  # name *inside* the gist; irrelevant to secrecy


def main():
    if len(sys.argv) != 2:
        print("Usage: publish_ics_gist.py <path-to-ics-file>", file=sys.stderr)
        sys.exit(1)

    ics_path = sys.argv[1]
    token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("GIST_ID", "").strip()

    if not token:
        print("ERROR: GIST_TOKEN environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    with open(ics_path, "r", encoding="utf-8") as f:
        content = f.read()

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"files": {GIST_FILENAME: {"content": content}}}

    if gist_id:
        resp = requests.patch(
            f"https://api.github.com/gists/{gist_id}", headers=headers, json=payload
        )
        if resp.status_code != 200:
            print(f"ERROR updating gist {gist_id}: {resp.status_code} {resp.text}", file=sys.stderr)
            sys.exit(1)
        data = resp.json()
        print(f"Updated existing secret gist {gist_id}")
    else:
        payload["description"] = "Roster calendar feed (secret — do not share this link)"
        payload["public"] = False  # "secret" gist: unlisted, not indexed, random ID
        resp = requests.post("https://api.github.com/gists", headers=headers, json=payload)
        if resp.status_code != 201:
            print(f"ERROR creating gist: {resp.status_code} {resp.text}", file=sys.stderr)
            sys.exit(1)
        data = resp.json()
        new_id = data["id"]
        print("=" * 70)
        print(f"Created new secret gist: {new_id}")
        print("ACTION REQUIRED: save this as your GIST_ID repository secret,")
        print("or every future run will create a brand new gist/URL instead")
        print("of updating this one.")
        print("=" * 70)

    raw_url = data["files"][GIST_FILENAME]["raw_url"]
    # raw_url includes a specific revision hash; the stable, always-latest
    # URL for calendar subscriptions drops that hash segment:
    stable_url = raw_url.rsplit("/", 2)[0] + "/" + GIST_FILENAME
    print(f"Subscribe your calendar app to: {stable_url}")


if __name__ == "__main__":
    main()
