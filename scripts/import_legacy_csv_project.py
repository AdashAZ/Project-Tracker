#!/usr/bin/env python3
"""
One-time importer for legacy wide CSV exports into Project Tracker.

Usage (dry run, no writes):
  python scripts/import_legacy_csv_project.py --csv "C:\\path\\legacy.csv"

Apply import:
  python scripts/import_legacy_csv_project.py --csv "C:\\path\\legacy.csv" --apply
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from app import create_app
from models import Comment, Machine, MachineWorkType, Project, TimeEntry, db


@dataclass(frozen=True)
class ParsedEntry:
    row_num: int
    source: str
    raw_work_type: str
    work_date: date
    hours: float
    mapped_type: str
    other_description: str | None

    @property
    def work_type_label(self) -> str:
        if self.mapped_type == "Other" and self.other_description:
            return f"Other - {self.other_description}"
        return self.mapped_type


HEADER_TEXT = {
    "work type:",
    "date",
    "hrs.",
    "nctp",
    "total incurred hrs on all machines",
    "avg.hrs per machine:",
    "hrs per machine incurred total:",
    "report status:",
    "balance of hrs. per machine:",
    "description",
    "p/n",
    "quantity",
}


def safe_cell(row: list[str], idx: int) -> str:
    if idx < 0 or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def try_parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%m/%d/%Y").date()
    except ValueError:
        return None


def try_parse_float(value: str) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def looks_like_header_text(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return True
    if text in HEADER_TEXT:
        return True
    if text.startswith("total "):
        return True
    if text.startswith("avg."):
        return True
    if "edb project id#" in text:
        return True
    return False


def map_work_type(raw: str) -> tuple[str, str | None]:
    lowered = raw.lower()
    if "risk assessment" in lowered or re.search(r"\bassessment\b", lowered):
        return "RA", None
    if "safety concept" in lowered:
        return "SC", None
    if "validation" in lowered or re.search(r"\bvv\b", lowered):
        return "VV", None
    if re.search(r"\bsol\b", lowered):
        return "SOL", None
    return "Other", raw.strip()


def parse_project_header(header_text: str) -> tuple[str, str]:
    lines = [line.strip() for line in (header_text or "").splitlines() if line.strip()]
    project_ref = lines[0] if lines else ""
    edb_number = ""
    for line in lines:
        match = re.search(r"EDB Project ID#\s*(.+)$", line, flags=re.IGNORECASE)
        if match:
            edb_number = match.group(1).strip()
            break
    return project_ref, edb_number


def infer_customer(rows: list[list[str]]) -> str:
    blocked = (
        "labor",
        "report",
        "nctp",
        "work type",
        "risk",
        "safety",
        "validation",
        "review",
        "project",
        "edb",
        "machine",
    )
    for row in rows[1:25]:
        for value in row[8:]:
            candidate = (value or "").strip()
            if not candidate:
                continue
            lowered = candidate.lower()
            if any(word in lowered for word in blocked):
                continue
            if ":" in candidate or "/" in candidate:
                continue
            if len(candidate) > 40:
                continue
            return candidate
    return ""


def extract_entries(rows: list[list[str]]) -> list[ParsedEntry]:
    parsed: list[ParsedEntry] = []
    for row_index, row in enumerate(rows[1:], start=2):
        # Layout A: [work type, ..., date, ..., incurred hrs]
        work_a = safe_cell(row, 0)
        date_a = try_parse_date(safe_cell(row, 2))
        hours_a = try_parse_float(safe_cell(row, 4))
        if work_a and date_a and hours_a is not None and hours_a > 0 and not looks_like_header_text(work_a):
            mapped, other = map_work_type(work_a)
            parsed.append(
                ParsedEntry(
                    row_num=row_index,
                    source="A",
                    raw_work_type=work_a,
                    work_date=date_a,
                    hours=hours_a,
                    mapped_type=mapped,
                    other_description=other,
                )
            )

        # Layout B: [.., work type, date, hours]
        work_b = safe_cell(row, 3)
        date_b = try_parse_date(safe_cell(row, 4))
        hours_b = try_parse_float(safe_cell(row, 5))
        if work_b and date_b and hours_b is not None and hours_b > 0 and not looks_like_header_text(work_b):
            mapped, other = map_work_type(work_b)
            parsed.append(
                ParsedEntry(
                    row_num=row_index,
                    source="B",
                    raw_work_type=work_b,
                    work_date=date_b,
                    hours=hours_b,
                    mapped_type=mapped,
                    other_description=other,
                )
            )

    parsed.sort(key=lambda item: (item.work_date, item.row_num, item.source))
    return parsed


def extract_quoted_hours(rows: list[list[str]]) -> float:
    # Legacy sheet has multiple quoted columns; for this format we use max numeric
    # value in the "Hrs Quanity Quoted" column (index 3).
    max_quoted = 0.0
    for row in rows[1:]:
        quoted = try_parse_float(safe_cell(row, 3))
        if quoted is not None and quoted > max_quoted:
            max_quoted = quoted
    return max_quoted


def summarize_entries(entries: list[ParsedEntry]) -> list[tuple[str, str, float, int]]:
    totals: dict[tuple[str, str], tuple[float, int]] = {}
    for item in entries:
        other = item.other_description or ""
        key = (item.mapped_type, other)
        hours, count = totals.get(key, (0.0, 0))
        totals[key] = (hours + item.hours, count + 1)

    output: list[tuple[str, str, float, int]] = []
    for (mapped, other), (hours, count) in sorted(totals.items(), key=lambda i: (i[0][0], i[0][1])):
        output.append((mapped, other, round(hours, 2), count))
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import legacy project CSV into the local Project Tracker database.")
    parser.add_argument("--csv", required=True, help="Absolute path to CSV file.")
    parser.add_argument("--customer", default="", help="Override customer name. If omitted, script infers from CSV.")
    parser.add_argument("--machine-name", default="Press 3 & 4", help="Machine/asset name to create.")
    parser.add_argument("--status", default="Completed", choices=["N/S", "WIP", "Stopped", "In Review", "Completed"])
    parser.add_argument("--apply", action="store_true", help="Write to database. Without this flag, dry run only.")
    parser.add_argument("--allow-duplicate", action="store_true", help="Allow creating project even if matching ref/EDB exists.")
    return parser


def run() -> int:
    args = build_parser().parse_args()
    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8-sig") as fp:
        rows = list(csv.reader(fp))

    if not rows:
        raise SystemExit("CSV is empty.")

    header_col0 = safe_cell(rows[0], 0)
    project_ref, edb_number = parse_project_header(header_col0)
    customer = (args.customer or infer_customer(rows)).strip()
    machine_name = (args.machine_name or "").strip()

    if not customer:
        raise SystemExit("Could not infer customer from CSV. Re-run with --customer \"...\".")
    if not project_ref:
        raise SystemExit("Could not infer project reference from CSV header.")
    if not machine_name:
        raise SystemExit("Machine name cannot be empty.")

    entries = extract_entries(rows)
    if not entries:
        raise SystemExit("No dated hours entries were parsed from CSV.")

    quoted_hours = extract_quoted_hours(rows)
    if quoted_hours <= 0:
        raise SystemExit("Could not infer quoted hours from CSV.")

    total_incurred = round(sum(item.hours for item in entries), 2)
    summary = summarize_entries(entries)
    first_date = entries[0].work_date.isoformat()
    last_date = entries[-1].work_date.isoformat()

    print("=== Dry Run Preview ===")
    print(f"CSV: {csv_path}")
    print(f"Project: customer={customer} | ref={project_ref} | edb={edb_number or 'N/A'}")
    print(f"Machine: {machine_name}")
    print(f"Status: {args.status}")
    print(f"Quoted Hours (from CSV): {quoted_hours:.1f}")
    print(f"Incurred Hours (from parsed entries): {total_incurred:.1f}")
    print(f"Entries: {len(entries)} | Range: {first_date} -> {last_date}")
    print("Work Type Totals:")
    for mapped, other, hours, count in summary:
        if mapped == "Other" and other:
            print(f"  - Other - {other}: {hours:.1f}h ({count} entries)")
        else:
            print(f"  - {mapped}: {hours:.1f}h ({count} entries)")

    print("Sample entries:")
    for item in entries[:12]:
        label = item.work_type_label
        print(f"  - row {item.row_num}: {item.work_date.isoformat()} | {label} | {item.hours:.1f}h")

    if not args.apply:
        print("Dry run only. Re-run with --apply to write to DB.")
        return 0

    app = create_app()
    with app.app_context():
        duplicate = Project.query.filter(
            (Project.na_number == project_ref) | (Project.edb_number == edb_number)
        ).first()
        if duplicate and not args.allow_duplicate:
            raise SystemExit(
                "Matching project already exists "
                f"(id={duplicate.id}, ref={duplicate.na_number}, edb={duplicate.edb_number}). "
                "Use --allow-duplicate to override."
            )

        project = Project(
            customer=customer,
            location=None,
            product_line=None,
            na_number=project_ref,
            edb_number=edb_number or None,
            due_date=None,
            status=args.status,
            quoted_hours_total=quoted_hours,
        )
        db.session.add(project)
        db.session.flush()

        machine = Machine(
            project_id=project.id,
            machine_name=machine_name,
            status=args.status,
            quoted_hours=quoted_hours,
            incurred_hours=total_incurred,
        )
        db.session.add(machine)
        db.session.flush()

        unique_work_types: set[tuple[str, str | None]] = set()
        for item in entries:
            key = (item.mapped_type, item.other_description)
            unique_work_types.add(key)

            db.session.add(
                TimeEntry(
                    project_id=project.id,
                    machine_id=machine.id,
                    date=item.work_date,
                    work_type=item.work_type_label,
                    hours=item.hours,
                    notes=f"Imported from legacy CSV row {item.row_num}: {item.raw_work_type}",
                )
            )

        for work_type, other_description in sorted(unique_work_types, key=lambda x: (x[0], x[1] or "")):
            db.session.add(
                MachineWorkType(
                    machine_id=machine.id,
                    work_type=work_type,
                    other_description=other_description,
                )
            )

        db.session.add(
            Comment(
                project_id=project.id,
                machine_id=machine.id,
                author="System",
                comment=f"Backfilled {len(entries)} historical entries from legacy CSV: {csv_path.name}",
                created_at=date.today(),
            )
        )

        db.session.commit()

        print("=== Import Complete ===")
        print(f"Project ID: {project.id}")
        print(f"Machine ID: {machine.id}")
        print(f"Created time entries: {len(entries)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
