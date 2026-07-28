#!/usr/bin/env python3
"""
Generates an .ics calendar feed from roster.json.
Mirrors the in-app "Export Calendar (.ics)" logic in index.html, but runs
automatically inside the GitHub Action so the file at a fixed public URL
always reflects the latest roster. Cancelled flights are excluded entirely,
so a subscribed calendar app removes them automatically on its next refresh.
"""
import json
from datetime import datetime, timezone


def parse_iso(iso):
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def ics_date(dt):
    # Floating local time (no trailing Z) — matches the exact digits shown in
    # the roster instead of letting calendar apps re-shift them by timezone.
    return dt.strftime("%Y%m%dT%H%M%S")


def ics_date_utc_now():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M00Z")


def fold(line):
    out = []
    while len(line) > 75:
        out.append(line[:75])
        line = " " + line[75:]
    out.append(line)
    return "\r\n".join(out)


def esc(s):
    if not s:
        return ""
    return (s.replace("\\", "\\\\").replace(";", "\\;")
             .replace(",", "\\,").replace("\n", "\\n"))


def fmt_duration(mins):
    if mins is None:
        return "--"
    return f"{int(mins)//60}:{int(mins)%60:02d}h"


def fmt_time(iso):
    d = parse_iso(iso)
    if not d:
        return "--"
    return f"{d.hour:02d}:{d.minute:02d}"


def act_code_id(act):
    return ((act.get("activityCode") or {}).get("id") or "").upper()


def medical_info(act):
    """Returns {label, isFullDay} for CM (medical rest) / V1 (pre medical
    test) / VMM (medical test day) entries, else None."""
    code = act_code_id(act)
    if code == "CM":
        return {"label": "Medical Rest", "isFullDay": True}
    if code == "V1":
        return {"label": "Pre Medical Test", "isFullDay": False}
    if code == "VMM":
        return {"label": "Medical Test", "isFullDay": False}
    return None


def training_code_info(act):
    """Returns {label} for ground-training (e.g. CR2/TRN) and sim-check
    (e.g. FC/SIM) entries, whether the activityCode sits on the top-level
    activity or on one of its sub-activities. Real flights are excluded."""
    subs = act.get("activities", [])
    if any(s.get("type") == "flight-leg" for s in subs):
        return None

    codes = [c for c in [act.get("activityCode")] + [s.get("activityCode") for s in subs] if c]
    if any((c.get("group") or "").upper() == "SIM" for c in codes):
        return {"label": "SIM CHECK"}
    trn = next((c for c in codes if (c.get("group") or "").upper() in ("TRN", "GTR")), None)
    if trn:
        return {"label": trn.get("description") or "Ground Training"}
    return None


def classify(act):
    subs = act.get("activities", [])
    if act_code_id(act) == "RV":
        return "standby"
    if any(s.get("type") == "flight-leg" for s in subs):
        return "flight"
    if any(s.get("isStandby") for s in subs):
        return "standby"
    grp = (act.get("activityCode") or {}).get("group", "").upper()
    if grp in ("SIM", "TRN", "GTR"):
        return "training"
    if any(s.get("isTraining") or (s.get("activityCode") or {}).get("group") in ("SIM", "GTR") for s in subs):
        return "training"
    return "other"


def crew_lines_for(unit):
    """CDB/OPL/CC crew assigned to a single unit (leg, layover, or activity)."""
    crew_map = {}

    def get_pos(c):
        p = c.get("position")
        if isinstance(p, dict):
            return str(p.get("id", "")).upper()
        return str(p or "").upper()

    for c in unit.get("assignedCrew", []) or []:
        pos = get_pos(c)
        if pos in ("CDB", "OPL", "CC"):
            key = c.get("crewId") or (c.get("givenNames", "") + c.get("surname", ""))
            crew_map.setdefault(key, {**c, "position": pos})

    return [
        f"{c['position']}: {c.get('givenNames','')} {c.get('surname','')} ({c.get('crewId','')})"
        for c in crew_map.values()
    ]


def build_event_lines(now, uid, dtstart, dtend, summary, location, desc):
    lines = ["BEGIN:VEVENT"]
    lines.append(fold(f"UID:{esc(uid)}"))
    lines.append(f"DTSTAMP:{now}")
    lines.append(f"DTSTART:{ics_date(dtstart)}")
    lines.append(f"DTEND:{ics_date(dtend)}")
    lines.append(fold(f"SUMMARY:{esc(summary)}"))
    if location:
        lines.append(fold(f"LOCATION:{esc(location)}"))
    if desc:
        lines.append(fold(f"DESCRIPTION:{esc(chr(10).join(desc))}"))
    lines.append("END:VEVENT")
    return lines


def build_ical(activities, crew_id):
    now = ics_date_utc_now()
    SEP = "──────────"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//RAM Roster Viewer//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        fold(f"X-WR-CALNAME:RAM Roster – {crew_id}"), "X-WR-TIMEZONE:UTC",
    ]

    for idx, act in enumerate(activities):
        act_type = classify(act)
        subs = act.get("activities", [])
        all_legs = [s for s in subs if s.get("type") == "flight-leg"]

        # Drop cancelled legs. If a "flight" trip has none left, skip it entirely —
        # this is what makes a cancelled flight disappear from the calendar.
        legs = [l for l in all_legs if not l.get("isCancelled")]
        if act_type == "flight" and not legs:
            continue

        role = (act.get("key") or {}).get("role", "")
        key_name = (act.get("key") or {}).get("name", "")
        uid_base = f"ram-{crew_id}-{idx}-{act.get('startTime', idx)}@ram-roster"

        if act_type == "flight" and legs:
            # One VEVENT per flight leg, in flight order.
            for li, leg in enumerate(legs):
                dtstart, dtend = parse_iso(leg.get("startTime")), parse_iso(leg.get("endTime"))
                if not dtstart or not dtend:
                    continue

                fn = f"{leg.get('carrier','')}{leg.get('flightNumber', (leg.get('activityCode') or {}).get('id',''))}"
                takeoff = fmt_time(leg.get("startTime"))
                summary = (
                    f"✈ {fn + ' ' if fn else ''}{leg.get('startStation','')} → {leg.get('endStation','')}"
                    f" · {takeoff}" + (f" ({role})" if role else "")
                )

                ac = leg.get("aircraftType", "")
                reg = leg.get("tail", "")
                ac_reg = f"  {ac} {reg}".rstrip() if (ac or reg) else ""
                status = f"  [{leg['statusLabel']}]" if leg.get("statusLabel") else ""
                leg_line = (
                    f"{fn}  {leg.get('startStation','')} → {leg.get('endStation','')}  "
                    f"{fmt_time(leg.get('startTime'))}–{fmt_time(leg.get('endTime'))}"
                    f"{ac_reg}{status}"
                )

                crew_lines = crew_lines_for(leg)
                desc = [leg_line]
                if crew_lines:
                    desc.append(SEP)
                    desc.extend(crew_lines)

                lines.extend(build_event_lines(
                    now, f"{uid_base}-leg{li}", dtstart, dtend,
                    summary, leg.get("startStation", ""), desc
                ))

            # Layovers get their own VEVENTs too.
            for loi, lo in enumerate(s for s in subs if s.get("type") == "layover"):
                dtstart, dtend = parse_iso(lo.get("startTime")), parse_iso(lo.get("endTime"))
                if not dtstart or not dtend:
                    continue

                summary = f"🏨 Layover · {lo.get('startStation','?')}"
                dur = fmt_duration(int((dtend - dtstart).total_seconds() / 60))
                desc = ["All times UTC/Zulu"]
                if key_name:
                    desc.append(f"Trip: {key_name}")
                desc.append(f"Duration: {dur}")
                hotel = (lo.get("hotel") or {}).get("name")
                if hotel:
                    desc.append(f"Hotel: {hotel}")

                lines.extend(build_event_lines(
                    now, f"{uid_base}-layover{loi}", dtstart, dtend,
                    summary, lo.get("startStation", ""), desc
                ))

            continue

        # Non-flight duties (standby, training, other) — unchanged, single event.
        dtstart, dtend = parse_iso(act.get("startTime")), parse_iso(act.get("endTime"))
        if not dtstart or not dtend:
            continue

        med_info = medical_info(act)
        trn_info = training_code_info(act)

        icon  = {"standby": "🔁", "training": "📚", "other": "🗓"}.get(act_type, "")
        route = f"{act.get('startStation','')} → {act.get('endStation','')}"
        if med_info:
            icon, route = "🏥", med_info["label"]
        elif trn_info:
            route = trn_info["label"]

        summary  = f"{icon} {route}" + (f" ({role})" if role else "")
        location = act.get("startStation", "")

        desc = ["All times UTC/Zulu"]
        if key_name:
            desc.append(f"Trip: {key_name}")
        if act.get("durationMinutes"):
            desc.append(f"Duration: {fmt_duration(act['durationMinutes'])}")
        if (med_info or trn_info) and (act.get("activityCode") or {}).get("description"):
            code_id = (act.get("activityCode") or {}).get("id", "")
            desc.append(f"Code: {code_id} — {act['activityCode']['description']}")
        if act_type == "training":
            desc.extend(crew_lines_for(act))
            for s in subs:
                desc.extend(crew_lines_for(s))
                for ss in s.get("activities", []) or []:
                    desc.extend(crew_lines_for(ss))

        lines.extend(build_event_lines(now, uid_base, dtstart, dtend, summary, location, desc))

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


if __name__ == "__main__":
    import os

    # This writes a LOCAL, TEMPORARY file only — it is never committed to
    # the repo (see .gitignore and the workflow step that deletes it).
    # It exists purely so the next workflow step can read it and push it
    # to a secret Gist. Override via ICS_LOCAL_FILENAME only if you need
    # a different local path for manual/local testing.
    output_filename = os.environ.get("ICS_LOCAL_FILENAME", "roster_local.ics")

    with open("roster.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    entity = data.get("entity", data)
    activities = entity.get("activities", [])
    crew_id = entity.get("crewId", "CREW")

    ics = build_ical(activities, crew_id)
    with open(output_filename, "w", encoding="utf-8", newline="") as f:
        f.write(ics)

    print(f"Wrote local temp file {output_filename} with events for crew {crew_id}")
