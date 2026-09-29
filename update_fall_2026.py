#!/usr/bin/env python3
"""Refresh the Kapiʻolani Fall 2026 course-browser data in index.html.

This updater preserves the already-tested HTML/CSS/JavaScript interface and the
embedded 2026–2027 catalog descriptions. It replaces only the DATA array and
the "Current as of" timestamp after collecting fresh section data from UH Class
Availability.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

SOURCE_ROOT = "https://www.sis.hawaii.edu:9350/crseavail"
TERM = "202710"
CAMPUS = "KAP"
TERM_YEAR = 2026

SUBJECTS = [
    "ACC", "AMST", "ANTH", "ART", "ASAN", "ASL", "ASTR",
    "BIOC", "BIOL", "BLAW", "BOT", "BUS",
    "CE", "CHEM", "CHN", "CHW", "COM", "CULN",
    "DENT", "DNCE",
    "EALL", "ECON", "ED", "EE", "EMT", "ENG", "ENT", "ERTH", "ES", "ESL", "ESOL", "ESS",
    "FIL", "FR", "FSHE", "GEO",
    "HAW", "HDFS", "HIST", "HLTH", "HOST", "HUM", "HWST",
    "ICS", "IS", "ITS", "JPN", "JOUR", "KOR",
    "LAW", "LING", "LLEA", "LLL",
    "MATH", "ME", "MEDA", "MGT", "MICR", "MICT", "MLT", "MUS",
    "NREM", "NURS", "OCN", "OEST", "OTA",
    "PACS", "PHIL", "PHRM", "PHYL", "PHYS", "POLS", "PSY", "PTA",
    "RAD", "REL", "RESP", "SCI", "SLT", "SOC", "SP", "SPAN", "SSCI", "SW",
    "THEA", "WS", "ZOO",
]

SUBJECT_TO_DEPARTMENT = {
    "ACC": "BUS", "AMST": "HUM", "ANTH": "SSCI", "ART": "HUM", "ASAN": "HUM", "ASL": "LLL", "ASTR": "MS",
    "BIOC": "MS", "BIOL": "MS", "BLAW": "BUS", "BOT": "MS", "BUS": "BUS",
    "CE": "MS", "CHEM": "MS", "CHN": "LLL", "CHW": "HS", "COM": "LLL", "CULN": "CULN",
    "DENT": "HS", "DNCE": "HUM", "EALL": "LLL", "ECON": "SSCI", "ED": "SSCI", "EE": "MS",
    "EMT": "EMS", "ENG": "LLL", "ENT": "BUS", "ERTH": "MS", "ES": "HUM", "ESL": "LLL", "ESOL": "LLL", "ESS": "MS",
    "FIL": "LLL", "FR": "LLL", "FSHE": "FSER", "GEO": "SSCI", "HAW": "LLL", "HDFS": "SSCI",
    "HIST": "HUM", "HLTH": "HS", "HOST": "HOSP", "HUM": "HUM", "HWST": "HUM",
    "ICS": "MS", "IS": "LLL", "ITS": "BUS", "JPN": "LLL", "JOUR": "LLL", "KOR": "LLL",
    "LAW": "BUS", "LING": "LLL", "LLEA": "LLL", "LLL": "LLL",
    "MATH": "MS", "ME": "MS", "MEDA": "HS", "MGT": "BUS", "MICR": "MS", "MICT": "EMS", "MLT": "HS", "MUS": "HUM",
    "NREM": "MS", "NURS": "NURS", "OCN": "MS", "OEST": "MS", "OTA": "HS",
    "PACS": "HUM", "PHIL": "HUM", "PHRM": "HS", "PHYL": "MS", "PHYS": "MS", "POLS": "SSCI", "PSY": "SSCI", "PTA": "HS",
    "RAD": "HS", "REL": "HUM", "RESP": "HS", "SCI": "MS", "SLT": "LLL", "SOC": "SSCI",
    "SP": "HUM", "SPAN": "LLL", "SSCI": "SSCI", "SW": "SSCI", "THEA": "HUM", "WS": "HUM", "ZOO": "MS",
}

DAY_LABELS = {"M": "Mon", "T": "Tue", "W": "Wed", "R": "Thu", "F": "Fri", "S": "Sat", "U": "Sun"}
DIAGNOSTIC_DIR = Path("diagnostics")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"[ \t\f\v]+", " ", str(value).replace("\xa0", " ")).strip()


def clean_multiline(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    blank = False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif out and not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def norm(value: Any) -> str:
    return clean(value).replace("ʻ", "'").replace("‘", "'").replace("’", "'").lower()


def clean_crn(value: Any) -> str:
    value = re.sub(r"\s*\(Xlst-P\)\s*", "", clean(value), flags=re.I).strip()
    return re.sub(r"^\*+\s*", "", value).strip()


def course_number_sort(value: Any) -> str:
    value = clean(value).upper()
    m = re.match(r"^(\d+)(.*)$", value)
    return f"{int(m.group(1)):05d}{m.group(2)}" if m else value


def parse_number_pair(value: str) -> tuple[str, float]:
    value = clean(value)
    m = re.search(r"(\d+)\s*/\s*(\d+)", value)
    if not m:
        return value or "TBA", -1.0
    return f"{m.group(1)}/{m.group(2)}", float(m.group(1))


def parse_email_from_cell(cell: Tag | None) -> str:
    if cell is None:
        return ""
    for anchor in cell.find_all("a", href=True):
        visible = clean(anchor.get_text(" ", strip=True))
        m = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", visible, re.I)
        if m:
            return m.group(0)
        query = parse_qs(urlparse(anchor.get("href", "")).query)
        for key in ("query", "email"):
            if key in query:
                candidate = unquote(query[key][0])
                if "@" in candidate:
                    return candidate
    m = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", cell.get_text(" ", strip=True), re.I)
    return m.group(0) if m else ""


def parse_instructor(cell: Tag | None) -> tuple[str, str]:
    if cell is None:
        return "TBA", ""
    email = parse_email_from_cell(cell)
    parts = [clean(s) for s in cell.stripped_strings]
    parts = [p for p in parts if p and p.lower() != email.lower()]
    return (parts[0] if parts else "TBA"), email


def normalize_days(cell: Tag | None) -> str:
    if cell is None:
        return ""
    codes: list[str] = []
    mapping = {
        "monday": "M", "tuesday": "T", "wednesday": "W", "thursday": "R",
        "friday": "F", "saturday": "S", "sunday": "U",
    }
    for span in cell.find_all(attrs={"aria-label": True}):
        code = mapping.get(norm(span.get("aria-label")))
        if code and code not in codes:
            codes.append(code)
    if codes:
        return "".join(codes)
    return re.sub(r"[^MTWRFSU]", "", clean(cell.get_text(" ", strip=True)).upper())


def display_days(days: str) -> str:
    return " / ".join(DAY_LABELS.get(ch, ch) for ch in days) if days else "TBA"


def _minutes(hour: int, minute: int, suffix: str) -> int:
    hour %= 12
    if suffix.lower() == "p":
        hour += 12
    return hour * 60 + minute


def parse_time_range(raw: str) -> tuple[str, str]:
    raw = clean(raw)
    if not raw or raw.upper() in {"TBA", "ARR", "ARRANGED"}:
        return raw or "Time TBA", "9999"
    m = re.fullmatch(
        r"(\d{1,2}):(\d{2})([ap]?)\s*[-–—]\s*(\d{1,2}):(\d{2})([ap]?)",
        raw,
        flags=re.I,
    )
    if not m:
        return raw, "9999"
    sh, sm, ss, eh, em, es = m.groups()
    sh_i, sm_i, eh_i, em_i = int(sh), int(sm), int(eh), int(em)
    ss, es = ss.lower(), es.lower()
    if not es and ss:
        es = ss
    if not ss and es:
        ss = es if _minutes(sh_i, sm_i, es) <= _minutes(eh_i, em_i, es) else ("a" if es == "p" else "p")

    def fmt(hour: int, minute: int, suffix: str) -> str:
        return f"{hour}:{minute:02d} {'AM' if suffix == 'a' else 'PM'}" if suffix else f"{hour}:{minute:02d}"

    display = f"{fmt(sh_i, sm_i, ss)}–{fmt(eh_i, em_i, es)}"
    sort_minutes = _minutes(sh_i, sm_i, ss) if ss else 24 * 60 + 1
    return display, f"{sort_minutes:04d}"


def parse_date_range(raw: str, year: int) -> tuple[str, str, str, str]:
    raw = clean(raw)
    if not raw:
        return "", "", "", ""
    m = re.fullmatch(
        r"(\d{1,2})/(\d{1,2})\s*[-–—]\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?",
        raw,
    )
    if not m:
        return raw, raw, "", ""
    sm, sd, em, ed, y = m.groups()
    y_i = int(y) if y else year
    if y and y_i < 100:
        y_i += 2000
    start = datetime(y_i, int(sm), int(sd))
    end = datetime(y_i, int(em), int(ed))
    if end < start:
        end = end.replace(year=end.year + 1)
    if start.year == end.year:
        display = f"{start.strftime('%b')} {start.day}–{end.strftime('%b')} {end.day}, {end.year}"
    else:
        display = f"{start.strftime('%b')} {start.day}, {start.year}–{end.strftime('%b')} {end.day}, {end.year}"
    return (
        display,
        f"{start.strftime('%b')} {start.day}, {start.year}",
        f"{end.strftime('%b')} {end.day}, {end.year}",
        start.strftime("%Y-%m-%d"),
    )


def class_has(tag: Tag, class_name: str) -> bool:
    return class_name in (tag.get("class") or [])


def parse_meeting(cells: list[Tag]) -> dict[str, str] | None:
    if len(cells) < 4:
        return None
    days = normalize_days(cells[0])
    time_raw = clean(cells[1].get_text(" ", strip=True))
    room = clean(cells[2].get_text(" ", strip=True)) or "TBA"
    dates_raw = clean(cells[3].get_text(" ", strip=True))
    time_display, time_sort = parse_time_range(time_raw)
    dates_display, start_date, end_date, date_sort = parse_date_range(dates_raw, TERM_YEAR)
    return {
        "days": days,
        "daysDisplay": display_days(days),
        "timeRaw": time_raw,
        "time": time_display,
        "timeSort": time_sort,
        "room": room,
        "datesRaw": dates_raw,
        "dates": dates_display or dates_raw,
        "startDate": start_date,
        "endDate": end_date,
        "dateSort": date_sort,
    }


def parse_subject_html(page_html: str, expected_subject: str = "") -> list[dict[str, Any]]:
    soup = BeautifulSoup(page_html, "html.parser")
    records: list[dict[str, Any]] = []

    for row in soup.select("tr.dataRow"):
        grid = row.select_one("div.dataGrid")
        if not grid:
            continue

        children = [
            child
            for child in grid.find_all("div", recursive=False)
            if isinstance(child, Tag)
        ]
        stop = len(children)
        for idx, child in enumerate(children):
            if class_has(child, "dataFullRow") or class_has(child, "dataFullRowContent"):
                stop = idx
                break

        main = children[:stop]
        if len(main) < 13:
            continue

        base = main[:13]
        designations = clean(base[0].get_text(" ", strip=True)).rstrip(", ")
        crn_raw = clean(base[1].get_text(" ", strip=True))
        grouped = crn_raw.lstrip().startswith("*")
        crn = clean_crn(crn_raw)
        course_code = clean(base[2].get_text(" ", strip=True)).upper()
        match = re.fullmatch(r"([A-Z][A-Z0-9]{1,7})\s+(\d{1,4}[A-Z]?)", course_code)
        if not match:
            continue

        alpha, number = match.group(1), match.group(2)
        section = clean(base[3].get_text(" ", strip=True))
        title = clean(base[4].get_text(" ", strip=True))
        credits = clean(base[5].get_text(" ", strip=True))
        instructor, email = parse_instructor(base[6])
        enrollment, enrollment_sort = parse_number_pair(base[7].get_text(" ", strip=True))
        waitlist, waitlist_sort = parse_number_pair(base[8].get_text(" ", strip=True))

        meetings: list[dict[str, str]] = []
        first = parse_meeting(base[9:13])
        if first:
            meetings.append(first)

        extras = [cell for cell in main[13:] if not class_has(cell, "meetingFiller")]
        for pos in range(0, len(extras), 4):
            meeting = parse_meeting(extras[pos : pos + 4])
            if meeting:
                meetings.append(meeting)

        detail_tags = grid.select("div.dataFullRowContent")
        section_details = clean_multiline(
            "\n\n".join(tag.get_text("\n", strip=True) for tag in detail_tags)
        )

        meeting_days = [m["days"] for m in meetings if m.get("days")]
        schedules = [f"{m['daysDisplay']} • {m['time']}" for m in meetings]
        locations = [m["room"] for m in meetings]
        dates: list[str] = []
        for meeting in meetings:
            if meeting["dates"] and meeting["dates"] not in dates:
                dates.append(meeting["dates"])

        first_meeting = meetings[0] if meetings else {
            "startDate": "",
            "endDate": "",
            "dateSort": "",
            "days": "",
            "timeSort": "9999",
        }

        records.append(
            {
                "department": SUBJECT_TO_DEPARTMENT.get(alpha, ""),
                "courseAlpha": alpha,
                "courseNumber": number,
                "courseNumberSort": course_number_sort(number),
                "courseTitle": title,
                "section": section,
                "crn": crn,
                "grouped": grouped,
                "credits": credits,
                "specialDesignations": designations,
                "startDate": first_meeting.get("startDate", ""),
                "startDateSort": first_meeting.get("dateSort", ""),
                "endDate": first_meeting.get("endDate", ""),
                "datesDisplay": "\n".join(dates),
                "daysRaw": " | ".join(meeting_days),
                "meetingDays": meeting_days,
                "schedule": "\n".join(schedules) if schedules else "Time TBA",
                "scheduleSort": f"{first_meeting.get('days', '')} {first_meeting.get('timeSort', '9999')}",
                "location": "\n".join(locations) if locations else "TBA",
                "meetings": meetings,
                "enrollment": enrollment,
                "enrollmentSort": enrollment_sort,
                "waitlist": waitlist,
                "waitlistSort": waitlist_sort,
                "instructor": instructor,
                "instructorEmail": email,
                "sectionDetails": section_details,
                "catalogDescription": "",
                "catalogSource": "",
            }
        )

    return records


def save_diagnostic(page: Page, subject: str, label: str) -> None:
    DIAGNOSTIC_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{label}_{subject.lower()}"
    html_path = DIAGNOSTIC_DIR / f"{stem}.html"
    png_path = DIAGNOSTIC_DIR / f"{stem}.png"
    txt_path = DIAGNOSTIC_DIR / f"{stem}.txt"

    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception as exc:
        print(f"[diagnostic] Could not save HTML: {exc}")

    try:
        page.screenshot(path=str(png_path), full_page=True)
    except Exception as exc:
        print(f"[diagnostic] Could not save screenshot: {exc}")

    try:
        body = page.locator("body").inner_text(timeout=2000)
    except Exception as exc:
        body = f"Could not read body text: {exc}"

    txt_path.write_text(
        f"URL: {page.url}\n\n{body[:12000]}",
        encoding="utf-8",
    )
    print(f"[diagnostic] Saved {html_path}, {png_path}, and {txt_path}")


def subject_page_state(page: Page, subject: str) -> str:
    if page.locator("tr.dataRow").count() > 0:
        return "rows"

    try:
        body = page.locator("body").inner_text(timeout=2000)
    except Exception:
        return ""

    body_l = body.lower()
    valid_heading = (
        "fall 2026" in body_l
        and "kapiolani community college" in body_l
        and subject.lower() in body_l
    )
    table_header = "crn" in body_l and "course" in body_l and "credits" in body_l
    explicit_empty = bool(
        re.search(
            r"no (?:classes|sections|courses|results)|"
            r"there are no (?:classes|sections|courses)|"
            r"0 (?:classes|sections|courses)",
            body_l,
        )
    )

    if explicit_empty or (valid_heading and table_header):
        return "empty"
    return ""


def fetch_subject(
    page: Page,
    subject: str,
    *,
    goto_timeout_ms: int = 15000,
    ready_timeout_s: float = 5.0,
) -> list[dict[str, Any]]:
    url = f"{SOURCE_ROOT}/{TERM}/{CAMPUS}/{subject}"

    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=goto_timeout_ms,
        )
    except Exception:
        save_diagnostic(page, subject, "navigation_failure")
        raise

    status = response.status if response else None
    if status is not None and status >= 400:
        save_diagnostic(page, subject, f"http_{status}")
        raise RuntimeError(f"HTTP {status} for {url}")

    deadline = time.monotonic() + ready_timeout_s
    state = ""
    while time.monotonic() < deadline:
        state = subject_page_state(page, subject)
        if state:
            break
        time.sleep(0.25)

    if not state:
        save_diagnostic(page, subject, "unexpected_page")
        raise RuntimeError(
            f"{subject}: page never looked like a Fall 2026 Kapiʻolani subject page "
            f"within {ready_timeout_s:.1f} seconds. Final URL: {page.url}"
        )

    html = page.content()
    records = parse_subject_html(html, subject)

    if state == "rows" and not records:
        save_diagnostic(page, subject, "parser_failure")
        raise RuntimeError(
            f"{subject}: the page had course rows, but the parser extracted none."
        )

    return records


def smoke_test(page: Page) -> None:
    print("Preflight: testing UH access with ESOL ...", flush=True)
    records = fetch_subject(
        page,
        "ESOL",
        goto_timeout_ms=12000,
        ready_timeout_s=4.0,
    )
    if not records:
        save_diagnostic(page, "ESOL", "preflight_no_rows")
        raise RuntimeError(
            "Preflight failed: ESOL returned no course rows. "
            "The GitHub runner may not be seeing the same UH page as a normal browser."
        )

    wrong = sorted(
        {str(r.get("courseAlpha") or "") for r in records}
        - {"ESOL"}
    )
    if wrong:
        save_diagnostic(page, "ESOL", "preflight_wrong_alpha")
        raise RuntimeError(
            f"Preflight failed: unexpected course alphas on ESOL page: {wrong}"
        )

    print(f"Preflight passed: ESOL returned {len(records)} section(s).", flush=True)


def collect(page: Page, delay: float = 0.15) -> list[dict[str, Any]]:
    all_records: list[dict[str, Any]] = []
    errors: list[str] = []

    for index, subject in enumerate(SUBJECTS, 1):
        print(
            f"[{index:02d}/{len(SUBJECTS):02d}] {subject}: ",
            end="",
            flush=True,
        )
        try:
            records = fetch_subject(page, subject)
            all_records.extend(records)
            print(f"{len(records)} section(s)", flush=True)
        except Exception as exc:
            errors.append(f"{subject}: {exc}")
            print(f"ERROR: {exc}", flush=True)
            # One bad subject means the snapshot would be incomplete. Fail fast
            # rather than waiting through the rest of the alphabet.
            break

        if delay:
            time.sleep(delay)

    if errors:
        raise RuntimeError(
            "Subject collection failed; refusing to publish an incomplete update:\n"
            + "\n".join(errors)
        )

    by_key: dict[str, dict[str, Any]] = {}
    for record in all_records:
        key = record["crn"] or "|".join(
            [
                record["courseAlpha"],
                record["courseNumber"],
                record["section"],
                record["schedule"],
                record["location"],
            ]
        )
        previous = by_key.get(key)
        if previous is None:
            by_key[key] = record
        else:
            old_score = len(previous.get("sectionDetails", "")) + len(previous.get("meetings", [])) * 50
            new_score = len(record.get("sectionDetails", "")) + len(record.get("meetings", [])) * 50
            if new_score > old_score:
                by_key[key] = record

    return list(by_key.values())

def extract_data(html: str) -> tuple[list[dict[str, Any]], int, int]:
    start_marker = "const DATA="
    end_marker = ";\nconst DEFAULT_SORTS="
    start = html.find(start_marker)
    if start < 0:
        raise RuntimeError("Could not find const DATA= in index.html")
    data_start = start + len(start_marker)
    end = html.find(end_marker, data_start)
    if end < 0:
        raise RuntimeError("Could not find the end of the DATA array in index.html")
    return json.loads(html[data_start:end]), data_start, end


def preserve_catalog(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> None:
    by_course: dict[tuple[str, str], tuple[str, str]] = {}
    by_crn: dict[str, tuple[str, str]] = {}

    for record in old:
        desc = str(record.get("catalogDescription") or "")
        source = str(record.get("catalogSource") or "")
        if not desc:
            continue

        key = (
            str(record.get("courseAlpha") or ""),
            str(record.get("courseNumber") or ""),
        )
        by_course.setdefault(key, (desc, source))

        crn = str(record.get("crn") or "")
        if crn:
            by_crn[crn] = (desc, source)

    for record in new:
        pair = by_crn.get(str(record.get("crn") or ""))
        if pair is None:
            pair = by_course.get((record["courseAlpha"], record["courseNumber"]))
        if pair:
            record["catalogDescription"], record["catalogSource"] = pair


def update_html(
    template: str,
    records: list[dict[str, Any]],
    data_start: int,
    data_end: int,
) -> str:
    payload = json.dumps(records, ensure_ascii=False)
    html = template[:data_start] + payload + template[data_end:]

    now = datetime.now(ZoneInfo("Pacific/Honolulu"))
    stamp = now.strftime("%B %-d, %Y at %-I:%M %p HST")
    replacement = (
        f'<p class="timestamp">Current as of {stamp}. '
        "Enrollment and section information can change.</p>"
    )

    html, count = re.subn(
        r'<p class="timestamp">.*?</p>',
        replacement,
        html,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError(
            "Could not update the Current as of timestamp in index.html"
        )
    return html


def validate(
    old: list[dict[str, Any]],
    new: list[dict[str, Any]],
    html: str,
) -> None:
    if len(new) < 500:
        raise RuntimeError(
            f"Only {len(new)} sections were collected; refusing to publish."
        )

    if old and len(new) < len(old) * 0.70:
        raise RuntimeError(
            f"Section count fell from {len(old)} to {len(new)}; refusing to publish."
        )

    alphas = {record.get("courseAlpha") for record in new}
    for required in ("ESOL", "IS"):
        if required not in alphas:
            raise RuntimeError(
                f"Required course alpha {required} is missing; refusing to publish."
            )

    if "COURSE_ALPHAS" not in html or "text:IS" not in html:
        raise RuntimeError(
            "The v9.5 exact-alpha search code is missing from index.html."
        )

    catalog_count = sum(bool(r.get("catalogDescription")) for r in new)
    if catalog_count < 100:
        raise RuntimeError(
            f"Only {catalog_count} catalog descriptions were preserved; refusing to publish."
        )

    print(
        f"Validation passed: {len(new)} sections, "
        f"{catalog_count} catalog descriptions."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", default="index.html")
    parser.add_argument(
        "--json-out",
        default="course_browser_fall_2026_current.json",
    )
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Test one known ESOL page and exit without changing any files.",
    )
    args = parser.parse_args()

    html_path = Path(args.html)
    template = html_path.read_text(encoding="utf-8")
    old_records, data_start, data_end = extract_data(template)
    print(f"Existing browser contains {len(old_records)} sections.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1500, "height": 1000},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(5000)
        page.set_default_navigation_timeout(15000)

        smoke_test(page)
        if args.smoke_test:
            browser.close()
            return

        records = collect(page, delay=max(0.0, args.delay))
        browser.close()

    preserve_catalog(old_records, records)
    records.sort(
        key=lambda r: (
            r.get("courseAlpha", ""),
            r.get("courseNumberSort", ""),
            r.get("scheduleSort", ""),
            r.get("location", ""),
            r.get("crn", ""),
        )
    )

    refreshed_html = update_html(
        template,
        records,
        data_start,
        data_end,
    )
    validate(old_records, records, refreshed_html)

    html_path.write_text(refreshed_html, encoding="utf-8")
    Path(args.json_out).write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    old_counts = Counter(r.get("courseAlpha", "") for r in old_records)
    new_counts = Counter(r.get("courseAlpha", "") for r in records)
    changed_subjects = sorted(
        key
        for key in set(old_counts) | set(new_counts)
        if old_counts[key] != new_counts[key]
    )

    print(f"Wrote {html_path} and {args.json_out}.")
    if changed_subjects:
        print("Subject section-count changes:")
        for subject in changed_subjects:
            print(
                f"  {subject}: "
                f"{old_counts[subject]} -> {new_counts[subject]}"
            )


if __name__ == "__main__":
    main()
