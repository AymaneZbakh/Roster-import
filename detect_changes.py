#!/usr/bin/env python3
"""
Compares the previous roster.json against the newly fetched one and detects
ANY meaningful change: added duties, removed duties, flight time changes,
crew changes, aircraft/tail changes, cancellations/reinstatements, route
changes, and layover/hotel changes. Sends one consolidated push notification
via ntfy.sh (set NTFY_TOPIC as a GitHub Actions secret) if anything changed.
"""
import json
import os
import urllib.request

# Fields worth flagging when they change, per comparable unit (flight-leg,
# ground-task, or personal-activity). (json field, human label)
TRACKED_FIELDS = [
    ("startTime", "Start"),
    ("endTime", "End"),
    ("scheduledStartTime", "Sched. departure"),
    ("scheduledEndTime", "Sched. arrival"),
    ("startStation", "From"),
    ("endStation", "To"),
    ("aircraftType", "Aircraft type"),
    ("tail", "Registration"),
    ("statusLabel", "Status"),
    ("isCancelled", "Cancelled"),
]


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def trip_key(act):
    key = (act.get("key") or {}).get("name")
    if key:
        return key
    return f"{act.get('type','')}|{act.get('startTime','')}|{act.get('startStation','')}|{act.get('endStation','')}"


def label_trip(act):
    date = (act.get("startTime") or "")[:10]
    route = f"{act.get('startStation','?')}→{act.get('endStation','?')}"
    return f"{route} ({date})"


def comparable_units(act):
    """Return a dict of {unit_key: unit_dict} for the meaningful sub-parts of
    a trip: flight legs, ground tasks, and layovers. Falls back to the
    activity itself for flat entries like sick leave / days off."""
    subs = act.get("activities")
    if not subs:
        return {f"self|{trip_key(act)}": act}

    units = {}
    for s in subs:
        t = s.get("type")
        if t == "flight-leg":
            k = s.get("fingerprint") or f"leg|{s.get('flightNumber')}|{s.get('startTime')}"
            units[k] = s
        elif t == "ground-task":
            k = s.get("fingerprint") or f"gt|{s.get('startTime')}"
            units[k] = s
        elif t == "layover":
            k = s.get("fingerprint") or f"layover|{s.get('startTime')}"
            units[k] = s
    return units


def unit_label_str(unit):
    """Describe a unit (flight leg / ground task / layover) by flight number
    and departure->destination — never a trip id/key."""
    fn = unit.get("flightNumber")
    route = f"{unit.get('startStation','?')}→{unit.get('endStation','?')}"
    if fn:
        return f"{unit.get('carrier','')}{fn} {route}"
    return route


def crew_set(unit):
    return {
        (c.get("crewId"), c.get("position"))
        for c in (unit.get("assignedCrew") or [])
    }


def crew_names(unit):
    return {
        c.get("crewId"): f"{c.get('givenNames','')} {c.get('surname','')}".strip()
        for c in (unit.get("assignedCrew") or [])
    }


def hotel_name(unit):
    return (unit.get("hotel") or {}).get("name")


def diff_unit(label, old_unit, new_unit):
    changes = []

    for field, human in TRACKED_FIELDS:
        old_val = old_unit.get(field)
        new_val = new_unit.get(field)
        if old_val != new_val and not (not old_val and not new_val):
            if field == "isCancelled":
                if new_val and not old_val:
                    changes.append(f"{label}: ❌ CANCELLED")
                elif old_val and not new_val:
                    changes.append(f"{label}: ✅ Reinstated (no longer cancelled)")
            else:
                changes.append(f"{label}: {human} changed {old_val or '—'} → {new_val or '—'}")

    old_crew = crew_set(old_unit)
    new_crew = crew_set(new_unit)
    if old_crew != new_crew:
        names = {**crew_names(old_unit), **crew_names(new_unit)}
        added = new_crew - old_crew
        removed = old_crew - new_crew
        parts = []
        if added:
            parts.append("added " + ", ".join(f"{names.get(cid,cid)} ({pos})" for cid, pos in added))
        if removed:
            parts.append("removed " + ", ".join(f"{names.get(cid,cid)} ({pos})" for cid, pos in removed))
        changes.append(f"{label}: Crew changed — {'; '.join(parts)}")

    old_hotel = hotel_name(old_unit)
    new_hotel = hotel_name(new_unit)
    if old_hotel != new_hotel and (old_hotel or new_hotel):
        changes.append(f"{label}: Hotel changed {old_hotel or '—'} → {new_hotel or '—'}")

    return changes


def main():
    old = load("roster_old.json")
    new = load("roster.json")

    old_entity = (old or {}).get("entity", old or {})
    new_entity = (new or {}).get("entity", new or {})

    old_trips = {trip_key(a): a for a in old_entity.get("activities", [])}
    new_trips = {trip_key(a): a for a in new_entity.get("activities", [])}

    messages = []

    # Added / removed duties
    for k in new_trips.keys() - old_trips.keys():
        if old_trips:  # skip noise on very first run when there's no baseline
            messages.append(f"🆕 NEW DUTY ADDED: {label_trip(new_trips[k])}")
    for k in old_trips.keys() - new_trips.keys():
        messages.append(f"🗑️ DUTY REMOVED: {label_trip(old_trips[k])}")

    # Modified duties
    for k in old_trips.keys() & new_trips.keys():
        old_act, new_act = old_trips[k], new_trips[k]
        old_units = comparable_units(old_act)
        new_units = comparable_units(new_act)
        trip_label = label_trip(new_act)
        trip_date = (new_act.get("startTime") or "")[:10]

        for uk in new_units.keys() - old_units.keys():
            messages.append(f"{unit_label_str(new_units[uk])} ({trip_date}): ➕ Flight/segment added")
        for uk in old_units.keys() - new_units.keys():
            messages.append(f"{unit_label_str(old_units[uk])} ({trip_date}): ➖ Flight/segment removed")

        for uk in old_units.keys() & new_units.keys():
            unit_label = trip_label
            fn = new_units[uk].get("flightNumber")
            if fn:
                unit_label = f"{new_units[uk].get('carrier','')}{fn} " + trip_label
            messages.extend(diff_unit(unit_label, old_units[uk], new_units[uk]))

    if not messages:
        print("No changes detected.")
        return

    print(f"Detected {len(messages)} change(s):")
    for m in messages:
        print(" -", m)

    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC secret not set — skipping push notification.")
        return

    body = "\n".join(messages)
    try:
        # HTTP headers must be Latin-1/ASCII only. An em dash (—) or any other
        # non-ASCII character in a header value makes urllib raise before the
        # request is even sent, which silently kills the notification. Keep
        # header values plain ASCII; UTF-8 content (emoji, accents, etc.) is
        # fine in the body since that's sent as encoded bytes, not a header.
        title = f"Roster Updated - {len(messages)} change(s)".encode("ascii", "ignore").decode("ascii")
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=body.encode("utf-8"),
            headers={"Title": title, "Priority": "high"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"ntfy send failed: {e}")


if __name__ == "__main__":
    main()
