#!/usr/bin/env python3
"""
Generates calendar.ics from roster.json.
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


def classify(act):
    subs = act.get("activities", [])
    if any(s.get("type") == "flight-leg" for s in subs):
        return "flight"
    if any(s.get("isStandby") for s in subs):
        return "standby"
    if any(s.get("isTraining") or (s.get("activityCode") or {}).get("group") in ("SIM", "GTR") for s in subs):
        return "training"
    return "other"


def build_ical(activities, crew_id):
    now = ics_date_utc_now()
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//RAM Roster Viewer//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        fold(f"X-WR-CALNAME:RAM Roster – {crew_id}"), "X-WR-TIMEZONE:UTC",
    ]

    SEP = "──────────"

    def get_pos(c):
        p = c.get("position")
        if isinstance(p, dict):
            return str(p.get("id", "")).upper()
        return str(p or "").upper()

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

        # Crew (CDB/OPL/CC) is shared across every leg of the same duty, collect once.
        crew_map = {}
        if act_type in ("flight", "training"):
            def collect(src):
                for c in src.get("assignedCrew", []) or []:
                    pos = get_pos(c)
                    if pos in ("CDB", "OPL", "CC"):
                        key = c.get("crewId") or (c.get("givenNames", "") + c.get("surname", ""))
                        crew_map.setdefault(key, {**c, "position": pos})
            collect(act)
            for s in subs:
                collect(s)
                for ss in s.get("activities", []) or []:
                    collect(ss)
        crew_lines = [
            f"{c['position']}: {c.get('givenNames','')} {c.get('surname','')} ({c.get('crewId','')})"
            for c in crew_map.values()
        ]

        if act_type == "flight" and legs:
            # One VEVENT per leg (e.g. CMN → ORY and ORY → CMN as two separate
            # events) instead of a single event spanning the whole rotation.
            # Any layover between two legs is attached as a trailing note on
            # the leg that lands into it.
            for leg_idx, leg in enumerate(legs):
                dtstart = parse_iso(leg["startTime"])
                dtend = parse_iso(leg["endTime"])
                if not dtstart or not dtend:
                    continue

                fn = f"{leg.get('carrier','')}{leg.get('flightNumber', (leg.get('activityCode') or {}).get('id',''))}"
                status = f"  [{leg['statusLabel']}]" if leg.get("statusLabel") else ""
                ac = leg.get("aircraftType", "")
                reg = leg.get("tail", "")
                ac_reg = f"  {ac} {reg}".rstrip() if (ac or reg) else ""

                route = f"{leg['startStation']} → {leg['endStation']}"
                summary = f"✈ {route}" + (f" {fn}" if fn else "") + (f" ({role})" if role else "")
                location = leg.get("startStation", "")

                desc = ["All times UTC/Zulu"]
                if key_name:
                    desc.append(f"Trip: {key_name}")
                block_mins = int((dtend - dtstart).total_seconds() / 60)
                desc.append(f"Block: {fmt_duration(block_mins)}")
                desc.append(
                    f"{fn}  {route}  {fmt_time(leg['startTime'])}–{fmt_time(leg['endTime'])}"
                    f"{ac_reg}{status}"
                )

                # Find a layover that sits between this leg and the next one in `subs`.
                try:
                    leg_pos = subs.index(leg)
                except ValueError:
                    leg_pos = -1
                if leg_pos != -1:
                    for s in subs[leg_pos + 1:]:
                        if s.get("type") == "flight-leg":
                            break
                        if s.get("type") == "layover":
                            hotel = (s.get("hotel") or {}).get("name")
                            st, et = parse_iso(s.get("startTime")), parse_iso(s.get("endTime"))
                            dur = fmt_duration(int((et - st).total_seconds() / 60)) if st and et else None
                            line = f"🌙 Layover {s.get('startStation','')}"
                            if dur:
                                line += f"  {dur}"
                            if hotel:
                                line += f"  — {hotel}"
                            desc.append(SEP)
                            desc.append(line)

                if crew_lines:
                    desc.append(SEP)
                    desc.extend(crew_lines)

                uid = f"ram-{crew_id}-{idx}-{leg_idx}-{leg.get('startTime', leg_idx)}@ram-roster"
                lines.append("BEGIN:VEVENT")
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
            continue

        # Non-flight duties (standby, training, other) keep a single event for the whole span.
        dtstart = parse_iso(act.get("startTime"))
        dtend = parse_iso(act.get("endTime"))
        if not dtstart or not dtend:
            continue

        icon = {"standby": "🔁", "training": "📚", "other": "🗓"}.get(act_type, "")
        route = f"{act.get('startStation','')} → {act.get('endStation','')}"
        summary = f"{icon} {route}" + (f" ({role})" if role else "")
        location = act.get("startStation", "")

        desc = ["All times UTC/Zulu"]
        if key_name:
            desc.append(f"Trip: {key_name}")
        if act.get("durationMinutes"):
            desc.append(f"Duration: {fmt_duration(act['durationMinutes'])}")
        if crew_lines:
            if len(desc) > 1:
                desc.append(SEP)
            desc.extend(crew_lines)

        uid = f"ram-{crew_id}-{idx}-{act.get('startTime', idx)}@ram-roster"
        lines.append("BEGIN:VEVENT")
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

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


if __name__ == "__main__":
    with open("roster.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    entity = data.get("entity", data)
    activities = entity.get("activities", [])
    crew_id = entity.get("crewId", "CREW")

    ics = build_ical(activities, crew_id)
    with open("calendar.ics", "w", encoding="utf-8", newline="") as f:
        f.write(ics)

    print(f"Wrote calendar.ics with events for crew {crew_id}")
