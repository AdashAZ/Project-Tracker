# app.py
from datetime import date, datetime, time, timedelta
import json
import re
import os
import subprocess
import secrets
from collections import defaultdict

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)
from sqlalchemy import text, case, or_
from urllib.parse import quote
from markupsafe import Markup, escape

from models import (
    db,
    Project,
    ProductLine,
    ProjectJobQuote,
    Machine,
    MachineJob,
    TimeEntry,
    DailyActivityLog,
    DailyActivityEntry,
    DailyActivityPosting,
    Comment,
    MachineWorkType,
    AuditLog,
)
from admin import admin_bp
from sqlalchemy import case, desc

ALLOWED_STATUSES = {"N/S", "WIP", "Stopped", "In Review", "Completed"}
MACHINE_STATUS_OPTIONS = ["N/S", "WIP", "Stopped", "In Review", "Completed"]
WORK_TYPE_OPTIONS = ["RA", "SC", "VV", "SOL", "SISTEMA", "BOM", "ConSC", "ConRA", "Other"]
DAILY_ACTIVITY_CATEGORIES = ["Project", "Admin", "INM", "Sales Support", "Training", "Travel", "Other"]
SALES_SUPPORT_ADP_NUMBER = "600-303100"
MACHINE_MILESTONE_DEFINITIONS = [
    {
        "key": "cas_approval",
        "label": "Report CAS Approval Date",
        "field": "report_cas_approval_date",
        "na_field": "report_cas_approval_na",
    },
    {
        "key": "sent_customer",
        "label": "Report Sent to Customer Date",
        "field": "report_sent_customer_date",
        "na_field": "report_sent_customer_na",
    },
    {
        "key": "sent_review_edb",
        "label": "Report Sent for Review in EDB",
        "field": "report_sent_review_edb_date",
        "na_field": "report_sent_review_edb_na",
    },
    {
        "key": "released_edb",
        "label": "Released in EDB",
        "field": "released_in_edb_date",
        "na_field": "released_in_edb_na",
    },
    {
        "key": "uploaded_s_drive_reports",
        "label": "Uploaded to S Drive - REPORT(s)",
        "field": "uploaded_s_drive_reports_date",
        "na_field": "uploaded_s_drive_reports_na",
    },
    {
        "key": "uploaded_s_drive_jsa",
        "label": "Uploaded to S Drive - JSA",
        "field": "uploaded_s_drive_jsa_date",
        "na_field": "uploaded_s_drive_jsa_na",
    },
    {
        "key": "uploaded_s_drive_photos",
        "label": "Uploaded to S Drive - PHOTOS",
        "field": "uploaded_s_drive_photos_date",
        "na_field": "uploaded_s_drive_photos_na",
    },
    {
        "key": "uploaded_s_drive_vizio",
        "label": "Uploaded to S Drive - VIZIO",
        "field": "uploaded_s_drive_vizio_date",
        "na_field": "uploaded_s_drive_vizio_na",
    },
    {
        "key": "log_updated",
        "label": "Log Updated",
        "field": "log_updated_date",
        "na_field": "log_updated_na",
    },
]
MILESTONE_FIELD_BY_KEY = {item["key"]: item["field"] for item in MACHINE_MILESTONE_DEFINITIONS}
MILESTONE_NA_FIELD_BY_KEY = {item["key"]: item["na_field"] for item in MACHINE_MILESTONE_DEFINITIONS}


def format_work_type_label_value(work_type: str | None, other_description: str | None = None):
    if work_type == "Other":
        cleaned_other = (other_description or "").strip()
        if cleaned_other:
            return f"Other - {cleaned_other}"
    return work_type or ""


def get_machine_version_label_value(machine: Machine | None):
    if not machine:
        return "V1.0"
    version_number = getattr(machine, "version_number", None) or 1
    return f"V{version_number}.0"


def get_progress_bucket(pct_raw: float) -> str:
    if pct_raw <= 21.0:
        return "dash-progress-red"
    if pct_raw <= 61.0:
        return "dash-progress-amber"
    if pct_raw <= 99.9:
        return "dash-progress-yellow"
    return "dash-progress-green"


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    db_path = os.path.join(app.instance_path, "app.db")
    os.makedirs(app.instance_path, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    # Register admin blueprint
    app.register_blueprint(admin_bp)

    with app.app_context():
        db.create_all()
        ensure_project_schema()
        ensure_machine_schema()
        ensure_machine_job_schema()

    def parse_date_input(value: str | None):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def parse_time_input(value: str | None):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%H:%M").time()
        except ValueError:
            return None

    def parse_float_input(value: str | None):
        if value in (None, ""):
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def get_week_start(selected_date: date):
        return selected_date - timedelta(days=selected_date.weekday())

    def combine_notes(parts):
        return "; ".join(part for part in parts if part)

    def format_work_type_label(work_type: str, other_description: str | None = None):
        return format_work_type_label_value(work_type, other_description)

    def parse_work_types_payload(payload_raw: str | None, require_one: bool = True):
        if not payload_raw:
            return ([] if not require_one else None), ("At least one work type is required." if require_one else None)

        try:
            payload = json.loads(payload_raw)
        except (TypeError, ValueError):
            return None, "Invalid work type payload."

        if not isinstance(payload, list):
            return None, "Invalid work type payload."

        parsed = []
        seen = set()
        for item in payload:
            if not isinstance(item, dict):
                return None, "Invalid work type payload."

            work_type = (item.get("work_type") or "").strip()
            other_description = (item.get("other_description") or "").strip()
            quoted_hours_raw = item.get("quoted_hours")
            due_date_raw = (item.get("due_date") or "").strip()

            if work_type not in WORK_TYPE_OPTIONS:
                return None, "Invalid work type selected."

            if work_type == "Other" and not other_description:
                return None, "Other work type requires a description."

            key = (work_type, other_description)
            if key in seen:
                return None, "Each work type can only be entered once per machine version."
            seen.add(key)

            quoted_hours = parse_float_input(str(quoted_hours_raw) if quoted_hours_raw not in (None, "") else None)
            if quoted_hours is None:
                quoted_hours = 0.0
            if quoted_hours < 0:
                return None, "Quoted hours must be a valid non-negative number."

            due_date = parse_date_input(due_date_raw)
            if due_date_raw and due_date is None:
                return None, "Job due dates must be valid dates."

            parsed.append(
                {
                    "work_type": work_type,
                    "other_description": other_description or None,
                    "label": format_work_type_label(work_type, other_description),
                    "quoted_hours": quoted_hours,
                    "due_date": due_date,
                }
            )

        if require_one and not parsed:
            return None, "At least one work type is required."

        return parsed, None

    def serialize_audit_value(value):
        if value is None:
            return None
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return str(value)

    def audit_change(project_id: int, change_type: str, field_name: str | None = None, old_value=None, new_value=None, machine_id: int | None = None, machine_job_id: int | None = None, version_number: int | None = None, note: str | None = None):
        db.session.add(
            AuditLog(
                actor=session.get("username") or session.get("user") or "system",
                project_id=project_id,
                machine_id=machine_id,
                machine_job_id=machine_job_id,
                version_number=version_number,
                change_type=change_type,
                field_name=field_name,
                old_value=serialize_audit_value(old_value),
                new_value=serialize_audit_value(new_value),
                note=note,
            )
        )

    def audit_field_change(project_id: int, change_type: str, field_name: str, old_value, new_value, machine_id: int | None = None, machine_job_id: int | None = None, version_number: int | None = None, note: str | None = None):
        if serialize_audit_value(old_value) == serialize_audit_value(new_value):
            return
        audit_change(
            project_id,
            change_type,
            field_name,
            old_value,
            new_value,
            machine_id=machine_id,
            machine_job_id=machine_job_id,
            version_number=version_number,
            note=note,
        )

    def recalculate_project_quoted_hours(project: Project):
        job_total = (
            db.session.query(db.func.coalesce(db.func.sum(MachineJob.quoted_hours), 0.0))
            .join(Machine)
            .filter(Machine.project_id == project.id)
            .scalar()
        ) or 0.0
        quote_total = sum((quote.quoted_hours or 0.0) for quote in project.job_quotes)
        if job_total > 0:
            project.quoted_hours_total = job_total
        elif quote_total > 0:
            project.quoted_hours_total = quote_total

    def parse_job_quotes_payload(payload_raw: str | None):
        if not payload_raw:
            return [], None

        try:
            payload = json.loads(payload_raw)
        except (TypeError, ValueError):
            return None, "Invalid quoted-hours payload."

        if not isinstance(payload, list):
            return None, "Invalid quoted-hours payload."

        parsed = []
        seen = set()
        for item in payload:
            if not isinstance(item, dict):
                return None, "Invalid quoted-hours payload."

            work_type = (item.get("work_type") or "").strip()
            other_description = (item.get("other_description") or "").strip()
            hours_raw = item.get("quoted_hours")
            due_date_raw = (item.get("due_date") or "").strip()

            if not work_type and hours_raw in (None, "") and not due_date_raw:
                continue
            if work_type not in WORK_TYPE_OPTIONS:
                return None, "Select a valid job for each quoted-hours row."
            if work_type == "Other" and not other_description:
                return None, "Other quoted-hours rows require a description."

            hours = parse_float_input(str(hours_raw) if hours_raw is not None else None)
            if hours is None or hours < 0:
                return None, "Quoted hours must be a valid non-negative number."
            due_date = parse_date_input(due_date_raw)
            if due_date_raw and due_date is None:
                return None, "Job due dates must be valid dates."

            key = (work_type, other_description)
            if key in seen:
                return None, "Each quoted-hours job can only be entered once."
            seen.add(key)

            parsed.append(
                {
                    "work_type": work_type,
                    "other_description": other_description or None,
                    "label": format_work_type_label(work_type, other_description),
                    "quoted_hours": hours,
                    "due_date": due_date,
                }
            )

        return parsed, None

    def build_project_job_progress_rows(project: Project, time_entries):
        if not project.job_quotes:
            return []

        rows = []
        job_due_dates_by_label = defaultdict(set)
        for machine in project.machines:
            for job in machine.jobs:
                if job.due_date:
                    job_due_dates_by_label[get_machine_job_label(job)].add(job.due_date)

        ordered_quotes = sorted(project.job_quotes, key=lambda quote: quote.id)
        for quote in ordered_quotes:
            quoted_hours = quote.quoted_hours or 0.0
            if quoted_hours <= 0:
                continue

            label = format_work_type_label(quote.work_type, quote.other_description)
            due_dates = sorted(job_due_dates_by_label.get(label, set()))
            incurred_hours = sum(
                (entry.hours or 0.0)
                for entry in time_entries
                if (entry.work_type or "").strip() == label
            )
            pct_raw = (incurred_hours / quoted_hours * 100.0) if quoted_hours else 0.0
            pct_fill = 100.0 if pct_raw > 100 else (0.0 if pct_raw < 0 else pct_raw)

            rows.append(
                {
                    "label": label,
                    "quoted_hours": quoted_hours,
                    "incurred_hours": incurred_hours,
                    "pct_raw": pct_raw,
                    "pct_fill": pct_fill,
                    "pct_class": get_progress_bucket(pct_raw),
                    "is_complete": pct_raw >= 100.0,
                    "due_dates": due_dates,
                }
            )

        return rows

    def parse_new_project_product_lines_payload(payload_raw: str | None):
        if not payload_raw:
            return None, "At least one Product / Line is required."

        try:
            payload = json.loads(payload_raw)
        except (TypeError, ValueError):
            return None, "Invalid product/line payload."

        if not isinstance(payload, list):
            return None, "Invalid product/line payload."

        parsed_lines = []
        for line_item in payload:
            if not isinstance(line_item, dict):
                return None, "Invalid product/line payload."

            line_name = (line_item.get("product_line_name") or "").strip()
            machine_items = line_item.get("machines") or []

            if not line_name and not machine_items:
                continue
            if not line_name:
                return None, "Each machine group requires a Product / Line name."

            if not isinstance(machine_items, list):
                return None, f"Product / Line '{line_name}' has invalid machine data."

            parsed_machines = []
            for machine_item in machine_items:
                if not isinstance(machine_item, dict):
                    return None, f"Product / Line '{line_name}' has invalid machine data."

                machine_name = (machine_item.get("machine_name") or "").strip()
                if not machine_name:
                    continue

                work_types_raw = json.dumps(machine_item.get("work_types") or [])
                parsed_work_types, error = parse_work_types_payload(work_types_raw, require_one=True)
                if error:
                    return None, f"Product / Line '{line_name}', machine '{machine_name}': {error}"

                parsed_machines.append({"machine_name": machine_name, "work_types": parsed_work_types})

            parsed_lines.append({"product_line_name": line_name, "machines": parsed_machines})

        if not parsed_lines:
            return None, "At least one Product / Line is required."

        return parsed_lines, None

    def get_machine_work_type_rows(machine: Machine):
        rows = []
        for item in sorted(machine.work_types, key=lambda wt: wt.id):
            rows.append(
                {
                    "id": item.id,
                    "work_type": item.work_type,
                    "other_description": item.other_description or "",
                    "label": format_work_type_label(item.work_type, item.other_description),
                }
            )
        return rows

    def get_machine_job_label(job: MachineJob):
        return format_work_type_label(job.work_type, job.other_description)

    def get_machine_job_version_label_value(job: MachineJob | None):
        if not job:
            return "V1.0"
        version_num = getattr(job, "version_number", None) or 1
        return f"V{version_num}.0"

    def get_machine_job_version_root(job: MachineJob):
        root = job
        while getattr(root, "parent_job", None) is not None:
            root = root.parent_job
        return root

    def get_or_create_machine_job(machine: Machine, work_type: str, other_description: str | None = None):
        job = MachineJob.query.filter_by(
            machine_id=machine.id,
            work_type=work_type,
            other_description=other_description or None,
            parent_job_id=None,
        ).first()
        if job:
            return job

        job = MachineJob(
            machine_id=machine.id,
            work_type=work_type,
            other_description=other_description or None,
            status="N/S",
            version_number=1,
        )
        db.session.add(job)
        db.session.flush()
        return job

    def get_or_create_machine_job_from_label(machine: Machine, label: str | None):
        selected_label = (label or "").strip()
        if not selected_label:
            return None, "Select a valid job for the selected machine."

        for job in machine.jobs:
            if job.parent_job_id:
                continue
            if get_machine_job_label(job) == selected_label:
                return job, None

        if selected_label in WORK_TYPE_OPTIONS:
            return get_or_create_machine_job(machine, selected_label, None), None
        if selected_label.startswith("Other - "):
            other_description = selected_label.replace("Other - ", "", 1).strip()
            if other_description:
                return get_or_create_machine_job(machine, "Other", other_description), None

        return None, "Select a valid job for the selected machine."

    def resolve_machine_job_id(job_id_raw: str | None, project_id: int):
        if not job_id_raw:
            return None, None, None
        try:
            job_id_int = int(job_id_raw)
        except ValueError:
            return None, None, "Invalid machine job selection."

        job = (
            MachineJob.query.join(Machine)
            .filter(MachineJob.id == job_id_int, Machine.project_id == project_id)
            .first()
        )
        if not job:
            return None, None, "Invalid machine job selection."
        return job.id, job, None

    def get_daily_activity_project_options():
        projects = (
            Project.query
            .filter(Project.status != "Completed")
            .order_by(Project.customer.asc(), Project.na_number.asc(), Project.id.asc())
            .all()
        )
        options = []
        for project in projects:
            project_ref = project.na_number or project.edb_number or f"Project {project.id}"
            machines = []
            for machine in sorted(project.machines, key=lambda item: (item.product_line.name if item.product_line else "", item.machine_name, item.id)):
                jobs = []
                for job in sorted(machine.jobs, key=lambda item: (item.work_type or "", item.other_description or "", item.version_number or 1, item.id)):
                    jobs.append(
                        {
                            "id": job.id,
                            "label": f"{get_machine_job_version_label_value(job)} - {format_work_type_label(job.work_type, job.other_description)}",
                        }
                    )
                machines.append(
                    {
                        "id": machine.id,
                        "label": f"{machine.product_line.name if machine.product_line else 'General'} - {machine.machine_name} - {machine.version_label}",
                        "jobs": jobs,
                    }
                )
            options.append(
                {
                    "id": project.id,
                    "label": f"{project_ref} - {project.customer or 'No customer'} - {project.location or 'No location'}",
                    "machines": machines,
                }
            )
        return options

    def parse_daily_activity_entries_payload(payload_raw: str | None, log_date: date, strict: bool = False):
        if not payload_raw:
            return [], []
        try:
            payload = json.loads(payload_raw)
        except (TypeError, ValueError):
            return [], ["Invalid daily activity payload."]
        if not isinstance(payload, list):
            return [], ["Invalid daily activity payload."]

        parsed = []
        errors = []
        for index, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                errors.append(f"Row {index}: invalid row data.")
                continue

            category = (item.get("category") or "").strip()
            duration_raw = (item.get("duration_hours") or "").strip()
            start_raw = (item.get("start_time") or "").strip()
            subcategory = (item.get("subcategory") or "").strip()
            notes = (item.get("notes") or "").strip()
            project_id_raw = (item.get("project_id") or "").strip()
            machine_id_raw = (item.get("machine_id") or "").strip()
            machine_job_id_raw = (item.get("machine_job_id") or "").strip()
            adp_number = (item.get("adp_number") or "").strip()

            if not any([category, duration_raw, start_raw, subcategory, notes, project_id_raw, machine_id_raw, machine_job_id_raw, adp_number]):
                continue

            row_errors = []
            if category not in DAILY_ACTIVITY_CATEGORIES:
                row_errors.append("select a valid category")

            duration = parse_float_input(duration_raw)
            if duration is None or duration <= 0:
                row_errors.append("enter a duration greater than 0")

            start_time = parse_time_input(start_raw)
            if start_raw and start_time is None:
                row_errors.append("enter a valid start time")

            end_time = None
            if start_time and duration is not None:
                end_dt = datetime.combine(log_date, start_time) + timedelta(minutes=round(duration * 60))
                end_time = end_dt.time()

            project_id = None
            machine_id = None
            machine_job_id = None
            machine_job = None
            is_billable = category == "Project"

            if category == "Project":
                if not project_id_raw:
                    row_errors.append("select a project")
                if not machine_id_raw:
                    row_errors.append("select a machine")
                if not machine_job_id_raw:
                    row_errors.append("select a job type")
                if project_id_raw and machine_id_raw and machine_job_id_raw:
                    try:
                        project_id = int(project_id_raw)
                        machine_id = int(machine_id_raw)
                        machine_job_id = int(machine_job_id_raw)
                    except ValueError:
                        row_errors.append("select valid project, machine, and job values")
                    else:
                        machine_job = (
                            MachineJob.query.join(Machine).join(Project)
                            .filter(
                                MachineJob.id == machine_job_id,
                                MachineJob.machine_id == machine_id,
                                Machine.project_id == project_id,
                                Project.status != "Completed",
                            )
                            .first()
                        )
                        if machine_job is None:
                            row_errors.append("select a valid active project machine/job")
            elif category == "Sales Support":
                adp_number = adp_number or SALES_SUPPORT_ADP_NUMBER
                if not adp_number:
                    row_errors.append("enter an ADP number")

            if row_errors and strict:
                errors.append(f"Row {index}: {', '.join(row_errors)}.")
            elif row_errors and not strict:
                errors.append(f"Row {index}: {', '.join(row_errors)}.")

            parsed.append(
                {
                    "entry_order": len(parsed) + 1,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration_hours": duration or 0.0,
                    "category": category if category in DAILY_ACTIVITY_CATEGORIES else "",
                    "project_id": project_id,
                    "machine_id": machine_id,
                    "machine_job_id": machine_job_id,
                    "machine_job": machine_job,
                    "subcategory": subcategory or None,
                    "adp_number": adp_number or None,
                    "notes": notes or None,
                    "is_billable": is_billable,
                }
            )

        return parsed, errors

    def save_daily_activity_entries(log: DailyActivityLog, parsed_entries):
        for entry in list(log.entries):
            db.session.delete(entry)
        db.session.flush()
        for item in parsed_entries:
            db.session.add(
                DailyActivityEntry(
                    daily_log_id=log.id,
                    entry_order=item["entry_order"],
                    start_time=item["start_time"],
                    end_time=item["end_time"],
                    duration_hours=item["duration_hours"],
                    category=item["category"],
                    project_id=item["project_id"],
                    machine_id=item["machine_id"],
                    machine_job_id=item["machine_job_id"],
                    subcategory=item["subcategory"],
                    adp_number=item["adp_number"],
                    notes=item["notes"],
                    is_billable=item["is_billable"],
                )
            )
        log.total_hours = sum(item["duration_hours"] for item in parsed_entries)
        log.updated_at = datetime.utcnow()

    def update_project_incurred_total(project_id: int):
        project = Project.query.get(project_id)
        if not project:
            return
        total = sum(entry.hours or 0.0 for entry in TimeEntry.query.filter_by(project_id=project_id).all())
        project.incurred_hours_total = total

    def machine_job_has_history(job: MachineJob):
        if getattr(job, "versions", None):
            if len(job.versions) > 0:
                return True
        if TimeEntry.query.filter_by(machine_job_id=job.id).count() > 0:
            return True
        if (job.quoted_hours or 0.0) > 0:
            return True
        if (job.incurred_hours or 0.0) > 0:
            return True
        if job.status and job.status != "N/S":
            return True
        if job.due_date:
            return True
        return any(
            getattr(job, item["field"]) or getattr(job, item["na_field"], False)
            for item in MACHINE_MILESTONE_DEFINITIONS
        )

    def sync_machine_jobs_from_work_types(machine: Machine, parsed_work_types):
        desired_keys = {
            (wt["work_type"], wt["other_description"] or None)
            for wt in parsed_work_types
        }

        base_jobs = [job for job in machine.jobs if not job.parent_job_id]

        for job in list(base_jobs):
            key = (job.work_type, job.other_description or None)
            if key in desired_keys:
                continue
            if machine_job_has_history(job):
                return f"Cannot remove {get_machine_job_label(job)} because it already has time entries, status, hours, due date, or milestone dates."
            db.session.delete(job)

        existing_keys = {
            (job.work_type, job.other_description or None)
            for job in base_jobs
        }
        for wt in parsed_work_types:
            key = (wt["work_type"], wt["other_description"] or None)
            if key not in existing_keys:
                get_or_create_machine_job(machine, wt["work_type"], wt["other_description"])

        return None

    def resolve_machine_id(machine_id_raw: str | None, project_id: int):
        if not machine_id_raw:
            return None, None
        try:
            machine_id_int = int(machine_id_raw)
        except ValueError:
            return None, "Invalid machine selection."
        machine = Machine.query.filter_by(id=machine_id_int, project_id=project_id).first()
        if not machine:
            return None, "Invalid machine selection."
        return machine.id, None

    def resolve_product_line_id(product_line_id_raw: str | None, project_id: int):
        if not product_line_id_raw:
            return None, "Select a valid Product / Line."
        try:
            product_line_id_int = int(product_line_id_raw)
        except ValueError:
            return None, "Select a valid Product / Line."
        product_line = ProductLine.query.filter_by(id=product_line_id_int, project_id=project_id).first()
        if not product_line:
            return None, "Select a valid Product / Line."
        return product_line.id, None

    def validate_and_sync_machine_work_type(machine: Machine, work_type: str | None):
        selected_work_type = (work_type or "").strip()
        if not selected_work_type:
            return "Select a valid work type for the selected machine."

        configured_labels = [item["label"] for item in get_machine_work_type_rows(machine)]
        if configured_labels:
            if selected_work_type not in configured_labels:
                return "Select a valid work type for the selected machine."
            return None

        if selected_work_type not in WORK_TYPE_OPTIONS:
            return "Select a valid work type for the selected machine."

        existing = MachineWorkType.query.filter_by(
            machine_id=machine.id,
            work_type=selected_work_type,
            other_description=None,
        ).first()
        if not existing:
            db.session.add(
                MachineWorkType(
                    machine_id=machine.id,
                    work_type=selected_work_type,
                    other_description=None,
                )
            )
        return None

    def compute_machine_stats(machines, time_entries):
        machine_hours = {machine.id: 0.0 for machine in machines}
        machine_entry_counts = {machine.id: 0 for machine in machines}
        for entry in time_entries:
            if entry.machine_id in machine_hours:
                machine_hours[entry.machine_id] += entry.hours or 0.0
                machine_entry_counts[entry.machine_id] += 1
        return machine_hours, machine_entry_counts

    def compute_machine_job_stats(machine_jobs, time_entries):
        job_hours = {job.id: 0.0 for job in machine_jobs}
        job_entry_counts = {job.id: 0 for job in machine_jobs}
        for entry in time_entries:
            if entry.machine_job_id in job_hours:
                job_hours[entry.machine_job_id] += entry.hours or 0.0
                job_entry_counts[entry.machine_job_id] += 1
        for job in machine_jobs:
            if job_entry_counts.get(job.id, 0) == 0 and (job.incurred_hours or 0.0) > 0:
                job_hours[job.id] = job.incurred_hours or 0.0
        return job_hours, job_entry_counts

    def get_machine_job_milestone_view(machine_jobs):
        milestone_values = {}
        row_complete = {}

        for job in machine_jobs:
            per_job = {}
            all_handled = True
            for item in MACHINE_MILESTONE_DEFINITIONS:
                milestone_date = getattr(job, item["field"])
                is_na = bool(getattr(job, item["na_field"], False))
                is_handled = bool(milestone_date or is_na)
                all_handled = all_handled and is_handled
                per_job[item["key"]] = {
                    "date": milestone_date,
                    "is_na": is_na,
                    "is_handled": is_handled,
                    "is_missing": job.status == "Completed" and not is_handled,
                }
            milestone_values[job.id] = per_job
            row_complete[job.id] = job.status == "Completed" and all_handled

        return milestone_values, row_complete

    def get_machine_milestone_view(machines):
        milestone_values = {}
        row_complete = {}

        for machine in machines:
            per_machine = {}
            for item in MACHINE_MILESTONE_DEFINITIONS:
                per_machine[item["key"]] = getattr(machine, item["field"])
            milestone_values[machine.id] = per_machine
            row_complete[machine.id] = machine.status == "Completed"

        return milestone_values, row_complete

    def project_machine_job_anchor(project_id, job_id, highlight: str | None = None):
        scroll_y = (request.form.get("scroll_y") or "").strip()
        params = []
        if scroll_y.isdigit():
            params.append(f"scroll_y={quote(scroll_y)}")
        if highlight:
            params.append(f"highlight={quote(highlight)}")
        restore_param = f"?{'&'.join(params)}" if params else ""
        return url_for("project_detail", project_id=project_id) + restore_param + f"#machine-job-{job_id}"

    def subtract_deleted_machine_job_quote(project: Project, job: MachineJob):
        if job.parent_job_id:
            return 0.0

        matching_quote = ProjectJobQuote.query.filter_by(
            project_id=project.id,
            work_type=job.work_type,
            other_description=job.other_description,
        ).first()
        if not matching_quote:
            return 0.0

        matching_base_job_count = (
            MachineJob.query.join(Machine)
            .filter(
                Machine.project_id == project.id,
                MachineJob.parent_job_id.is_(None),
                MachineJob.work_type == job.work_type,
                MachineJob.other_description == job.other_description,
            )
            .count()
        )
        if matching_base_job_count <= 0:
            return 0.0

        hours_to_subtract = (matching_quote.quoted_hours or 0.0) / matching_base_job_count
        matching_quote.quoted_hours = max((matching_quote.quoted_hours or 0.0) - hours_to_subtract, 0.0)

        if matching_quote.quoted_hours <= 0:
            db.session.delete(matching_quote)

        project.quoted_hours_total = max((project.quoted_hours_total or 0.0) - hours_to_subtract, 0.0)
        return hours_to_subtract

    def get_machine_version_root(machine: Machine):
        return machine.parent_machine_id or machine.id

    def machine_version_is_copy_ready(machine: Machine, machine_jobs_for_machine, machine_job_row_complete_map, machine_job_milestones_map):
        if not machine_jobs_for_machine:
            return False
        return any(machine_job_row_complete_map.get(job.id) for job in machine_jobs_for_machine)

    def build_machine_version_groups(product_lines, machines, machine_jobs, machine_job_row_complete_map, machine_job_milestones_map):
        machines_by_id = {machine.id: machine for machine in machines}
        versions_by_root = defaultdict(list)
        roots_by_id = {}

        for machine in machines:
            root_id = get_machine_version_root(machine)
            root_machine = machines_by_id.get(root_id)
            if root_machine is None:
                root_machine = machine
                root_id = machine.id
                machine.parent_machine_id = None
            roots_by_id[root_id] = root_machine
            versions_by_root[root_id].append(machine)

        for version_list in versions_by_root.values():
            version_list.sort(key=lambda item: ((item.version_number or 1), item.id), reverse=True)

        machine_jobs_by_machine = defaultdict(list)
        for job in machine_jobs:
            machine_jobs_by_machine[job.machine_id].append(job)

        family_map = defaultdict(list)
        for line in product_lines:
            line_families = []
            line_machines = [machine for machine in machines if machine.product_line_id == line.id and machine.parent_machine_id is None]
            line_machines.sort(key=lambda item: (item.id,))
            for root_machine in line_machines:
                versions = versions_by_root.get(root_machine.id, [root_machine])
                version_blocks = []
                for version_machine in versions:
                    version_jobs = machine_jobs_by_machine.get(version_machine.id, [])
                    version_blocks.append(
                        {
                            "machine": version_machine,
                            "jobs": version_jobs,
                            "is_ready_for_copy": machine_version_is_copy_ready(
                                version_machine,
                                version_jobs,
                                machine_job_row_complete_map,
                                machine_job_milestones_map,
                            ),
                            "has_next_version": any(
                                child.version_number == ((version_machine.version_number or 1) + 1)
                                for child in versions
                            ),
                        }
                    )
                line_families.append(
                    {
                        "root_machine": root_machine,
                        "versions": version_blocks,
                    }
                )
            family_map[line.id] = line_families

        return family_map


    def linkify_comment_text(comment_text: str):
        # Match Windows absolute paths like C:\Folder\Subfolder\File
        path_pattern = re.compile(r"[A-Za-z]:\\[^\r\n]+")
        parts = []
        last_end = 0

        for match in path_pattern.finditer(comment_text or ""):
            start, end = match.span()
            if start > last_end:
                parts.append(escape(comment_text[last_end:start]))

            raw_path = match.group(0)
            open_href = url_for("open_path") + "?target=" + quote(raw_path, safe="")
            link = Markup(f'<a href="{open_href}">{escape(raw_path)}</a>')
            parts.append(link)
            last_end = end

        if last_end < len(comment_text or ""):
            parts.append(escape((comment_text or "")[last_end:]))

        if not parts:
            return escape(comment_text or "")

        return Markup("".join(str(p) for p in parts))
    def get_csrf_token():
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_hex(16)
            session["_csrf_token"] = token
        return token

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": get_csrf_token}

    @app.before_request
    def verify_csrf():
        if request.method == "POST":
            # Skip CSRF verification for admin API endpoints with JSON data
            if request.path.startswith('/admin/') and request.is_json:
                return None
                
            expected = session.get("_csrf_token")
            received = request.form.get("_csrf_token")
            if not expected or expected != received:
                flash("Invalid form token. Please try again.", "error")
                return redirect(request.referrer or url_for("dashboard"))

    @app.route("/")
    def dashboard():
        status_filter = request.args.get("status", type=str)
        query = Project.query
        
        # Default to "Ongoing" if no status filter is provided
        if not status_filter:
            status_filter = "Ongoing"
        
        if status_filter and status_filter in ALLOWED_STATUSES:
            query = query.filter_by(status=status_filter)

        completion_bucket = case((Project.status == "Completed", 1), else_=0)

        projects = query.order_by(
            completion_bucket.asc(),  # keeps Completed at bottom
            case(
                (Project.status == "Completed", Project.due_date),
                else_=Project.id
            ).desc()  # ← apply DESC to the whole CASE result
        ).all()

        for project in projects:
            project_time_entries = list(project.time_entries)
            total_incurred = sum(te.hours or 0.0 for te in project_time_entries)
            project.incurred_hours_total = total_incurred
            project.job_progress_rows = build_project_job_progress_rows(project, project_time_entries)

        return render_template("dashboard.html", projects=projects, status_filter=status_filter)
    @app.route("/open-path")
    def open_path():
        target = request.args.get("target", type=str) or ""

        # Only allow local absolute Windows-style paths like C:\...
        if not re.match(r"^[A-Za-z]:\\", target):
            flash("Invalid local path format.", "error")
            return redirect(request.referrer or url_for("dashboard"))

        if not os.path.exists(target):
            flash("Path does not exist on this machine.", "error")
            return redirect(request.referrer or url_for("dashboard"))

        try:
            subprocess.Popen(["explorer", target])
            flash("Opened path in Explorer.", "success")
        except Exception:
            flash("Failed to open path.", "error")

        return redirect(request.referrer or url_for("dashboard"))

    @app.route("/daily-activity")
    def daily_activity():
        selected_date = parse_date_input(request.args.get("date")) or date.today()
        log = DailyActivityLog.query.filter_by(date=selected_date).first()
        entries = []
        if log:
            for entry in log.entries:
                entries.append(
                    {
                        "start_time": entry.start_time.strftime("%H:%M") if entry.start_time else "",
                        "end_time": entry.end_time.strftime("%H:%M") if entry.end_time else "",
                        "duration_hours": entry.duration_hours or 0.0,
                        "category": entry.category or "",
                        "project_id": entry.project_id or "",
                        "machine_id": entry.machine_id or "",
                        "machine_job_id": entry.machine_job_id or "",
                        "subcategory": entry.subcategory or "",
                        "adp_number": entry.adp_number or "",
                        "notes": entry.notes or "",
                    }
                )

        return render_template(
            "daily_activity.html",
            selected_date=selected_date,
            week_start=get_week_start(selected_date),
            log=log,
            entries=entries,
            categories=DAILY_ACTIVITY_CATEGORIES,
            sales_support_adp_number=SALES_SUPPORT_ADP_NUMBER,
            project_options=get_daily_activity_project_options(),
        )

    @app.route("/daily-activity/save", methods=["POST"])
    def save_daily_activity():
        selected_date = parse_date_input(request.form.get("date")) or date.today()
        parsed_entries, errors = parse_daily_activity_entries_payload(
            request.form.get("entries_payload"),
            selected_date,
            strict=False,
        )
        if errors:
            for error in errors:
                flash(error, "error")
            return redirect(url_for("daily_activity", date=selected_date.isoformat()))

        log = DailyActivityLog.query.filter_by(date=selected_date).first()
        if not log:
            log = DailyActivityLog(date=selected_date, status="Draft")
            db.session.add(log)
            db.session.flush()
        elif log.status == "Submitted":
            log.status = "Needs Review"

        save_daily_activity_entries(log, parsed_entries)
        db.session.commit()
        flash("Daily activity draft saved.", "success")
        return redirect(url_for("daily_activity", date=selected_date.isoformat()))

    @app.route("/daily-activity/clear", methods=["POST"])
    def clear_daily_activity():
        selected_date = parse_date_input(request.form.get("date")) or date.today()
        log = DailyActivityLog.query.filter_by(date=selected_date).first()
        affected_project_ids = set()
        if log:
            for posting in list(log.postings):
                affected_project_ids.add(posting.project_id)
                if posting.time_entry:
                    db.session.delete(posting.time_entry)
                db.session.delete(posting)
            for entry in list(log.entries):
                db.session.delete(entry)
            log.status = "Draft"
            log.total_hours = 0.0
            log.updated_at = datetime.utcnow()
            log.posted_at = None
            for project_id in affected_project_ids:
                update_project_incurred_total(project_id)
            db.session.commit()
            flash("Daily activity cleared.", "success")
        return redirect(url_for("daily_activity", date=selected_date.isoformat()))

    @app.route("/daily-activity/week")
    def daily_activity_week():
        selected_date = parse_date_input(request.args.get("date")) or date.today()
        week_start = get_week_start(selected_date)
        week_end = week_start + timedelta(days=6)
        logs = (
            DailyActivityLog.query
            .filter(DailyActivityLog.date >= week_start, DailyActivityLog.date <= week_end)
            .order_by(DailyActivityLog.date.asc())
            .all()
        )
        logs_by_date = {log.date: log for log in logs}
        week_days = [week_start + timedelta(days=offset) for offset in range(7)]

        category_totals = defaultdict(float)
        project_totals = defaultdict(float)
        grand_total = 0.0
        for log in logs:
            for entry in log.entries:
                hours = entry.duration_hours or 0.0
                grand_total += hours
                category_totals[entry.category or "Uncategorized"] += hours
                if entry.project:
                    project_totals[entry.project.na_number or entry.project.edb_number or f"Project {entry.project_id}"] += hours

        return render_template(
            "daily_activity_week.html",
            week_start=week_start,
            week_end=week_end,
            week_days=week_days,
            logs_by_date=logs_by_date,
            category_totals=dict(sorted(category_totals.items())),
            project_totals=dict(sorted(project_totals.items())),
            grand_total=grand_total,
        )

    @app.route("/daily-activity/week/submit", methods=["POST"])
    def submit_daily_activity_week():
        week_start = parse_date_input(request.form.get("week_start")) or get_week_start(date.today())
        week_end = week_start + timedelta(days=6)
        logs = (
            DailyActivityLog.query
            .filter(DailyActivityLog.date >= week_start, DailyActivityLog.date <= week_end)
            .order_by(DailyActivityLog.date.asc())
            .all()
        )
        errors = []
        affected_project_ids = set()

        for log in logs:
            payload = []
            for entry in log.entries:
                payload.append(
                    {
                        "start_time": entry.start_time.strftime("%H:%M") if entry.start_time else "",
                        "duration_hours": str(entry.duration_hours or ""),
                        "category": entry.category or "",
                        "project_id": str(entry.project_id or ""),
                        "machine_id": str(entry.machine_id or ""),
                        "machine_job_id": str(entry.machine_job_id or ""),
                        "subcategory": entry.subcategory or "",
                        "adp_number": entry.adp_number or "",
                        "notes": entry.notes or "",
                    }
                )
            _, row_errors = parse_daily_activity_entries_payload(json.dumps(payload), log.date, strict=True)
            errors.extend([f"{log.date.isoformat()}: {error}" for error in row_errors])

        if errors:
            for error in errors:
                flash(error, "error")
            return redirect(url_for("daily_activity_week", date=week_start.isoformat()))

        for log in logs:
            grouped = {}
            for entry in log.entries:
                if entry.category != "Project":
                    continue
                key = (entry.project_id, entry.machine_id, entry.machine_job_id)
                if key not in grouped:
                    grouped[key] = {"hours": 0.0, "notes": [], "job": entry.machine_job}
                grouped[key]["hours"] += entry.duration_hours or 0.0
                grouped[key]["notes"].append(combine_notes([entry.subcategory, entry.notes]))

            existing_postings = {
                (posting.project_id, posting.machine_id, posting.machine_job_id): posting
                for posting in log.postings
            }

            for key, posting in list(existing_postings.items()):
                if key in grouped:
                    continue
                affected_project_ids.add(posting.project_id)
                if posting.time_entry:
                    db.session.delete(posting.time_entry)
                db.session.delete(posting)

            for (project_id, machine_id, machine_job_id), grouped_item in grouped.items():
                affected_project_ids.add(project_id)
                job = grouped_item["job"] or MachineJob.query.get(machine_job_id)
                notes_summary = combine_notes(grouped_item["notes"])
                posting = existing_postings.get((project_id, machine_id, machine_job_id))
                if posting and posting.time_entry:
                    time_entry = posting.time_entry
                    time_entry.date = log.date
                    time_entry.machine_id = machine_id
                    time_entry.machine_job_id = machine_job_id
                    time_entry.work_type = get_machine_job_label(job) if job else ""
                    time_entry.hours = grouped_item["hours"]
                    time_entry.notes = notes_summary
                else:
                    time_entry = TimeEntry(
                        project_id=project_id,
                        machine_id=machine_id,
                        machine_job_id=machine_job_id,
                        date=log.date,
                        work_type=get_machine_job_label(job) if job else "",
                        hours=grouped_item["hours"],
                        notes=notes_summary,
                    )
                    db.session.add(time_entry)
                    db.session.flush()
                    posting = DailyActivityPosting(
                        daily_log_id=log.id,
                        project_id=project_id,
                        machine_id=machine_id,
                        machine_job_id=machine_job_id,
                        category="Project",
                        time_entry_id=time_entry.id,
                    )
                    db.session.add(posting)

                posting.duration_hours = grouped_item["hours"]
                posting.notes_summary = notes_summary
                posting.posted_at = datetime.utcnow()

            log.status = "Submitted"
            log.posted_at = datetime.utcnow()
            log.updated_at = datetime.utcnow()

        for project_id in affected_project_ids:
            update_project_incurred_total(project_id)

        db.session.commit()
        flash("Weekly project hours submitted.", "success")
        return redirect(url_for("daily_activity_week", date=week_start.isoformat()))

    @app.route("/projects/new", methods=["GET", "POST"])
    def new_project():
        if request.method == "POST":
            customer = request.form.get("customer")
            project_manager = request.form.get("project_manager")
            location = request.form.get("location")
            na_number = request.form.get("na_number")
            edb_number = request.form.get("edb_number")
            status = request.form.get("status") or "N/S"
            quoted_hours_total = request.form.get("quoted_hours_total") or "0"
            product_lines_payload = request.form.get("product_lines_payload")
            job_quotes_payload = request.form.get("job_quotes_payload")

            if not customer:
                flash("Customer is required.", "error")
                return redirect(url_for("new_project"))

            job_quotes, job_quotes_error = parse_job_quotes_payload(job_quotes_payload)
            if job_quotes_error:
                flash(job_quotes_error, "error")
                return redirect(url_for("new_project"))
            due_dates = [quote["due_date"] for quote in job_quotes if quote["due_date"]]
            due_date = max(due_dates) if due_dates else None
            due_dates_by_job_key = {
                (quote["work_type"], quote["other_description"]): quote["due_date"]
                for quote in job_quotes
            }

            quoted_hours = sum(item["quoted_hours"] for item in job_quotes)
            if not job_quotes:
                quoted_hours = parse_float_input(quoted_hours_total)
                if quoted_hours is None:
                    flash("Quoted hours must be a valid number.", "error")
                    return redirect(url_for("new_project"))

            product_line_specs, product_line_error = parse_new_project_product_lines_payload(product_lines_payload)
            if product_line_error:
                flash(product_line_error, "error")
                return redirect(url_for("new_project"))

            project = Project(
                customer=customer,
                project_manager=project_manager,
                location=location,
                product_line=product_line_specs[0]["product_line_name"] if product_line_specs else None,
                na_number=na_number,
                edb_number=edb_number,
                due_date=due_date,
                status=status,
                quoted_hours_total=quoted_hours,
            )
            db.session.add(project)
            db.session.flush()

            for quote in job_quotes:
                db.session.add(
                    ProjectJobQuote(
                        project_id=project.id,
                        work_type=quote["work_type"],
                        other_description=quote["other_description"],
                        quoted_hours=quote["quoted_hours"],
                        due_date=quote["due_date"],
                    )
                )

            for line_spec in product_line_specs:
                product_line_item = ProductLine(project_id=project.id, name=line_spec["product_line_name"])
                db.session.add(product_line_item)
                db.session.flush()

                for machine_spec in line_spec["machines"]:
                    machine = Machine(
                        project_id=project.id,
                        product_line_id=product_line_item.id,
                        machine_name=machine_spec["machine_name"],
                        status="N/S",
                    )
                    db.session.add(machine)
                    db.session.flush()

                    for wt in machine_spec["work_types"]:
                        db.session.add(
                            MachineWorkType(
                                machine_id=machine.id,
                                work_type=wt["work_type"],
                                other_description=wt["other_description"],
                            )
                        )
                        job = get_or_create_machine_job(machine, wt["work_type"], wt["other_description"])
                        job.due_date = due_dates_by_job_key.get((wt["work_type"], wt["other_description"]))

            db.session.commit()

            flash("Project created.", "success")
            return redirect(url_for("project_detail", project_id=project.id))

        return render_template("project_form.html", work_type_options=WORK_TYPE_OPTIONS)

    @app.route("/projects/<int:project_id>")
    def project_detail(project_id):
        project = Project.query.get_or_404(project_id)
        product_lines = ProductLine.query.filter_by(project_id=project.id).order_by(ProductLine.id.asc()).all()
        created_default_line = False
        if not product_lines:
            general_line = ProductLine(project_id=project.id, name="General")
            db.session.add(general_line)
            db.session.flush()
            product_lines = [general_line]
            created_default_line = True

        machines = Machine.query.filter_by(project_id=project.id).order_by(Machine.id.asc()).all()
        updated_missing_machine_lines = False
        fallback_line = product_lines[0] if product_lines else None
        if fallback_line:
            for machine in machines:
                if machine.product_line_id is None:
                    machine.product_line_id = fallback_line.id
                    updated_missing_machine_lines = True
        if created_default_line or updated_missing_machine_lines:
            db.session.commit()
            machines = Machine.query.filter_by(project_id=project.id).order_by(Machine.id.asc()).all()
            product_lines = ProductLine.query.filter_by(project_id=project.id).order_by(ProductLine.id.asc()).all()

        time_entries = (
            TimeEntry.query.filter_by(project_id=project.id)
            .order_by(TimeEntry.date.desc(), TimeEntry.id.desc())
            .all()
        )
        comments = (
            Comment.query.filter_by(project_id=project.id)
            .order_by(Comment.created_at.desc(), Comment.id.desc())
            .all()
        )

        for item in comments:
            item.comment_html = linkify_comment_text(item.comment or "")

        total_incurred = sum(te.hours for te in time_entries)
        project.incurred_hours_total = total_incurred
        machine_hours, machine_entry_counts = compute_machine_stats(machines, time_entries)
        machine_milestones, machine_row_complete = get_machine_milestone_view(machines)
        machine_jobs = list(
            MachineJob.query.join(Machine)
            .filter(Machine.project_id == project.id)
            .all()
        )
        machine_jobs.sort(
            key=lambda job: (
                job.machine.product_line_id or 0,
                job.machine_id,
                job.work_type or "",
                job.other_description or "",
                job.version_number or 1,
                job.id,
            )
        )
        machine_job_hours, machine_job_entry_counts = compute_machine_job_stats(machine_jobs, time_entries)
        machine_job_milestones, machine_job_row_complete = get_machine_job_milestone_view(machine_jobs)
        machine_version_groups = build_machine_version_groups(
            product_lines,
            machines,
            machine_jobs,
            machine_job_row_complete,  # row complete map
            machine_job_milestones  # milestones map
        )
        machine_jobs_by_machine_id = defaultdict(list)
        machine_jobs_by_id = {}
        for job in machine_jobs:
            machine_jobs_by_machine_id[job.machine_id].append(job)
            machine_jobs_by_id[job.id] = job
        machine_job_display_labels = {
            job.id: f"{get_machine_job_version_label_value(job)} - {job.machine.product_line.name if job.machine.product_line else 'General'} - {job.machine.machine_name} - {get_machine_job_label(job)}"
            for job in machine_jobs
        }
        machine_job_work_labels = {job.id: get_machine_job_label(job) for job in machine_jobs}

        project_job_quote_hours = {
            format_work_type_label(quote.work_type, quote.other_description): quote.quoted_hours or 0.0
            for quote in project.job_quotes
        }
        machine_job_groups = []
        machine_work_type_rows = {}
        machine_work_type_choices = {}
        machine_work_type_hours = {}
        machine_display_labels = {}
        machine_groups = []
        machine_job_version_children_map = defaultdict(list)
        machine_job_version_family_map = defaultdict(list)
        for job in machine_jobs:
            root_job = get_machine_job_version_root(job)
            machine_job_version_family_map[root_job.id].append(job)
            if job.parent_job_id:
                machine_job_version_children_map[job.parent_job_id].append(job)

        for family_jobs in machine_job_version_family_map.values():
            family_jobs.sort(key=lambda item: ((item.version_number or 1), item.id))

        base_job_label_counts = {}
        for job in machine_jobs:
            if job.parent_job_id:
                continue
            label = machine_job_work_labels[job.id]
            base_job_label_counts[label] = base_job_label_counts.get(label, 0) + 1

        base_job_quote_hours = {
            label: (
                project_job_quote_hours.get(label, 0.0) / base_job_label_counts[label]
                if base_job_label_counts.get(label) else 0.0
            )
            for label in base_job_label_counts
        }

        machine_job_quote_hours = {}
        for job in machine_jobs:
            root_job = get_machine_job_version_root(job)
            root_label = machine_job_work_labels.get(root_job.id, get_machine_job_label(root_job))
            machine_job_quote_hours[job.id] = (
                job.quoted_hours
                if (job.quoted_hours or 0.0) > 0
                else base_job_quote_hours.get(root_label, 0.0)
            )

        for machine in machines:
            work_type_rows = get_machine_work_type_rows(machine)
            machine_work_type_rows[machine.id] = work_type_rows

            labels = [item["label"] for item in work_type_rows]
            machine_work_type_choices[machine.id] = labels
            product_line_name = machine.product_line.name if machine.product_line else "General"
            machine_display_labels[machine.id] = f"{get_machine_version_label_value(machine)} - {product_line_name} - {machine.machine_name}"

            hours_by_label = []
            for label in labels:
                total_hours = sum(
                    (entry.hours or 0.0)
                    for entry in time_entries
                    if entry.machine_id == machine.id and (entry.work_type or "") == label
                )
                hours_by_label.append({"label": label, "hours": total_hours})

            extra_labels = []
            for entry in time_entries:
                if entry.machine_id != machine.id:
                    continue
                entry_label = (entry.work_type or "").strip()
                if not entry_label or entry_label in labels or entry_label in extra_labels:
                    continue
                extra_labels.append(entry_label)

            for label in extra_labels:
                total_hours = sum(
                    (entry.hours or 0.0)
                    for entry in time_entries
                    if entry.machine_id == machine.id and (entry.work_type or "") == label
                )
                hours_by_label.append({"label": label, "hours": total_hours})

            machine_work_type_hours[machine.id] = hours_by_label

        for line in product_lines:
            line_root_machines = [
                machine for machine in machines
                if machine.product_line_id == line.id and machine.parent_machine_id is None
            ]
            line_root_machines.sort(key=lambda item: item.id)
            machine_groups.append({"product_line": line, "machines": line_root_machines})

        edit_machine_id = request.args.get("edit_machine", type=int)
        if edit_machine_id and not any(machine.id == edit_machine_id for machine in machines):
            edit_machine_id = None
        edit_machine_job_id = request.args.get("edit_job", type=int)
        if (
            edit_machine_job_id
            and (
                edit_machine_job_id not in machine_jobs_by_id
                or machine_jobs_by_id[edit_machine_job_id].machine_id != edit_machine_id
            )
        ):
            edit_machine_job_id = None

        edit_time_entry_id = request.args.get("edit_time_entry", type=int)
        if edit_time_entry_id and not any(entry.id == edit_time_entry_id for entry in time_entries):
            edit_time_entry_id = None

        edit_comment_id = request.args.get("edit_comment", type=int)
        if edit_comment_id and not any(item.id == edit_comment_id for item in comments):
            edit_comment_id = None

        return render_template(
            "project_detail.html",
            project=project,
            product_lines=product_lines,
            machine_groups=machine_groups,
            machines=machines,
            machine_jobs=machine_jobs,
            machine_job_groups=machine_job_groups,
            machine_display_labels=machine_display_labels,
            machine_job_display_labels=machine_job_display_labels,
            machine_job_work_labels=machine_job_work_labels,
            project_job_quote_hours=project_job_quote_hours,
            machine_job_quote_hours=machine_job_quote_hours,
            time_entries=time_entries,
            comments=comments,
            machine_hours=machine_hours,
            machine_entry_counts=machine_entry_counts,
            machine_milestones=machine_milestones,
            machine_row_complete=machine_row_complete,
            machine_job_hours=machine_job_hours,
            machine_job_entry_counts=machine_job_entry_counts,
            machine_job_milestones=machine_job_milestones,
            machine_job_row_complete=machine_job_row_complete,
            machine_jobs_by_machine_id=machine_jobs_by_machine_id,
            machine_jobs_by_id=machine_jobs_by_id,
            machine_job_version_family_map=machine_job_version_family_map,
            machine_job_version_children_map=machine_job_version_children_map,
            machine_work_type_rows=machine_work_type_rows,
            machine_work_type_choices=machine_work_type_choices,
            machine_work_type_hours=machine_work_type_hours,
            machine_version_groups=machine_version_groups,
            machine_status_options=MACHINE_STATUS_OPTIONS,
            work_type_options=WORK_TYPE_OPTIONS,
            milestone_definitions=MACHINE_MILESTONE_DEFINITIONS,
            edit_machine_id=edit_machine_id,
            edit_machine_job_id=edit_machine_job_id,
            edit_time_entry_id=edit_time_entry_id,
            edit_comment_id=edit_comment_id,
        )

    @app.route("/projects/<int:project_id>/delete", methods=["POST"])
    def delete_project(project_id):
        project = Project.query.get_or_404(project_id)
        db.session.delete(project)
        db.session.commit()

        flash("Project deleted successfully.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/projects/<int:project_id>/machines", methods=["POST"])
    def add_machine(project_id):
        project = Project.query.get_or_404(project_id)
        machine_name = (request.form.get("machine_name") or "").strip()
        product_line_id_raw = request.form.get("product_line_id")
        new_product_line_name = (request.form.get("new_product_line") or "").strip()
        
        # Get work types from form
        work_types = request.form.getlist("work_types")
        other_descriptions = request.form.getlist("other_description")
        
        # Get work types payload (for copying from existing machines)
        work_types_payload_raw = request.form.get("work_types_payload")

        if not machine_name:
            flash("Machine / Asset # cannot be empty.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#machines")

        # Handle product/line assignment
        product_line_id_value = None
        product_line_error = None

        if new_product_line_name:
            # Create new product/line
            new_product_line = ProductLine(project_id=project.id, name=new_product_line_name)
            db.session.add(new_product_line)
            db.session.flush()  # Get the ID
            product_line_id_value = new_product_line.id
        elif product_line_id_raw:
            # Use existing product/line
            product_line_id_value, product_line_error = resolve_product_line_id(product_line_id_raw, project.id)
        else:
            # Use default 'General' product/line
            general_line = ProductLine.query.filter_by(project_id=project.id, name="General").first()
            if not general_line:
                general_line = ProductLine(project_id=project.id, name="General")
                db.session.add(general_line)
                db.session.flush()
            product_line_id_value = general_line.id

        if product_line_error:
            flash(product_line_error, "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#machines")

        # Parse work types payload first (for copying)
        parsed_work_types, work_types_error = parse_work_types_payload(work_types_payload_raw, require_one=False)
        if work_types_error:
            flash(work_types_error, "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#machines")

        # If no work types from payload, try form fields
        if not parsed_work_types:
            for i, work_type in enumerate(work_types):
                work_type = work_type.strip()
                if not work_type:
                    continue
                    
                if work_type not in WORK_TYPE_OPTIONS:
                    flash(f"Invalid work type: {work_type}", "error")
                    return redirect(url_for("project_detail", project_id=project.id) + "#machines")
                    
                other_description = other_descriptions[i] if i < len(other_descriptions) else ""
                if work_type == "Other" and not other_description.strip():
                    flash("Other work type requires a description.", "error")
                    return redirect(url_for("project_detail", project_id=project.id) + "#machines")
                    
                parsed_work_types.append({
                    "work_type": work_type,
                    "other_description": other_description.strip() if other_description else None,
                    "label": format_work_type_label(work_type, other_description)
                })

        # If still no work types, add a default "RA" work type
        if not parsed_work_types:
            parsed_work_types.append({
                "work_type": "RA",
                "other_description": None,
                "label": "RA"
            })

        machine = Machine(
            project_id=project.id,
            product_line_id=product_line_id_value,
            machine_name=machine_name,
            status="N/S",
            version_number=1,
            version="V1.0",
        )
        db.session.add(machine)
        db.session.flush()
        audit_change(
            project.id,
            "machine_created",
            machine_id=machine.id,
            note=f"Created machine {machine.machine_name}",
        )

        # Add work types
        for wt in parsed_work_types:
            db.session.add(
                MachineWorkType(
                    machine_id=machine.id,
                    work_type=wt["work_type"],
                    other_description=wt["other_description"],
                )
            )
            job = get_or_create_machine_job(machine, wt["work_type"], wt["other_description"])
            job.quoted_hours = wt.get("quoted_hours") or 0.0
            job.due_date = wt.get("due_date")
            audit_change(
                project.id,
                "job_created",
                machine_id=machine.id,
                machine_job_id=job.id,
                version_number=job.version_number,
                note=f"Added {get_machine_job_label(job)} to {machine.machine_name}",
            )

        recalculate_project_quoted_hours(project)

        db.session.commit()

        flash("Machine / Asset # added with work types.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#machines")

    @app.route("/projects/<int:project_id>/machines/<int:machine_id>/update", methods=["POST"])
    def update_machine(project_id, machine_id):
        project = Project.query.get_or_404(project_id)
        machine = Machine.query.filter_by(id=machine_id, project_id=project.id).first_or_404()

        machine_name = (request.form.get("machine_name") or "").strip()
        product_line_id_raw = request.form.get("product_line_id")
        status = request.form.get("status")
        quoted_hours_raw = request.form.get("quoted_hours")
        job_due_date_raw = request.form.get("job_due_date")
        incurred_hours_raw = request.form.get("incurred_hours")
        version = (request.form.get("version") or "").strip() or machine.version or machine.version_label
        nctp = request.form.get("nctp") == "on"
        edit_job_id_raw = request.form.get("edit_job_id")

        cas_approval_raw = request.form.get("report_cas_approval_date")
        sent_customer_raw = request.form.get("report_sent_customer_date")
        sent_review_edb_raw = request.form.get("report_sent_review_edb_date")
        released_edb_raw = request.form.get("released_in_edb_date")
        uploaded_s_drive_reports_raw = request.form.get("uploaded_s_drive_reports_date")
        uploaded_s_drive_jsa_raw = request.form.get("uploaded_s_drive_jsa_date")
        uploaded_s_drive_photos_raw = request.form.get("uploaded_s_drive_photos_date")
        uploaded_s_drive_vizio_raw = request.form.get("uploaded_s_drive_vizio_date")
        log_updated_raw = request.form.get("log_updated_date")
        work_types_payload_raw = request.form.get("work_types_payload")

        if not machine_name:
            flash("Machine / Asset # cannot be empty.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        target_job = None
        target_job_id = None
        if edit_job_id_raw:
            try:
                target_job_id = int(edit_job_id_raw)
            except ValueError:
                target_job_id = None
            if target_job_id:
                target_job = MachineJob.query.filter_by(id=target_job_id, machine_id=machine.id).first()
            if target_job is None:
                flash("Invalid job row selection.", "error")
                return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        if status not in MACHINE_STATUS_OPTIONS:
            flash("Invalid machine status value.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        product_line_id_value, product_line_error = resolve_product_line_id(product_line_id_raw, project.id)
        if product_line_error:
            flash(product_line_error, "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        parsed_work_types, work_types_error = parse_work_types_payload(work_types_payload_raw, require_one=True)
        if work_types_error:
            flash(work_types_error, "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        quoted_hours = parse_float_input(quoted_hours_raw)
        if quoted_hours is None and (quoted_hours_raw or "") != "":
            flash("Quoted hours must be a valid number.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        job_due_date = parse_date_input(job_due_date_raw)
        if job_due_date_raw and job_due_date is None:
            flash("Invalid job due date.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        incurred_hours = parse_float_input(incurred_hours_raw)
        if incurred_hours is None and (incurred_hours_raw or "") != "":
            flash("Incurred hours must be a valid number.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        cas_approval = parse_date_input(cas_approval_raw)
        if cas_approval_raw and cas_approval is None:
            flash("Invalid CAS approval date.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        sent_customer = parse_date_input(sent_customer_raw)
        if sent_customer_raw and sent_customer is None:
            flash("Invalid report sent to customer date.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        sent_review_edb = parse_date_input(sent_review_edb_raw)
        if sent_review_edb_raw and sent_review_edb is None:
            flash("Invalid sent for review in EDB date.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        released_edb = parse_date_input(released_edb_raw)
        if released_edb_raw and released_edb is None:
            flash("Invalid released in EDB date.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        uploaded_s_drive_reports = parse_date_input(uploaded_s_drive_reports_raw)
        if uploaded_s_drive_reports_raw and uploaded_s_drive_reports is None:
            flash("Invalid uploaded to S Drive REPORT(s) date.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        uploaded_s_drive_jsa = parse_date_input(uploaded_s_drive_jsa_raw)
        if uploaded_s_drive_jsa_raw and uploaded_s_drive_jsa is None:
            flash("Invalid uploaded to S Drive JSA date.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        uploaded_s_drive_photos = parse_date_input(uploaded_s_drive_photos_raw)
        if uploaded_s_drive_photos_raw and uploaded_s_drive_photos is None:
            flash("Invalid uploaded to S Drive PHOTOS date.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        uploaded_s_drive_vizio = parse_date_input(uploaded_s_drive_vizio_raw)
        if uploaded_s_drive_vizio_raw and uploaded_s_drive_vizio is None:
            flash("Invalid uploaded to S Drive VIZIO date.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        log_updated = parse_date_input(log_updated_raw)
        if log_updated_raw and log_updated is None:
            flash("Invalid Log Updated date.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        if target_job is not None and len(parsed_work_types) != 1:
            flash("Edit one work type for the selected job row.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id, edit_job=target_job.id) + "#machines")

        if target_job is None:
            sync_error = sync_machine_jobs_from_work_types(machine, parsed_work_types)
            if sync_error:
                flash(sync_error, "error")
                return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")
        if target_job_id:
            target_job = MachineJob.query.filter_by(id=target_job_id, machine_id=machine.id).first()
            if target_job is None:
                db.session.rollback()
                flash("The selected job row no longer exists.", "error")
                return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        milestone_updates = {
            "report_cas_approval_date": cas_approval,
            "report_sent_customer_date": sent_customer,
            "report_sent_review_edb_date": sent_review_edb,
            "released_in_edb_date": released_edb,
            "uploaded_s_drive_reports_date": uploaded_s_drive_reports,
            "uploaded_s_drive_jsa_date": uploaded_s_drive_jsa,
            "uploaded_s_drive_photos_date": uploaded_s_drive_photos,
            "uploaded_s_drive_vizio_date": uploaded_s_drive_vizio,
            "log_updated_date": log_updated,
        }

        audit_field_change(project.id, "machine_updated", "machine_name", machine.machine_name, machine_name, machine_id=machine.id)
        audit_field_change(project.id, "machine_updated", "product_line_id", machine.product_line_id, product_line_id_value, machine_id=machine.id)
        machine.machine_name = machine_name
        machine.product_line_id = product_line_id_value
        machine.version = version
        machine.nctp = nctp

        if target_job is not None:
            selected_work_type = parsed_work_types[0]
            duplicate_job = MachineJob.query.filter(
                MachineJob.machine_id == machine.id,
                MachineJob.id != target_job.id,
                MachineJob.version_number == (target_job.version_number or 1),
                MachineJob.work_type == selected_work_type["work_type"],
                MachineJob.other_description == selected_work_type["other_description"],
            ).first()
            if duplicate_job:
                flash("That work type already exists for this asset/version.", "error")
                return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id, edit_job=target_job.id) + "#machines")

            old_job_label = get_machine_job_label(target_job)
            old_status = target_job.status
            old_due_date = target_job.due_date
            old_quoted_hours = target_job.quoted_hours
            old_incurred_hours = target_job.incurred_hours

            target_job.work_type = selected_work_type["work_type"]
            target_job.other_description = selected_work_type["other_description"]
            target_job.status = status
            target_job.due_date = job_due_date
            target_job.quoted_hours = quoted_hours if quoted_hours is not None else 0.0
            target_job.incurred_hours = incurred_hours if incurred_hours is not None else 0.0
            audit_field_change(project.id, "work_type_changed", "work_type", old_job_label, get_machine_job_label(target_job), machine_id=machine.id, machine_job_id=target_job.id, version_number=target_job.version_number)
            audit_field_change(project.id, "job_status_changed", "status", old_status, target_job.status, machine_id=machine.id, machine_job_id=target_job.id, version_number=target_job.version_number)
            audit_field_change(project.id, "job_hours_changed", "quoted_hours", old_quoted_hours, target_job.quoted_hours, machine_id=machine.id, machine_job_id=target_job.id, version_number=target_job.version_number)
            audit_field_change(project.id, "job_hours_changed", "manual_incurred_hours", old_incurred_hours, target_job.incurred_hours, machine_id=machine.id, machine_job_id=target_job.id, version_number=target_job.version_number)
            audit_field_change(project.id, "job_due_date_changed", "due_date", old_due_date, target_job.due_date, machine_id=machine.id, machine_job_id=target_job.id, version_number=target_job.version_number)
            na_fields_by_date_field = {
                item["field"]: item["na_field"]
                for item in MACHINE_MILESTONE_DEFINITIONS
            }
            for field, value in milestone_updates.items():
                old_value = getattr(target_job, field)
                setattr(target_job, field, value)
                if value:
                    setattr(target_job, na_fields_by_date_field[field], False)
                audit_field_change(project.id, "milestone_changed", field, old_value, value, machine_id=machine.id, machine_job_id=target_job.id, version_number=target_job.version_number)

        MachineWorkType.query.filter_by(machine_id=machine.id).delete()
        work_types_to_store = parsed_work_types
        if target_job is not None:
            work_types_to_store = [
                {
                    "work_type": job.work_type,
                    "other_description": job.other_description,
                }
                for job in MachineJob.query.filter_by(machine_id=machine.id).order_by(MachineJob.id.asc()).all()
            ]

        for wt in work_types_to_store:
            db.session.add(
                MachineWorkType(
                    machine_id=machine.id,
                    work_type=wt["work_type"],
                    other_description=wt["other_description"],
                )
            )
            get_or_create_machine_job(machine, wt["work_type"], wt["other_description"])

        recalculate_project_quoted_hours(project)
        db.session.commit()

        flash("Job row updated.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#machines")

    @app.route("/projects/<int:project_id>/machines/<int:machine_id>/status", methods=["POST"])
    def update_machine_status(project_id, machine_id):
        project = Project.query.get_or_404(project_id)
        machine = Machine.query.filter_by(id=machine_id, project_id=project.id).first_or_404()
        new_status = request.form.get("status")

        if new_status not in MACHINE_STATUS_OPTIONS:
            flash("Invalid machine status value.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#machines")

        machine.status = new_status
        db.session.commit()

        flash("Machine status updated.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#machines")

    @app.route("/projects/<int:project_id>/machine_jobs/<int:job_id>/status", methods=["POST"])
    def update_machine_job_status(project_id, job_id):
        project = Project.query.get_or_404(project_id)
        job = (
            MachineJob.query.join(Machine)
            .filter(MachineJob.id == job_id, Machine.project_id == project.id)
            .first_or_404()
        )
        new_status = request.form.get("status")

        if new_status not in MACHINE_STATUS_OPTIONS:
            flash("Invalid job status value.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#machines")

        old_status = job.status
        job.status = new_status
        audit_field_change(project.id, "job_status_changed", "status", old_status, new_status, machine_id=job.machine_id, machine_job_id=job.id, version_number=job.version_number)
        db.session.commit()

        flash("Job status updated.", "success")
        return redirect(project_machine_job_anchor(project.id, job.id, "status"))

    @app.route("/projects/<int:project_id>/machine_jobs/<int:job_id>/milestones/<string:milestone_key>/set_today", methods=["POST"])
    def set_machine_job_milestone_today(project_id, job_id, milestone_key):
        project = Project.query.get_or_404(project_id)
        job = (
            MachineJob.query.join(Machine)
            .filter(MachineJob.id == job_id, Machine.project_id == project.id)
            .first_or_404()
        )
        field = MILESTONE_FIELD_BY_KEY.get(milestone_key)
        na_field = MILESTONE_NA_FIELD_BY_KEY.get(milestone_key)

        if not field or not na_field:
            flash("Invalid milestone field.", "error")
            return redirect(project_machine_job_anchor(project.id, job.id))

        old_value = getattr(job, field)
        old_na_value = getattr(job, na_field, False)
        new_value = datetime.today().date()
        setattr(job, field, new_value)
        setattr(job, na_field, False)
        audit_field_change(project.id, "milestone_changed", field, old_value, new_value, machine_id=job.machine_id, machine_job_id=job.id, version_number=job.version_number)
        audit_field_change(project.id, "milestone_changed", na_field, old_na_value, False, machine_id=job.machine_id, machine_job_id=job.id, version_number=job.version_number)
        db.session.commit()

        flash("Job milestone updated to today.", "success")
        return redirect(project_machine_job_anchor(project.id, job.id, milestone_key))

    @app.route("/projects/<int:project_id>/machine_jobs/<int:job_id>/milestones/<string:milestone_key>/mark_na", methods=["POST"])
    def mark_machine_job_milestone_na(project_id, job_id, milestone_key):
        project = Project.query.get_or_404(project_id)
        job = (
            MachineJob.query.join(Machine)
            .filter(MachineJob.id == job_id, Machine.project_id == project.id)
            .first_or_404()
        )
        field = MILESTONE_FIELD_BY_KEY.get(milestone_key)
        na_field = MILESTONE_NA_FIELD_BY_KEY.get(milestone_key)

        if not field or not na_field:
            flash("Invalid milestone field.", "error")
            return redirect(project_machine_job_anchor(project.id, job.id))

        old_value = getattr(job, field)
        old_na_value = getattr(job, na_field, False)
        setattr(job, field, None)
        setattr(job, na_field, True)
        audit_field_change(project.id, "milestone_changed", field, old_value, None, machine_id=job.machine_id, machine_job_id=job.id, version_number=job.version_number)
        audit_field_change(project.id, "milestone_changed", na_field, old_na_value, True, machine_id=job.machine_id, machine_job_id=job.id, version_number=job.version_number)
        db.session.commit()

        flash("Job milestone marked N/A.", "success")
        return redirect(project_machine_job_anchor(project.id, job.id, milestone_key))

    @app.route("/projects/<int:project_id>/machine_jobs/<int:job_id>/milestones/<string:milestone_key>/clear", methods=["POST"])
    def clear_machine_job_milestone(project_id, job_id, milestone_key):
        project = Project.query.get_or_404(project_id)
        job = (
            MachineJob.query.join(Machine)
            .filter(MachineJob.id == job_id, Machine.project_id == project.id)
            .first_or_404()
        )
        field = MILESTONE_FIELD_BY_KEY.get(milestone_key)
        na_field = MILESTONE_NA_FIELD_BY_KEY.get(milestone_key)

        if not field or not na_field:
            flash("Invalid milestone field.", "error")
            return redirect(project_machine_job_anchor(project.id, job.id))

        old_value = getattr(job, field)
        old_na_value = getattr(job, na_field, False)
        setattr(job, field, None)
        setattr(job, na_field, False)
        audit_field_change(project.id, "milestone_changed", field, old_value, None, machine_id=job.machine_id, machine_job_id=job.id, version_number=job.version_number)
        audit_field_change(project.id, "milestone_changed", na_field, old_na_value, False, machine_id=job.machine_id, machine_job_id=job.id, version_number=job.version_number)
        db.session.commit()

        flash("Job milestone cleared.", "success")
        return redirect(project_machine_job_anchor(project.id, job.id, milestone_key))

    @app.route("/projects/<int:project_id>/machine_jobs/<int:job_id>/delete", methods=["POST"])
    def delete_machine_job(project_id, job_id):
        project = Project.query.get_or_404(project_id)
        job = (
            MachineJob.query.join(Machine)
            .filter(MachineJob.id == job_id, Machine.project_id == project.id)
            .first_or_404()
        )

        if machine_job_has_history(job):
            flash(
                f"Cannot remove {get_machine_job_label(job)} because it already has time entries, status, hours, due date, or milestone dates.",
                "error",
            )
            return redirect(url_for("project_detail", project_id=project.id) + "#machines")

        MachineWorkType.query.filter_by(
            machine_id=job.machine_id,
            work_type=job.work_type,
            other_description=job.other_description,
        ).delete()
        removed_quote_hours = subtract_deleted_machine_job_quote(project, job)
        db.session.delete(job)
        db.session.commit()

        if removed_quote_hours > 0:
            flash(f"Unused machine job removed. Project quoted hours reduced by {removed_quote_hours:.1f}h.", "success")
        else:
            flash("Unused machine job removed.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#machines")

    @app.route("/projects/<int:project_id>/machines/<int:machine_id>/milestones/<string:milestone_key>/set_today", methods=["POST"])
    def set_machine_milestone_today(project_id, machine_id, milestone_key):
        project = Project.query.get_or_404(project_id)
        machine = Machine.query.filter_by(id=machine_id, project_id=project.id).first_or_404()
        field = MILESTONE_FIELD_BY_KEY.get(milestone_key)

        if not field:
            flash("Invalid milestone field.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#machines")

        setattr(machine, field, datetime.today().date())
        db.session.commit()

        flash("Milestone updated to today.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#machines")

    @app.route("/projects/<int:project_id>/machines/<int:machine_id>/milestones/<string:milestone_key>/clear", methods=["POST"])
    def clear_machine_milestone(project_id, machine_id, milestone_key):
        project = Project.query.get_or_404(project_id)
        machine = Machine.query.filter_by(id=machine_id, project_id=project.id).first_or_404()
        field = MILESTONE_FIELD_BY_KEY.get(milestone_key)

        if not field:
            flash("Invalid milestone field.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#machines")

        setattr(machine, field, None)
        db.session.commit()

        flash("Milestone cleared.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#machines")

    @app.route("/projects/<int:project_id>/machines/<int:machine_id>/delete", methods=["POST"])
    def delete_machine(project_id, machine_id):
        project = Project.query.get_or_404(project_id)
        machine = Machine.query.filter_by(id=machine_id, project_id=project.id).first_or_404()

        if machine.versions:
            flash("Remove the machine versions first before deleting the base machine.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#machines")

        TimeEntry.query.filter_by(project_id=project.id, machine_id=machine.id).update(
            {"machine_id": None, "machine_job_id": None}
        )
        Comment.query.filter_by(project_id=project.id, machine_id=machine.id).update({"machine_id": None})
        MachineWorkType.query.filter_by(machine_id=machine.id).delete()

        db.session.delete(machine)
        db.session.commit()

        flash("Machine / Asset # deleted.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#machines")

    @app.route("/projects/<int:project_id>/machines/<int:machine_id>/versions/create", methods=["POST"])
    def create_machine_version(project_id, machine_id):
        project = Project.query.get_or_404(project_id)
        source_machine = Machine.query.filter_by(id=machine_id, project_id=project.id).first_or_404()
        version_jobs_payload_raw = request.form.get("version_jobs_payload")
        selected_jobs, selected_jobs_error = parse_work_types_payload(version_jobs_payload_raw, require_one=True)
        if selected_jobs_error:
            flash(selected_jobs_error, "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#machines")

        root_id = get_machine_version_root(source_machine)
        family_machines = Machine.query.filter(
            Machine.project_id == project.id,
            or_(Machine.id == root_id, Machine.parent_machine_id == root_id),
        ).all()
        max_version_number = max((machine.version_number or 1) for machine in family_machines)
        next_version_number = max_version_number + 1

        if any((machine.version_number or 1) == next_version_number for machine in family_machines):
            flash(f"V{next_version_number}.0 already exists for this asset.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#machines")

        new_machine = Machine(
            project_id=project.id,
            product_line_id=source_machine.product_line_id,
            machine_name=source_machine.machine_name,
            status="N/S",
            parent_machine_id=root_id,
            version_number=next_version_number,
            version=f"V{next_version_number}.0",
            nctp=source_machine.nctp,
        )
        db.session.add(new_machine)
        db.session.flush()

        audit_change(
            project.id,
            "version_created",
            machine_id=new_machine.id,
            version_number=next_version_number,
            note=f"Created V{next_version_number}.0 for {source_machine.machine_name}",
        )

        for wt in selected_jobs:
            db.session.add(
                MachineWorkType(
                    machine_id=new_machine.id,
                    work_type=wt["work_type"],
                    other_description=wt["other_description"],
                )
            )
            job = MachineJob(
                machine_id=new_machine.id,
                work_type=wt["work_type"],
                other_description=wt["other_description"],
                version_number=next_version_number,
                status="N/S",
                due_date=wt.get("due_date"),
                quoted_hours=wt.get("quoted_hours") or 0.0,
                incurred_hours=0.0,
            )
            db.session.add(job)
            db.session.flush()
            audit_change(
                project.id,
                "job_created",
                machine_id=new_machine.id,
                machine_job_id=job.id,
                version_number=next_version_number,
                note=f"Created {job.version_label} {get_machine_job_label(job)}",
            )

        recalculate_project_quoted_hours(project)
        db.session.commit()

        flash(f"Created V{next_version_number}.0 for {source_machine.machine_name}.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#machines")

    @app.route("/projects/<int:project_id>/status", methods=["POST"])
    def update_project_status(project_id):
        project = Project.query.get_or_404(project_id)
        new_status = request.form.get("status")

        if new_status not in ALLOWED_STATUSES:
            flash("Invalid status value.", "error")
            return redirect(url_for("dashboard"))

        project.status = new_status
        db.session.commit()

        flash("Project status updated.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/projects/<int:project_id>/expenses-submitted/set_today", methods=["POST"])
    def set_project_expenses_submitted_today(project_id):
        project = Project.query.get_or_404(project_id)
        project.expenses_submitted_date = datetime.today().date()
        db.session.commit()
        flash("Expenses Submitted set to today.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#project-header")

    @app.route("/projects/<int:project_id>/expenses-submitted/clear", methods=["POST"])
    def clear_project_expenses_submitted(project_id):
        project = Project.query.get_or_404(project_id)
        project.expenses_submitted_date = None
        db.session.commit()
        flash("Expenses Submitted cleared.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#project-header")

    @app.route("/projects/<int:project_id>/time_entries", methods=["POST"])
    def add_time_entry(project_id):
        project = Project.query.get_or_404(project_id)

        date_str = request.form.get("date")
        work_type = request.form.get("work_type")
        hours_str = request.form.get("hours")
        machine_id_raw = request.form.get("machine_id")
        machine_job_id_raw = request.form.get("machine_job_id")
        notes = request.form.get("notes")
        has_jobs = (
            MachineJob.query.join(Machine)
            .filter(Machine.project_id == project.id)
            .count()
        ) > 0

        if not hours_str:
            flash("Hours are required.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#time-entries")
        if has_jobs and not machine_job_id_raw:
            flash("Select a machine job for this time entry.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#time-entries")

        entry_date = parse_date_input(date_str)
        if date_str and entry_date is None:
            flash("Invalid date format.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#time-entries")

        hours = parse_float_input(hours_str)
        if hours is None:
            flash("Hours must be a valid number.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#time-entries")

        machine_job_id_value, machine_job, machine_job_error = resolve_machine_job_id(machine_job_id_raw, project.id)
        if machine_job_error:
            flash(machine_job_error, "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#time-entries")

        machine_obj = None
        machine_id_value = None
        if machine_job is not None:
            machine_obj = machine_job.machine
            machine_id_value = machine_job.machine_id
            work_type = get_machine_job_label(machine_job)

        db.session.add(
            TimeEntry(
                project_id=project.id,
                machine_id=machine_id_value,
                machine_job_id=machine_job_id_value,
                date=entry_date,
                work_type=work_type,
                hours=hours,
                notes=notes,
            )
        )

        if machine_job and hours > 0 and machine_job.status == "N/S":
            machine_job.status = "WIP"
        if machine_obj and hours > 0 and machine_obj.status == "N/S":
            machine_obj.status = "WIP"

        db.session.commit()
        flash("Time entry added.", "success")

        return redirect(url_for("project_detail", project_id=project.id) + "#time-entries")

    @app.route("/projects/<int:project_id>/time_entries/<int:entry_id>/update", methods=["POST"])
    def update_time_entry(project_id, entry_id):
        project = Project.query.get_or_404(project_id)
        entry = TimeEntry.query.filter_by(id=entry_id, project_id=project.id).first_or_404()

        date_str = request.form.get("date")
        work_type = request.form.get("work_type")
        hours_str = request.form.get("hours")
        machine_id_raw = request.form.get("machine_id")
        machine_job_id_raw = request.form.get("machine_job_id")
        notes = request.form.get("notes")
        has_jobs = (
            MachineJob.query.join(Machine)
            .filter(Machine.project_id == project.id)
            .count()
        ) > 0

        if not hours_str:
            flash("Hours are required.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_time_entry=entry.id) + "#time-entries")
        if has_jobs and not machine_job_id_raw:
            flash("Select a machine job for this time entry.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_time_entry=entry.id) + "#time-entries")

        entry_date = parse_date_input(date_str)
        if date_str and entry_date is None:
            flash("Invalid date format.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_time_entry=entry.id) + "#time-entries")

        hours = parse_float_input(hours_str)
        if hours is None:
            flash("Hours must be a valid number.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_time_entry=entry.id) + "#time-entries")

        machine_job_id_value, machine_job, machine_job_error = resolve_machine_job_id(machine_job_id_raw, project.id)
        if machine_job_error:
            flash(machine_job_error, "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_time_entry=entry.id) + "#time-entries")

        machine_id_value = None
        if machine_job is not None:
            machine_id_value = machine_job.machine_id
            work_type = get_machine_job_label(machine_job)

        entry.date = entry_date
        entry.work_type = work_type
        entry.hours = hours
        entry.machine_id = machine_id_value
        entry.machine_job_id = machine_job_id_value
        entry.notes = notes
        db.session.commit()

        flash("Time entry updated.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#time-entries")

    @app.route("/projects/<int:project_id>/time_entries/<int:entry_id>/delete", methods=["POST"])
    def delete_time_entry(project_id, entry_id):
        project = Project.query.get_or_404(project_id)
        entry = TimeEntry.query.filter_by(id=entry_id, project_id=project.id).first_or_404()

        db.session.delete(entry)
        db.session.commit()

        flash("Time entry deleted.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#time-entries")

    @app.route("/projects/<int:project_id>/update", methods=["POST"])
    def update_project(project_id):
        project = Project.query.get_or_404(project_id)

        customer = request.form.get("customer")
        project_manager = request.form.get("project_manager")
        location = request.form.get("location")
        product_line = request.form.get("product_line")
        na_number = request.form.get("na_number")
        edb_number = request.form.get("edb_number")
        expenses_submitted_date_str = request.form.get("expenses_submitted_date")
        quoted_hours_total = request.form.get("quoted_hours_total")
        job_quotes_payload = request.form.get("job_quotes_payload")
        status = request.form.get("status")

        if customer is not None:
            project.customer = customer
        if project_manager is not None:
            project.project_manager = project_manager
        if location is not None:
            project.location = location
        if product_line is not None:
            project.product_line = product_line
        if na_number is not None:
            project.na_number = na_number
        if edb_number is not None:
            project.edb_number = edb_number

        if expenses_submitted_date_str:
            parsed_expenses = parse_date_input(expenses_submitted_date_str)
            if parsed_expenses is None:
                flash("Invalid Expenses Submitted date format.", "error")
                return redirect(url_for("project_detail", project_id=project.id))
            project.expenses_submitted_date = parsed_expenses
        else:
            project.expenses_submitted_date = None

        if job_quotes_payload:
            job_quotes, job_quotes_error = parse_job_quotes_payload(job_quotes_payload)
            if job_quotes_error:
                flash(job_quotes_error, "error")
                return redirect(url_for("project_detail", project_id=project.id))

            ProjectJobQuote.query.filter_by(project_id=project.id).delete()
            for quote in job_quotes:
                db.session.add(
                    ProjectJobQuote(
                        project_id=project.id,
                        work_type=quote["work_type"],
                        other_description=quote["other_description"],
                        quoted_hours=quote["quoted_hours"],
                        due_date=quote["due_date"],
                    )
                )
            project.quoted_hours_total = sum(item["quoted_hours"] for item in job_quotes)
            quote_due_dates = [item["due_date"] for item in job_quotes if item["due_date"]]
            project.due_date = max(quote_due_dates) if quote_due_dates else None


            # Add new quoted job types to all existing machines so they appear
            # as new rows in the machine list.
            machines = Machine.query.filter_by(project_id=project.id).all()

            for machine in machines:
                for quote in job_quotes:
                    existing_work_type = MachineWorkType.query.filter_by(
                        machine_id=machine.id,
                        work_type=quote["work_type"],
                        other_description=quote["other_description"],
                    ).first()

                    if not existing_work_type:
                        db.session.add(
                            MachineWorkType(
                                machine_id=machine.id,
                                work_type=quote["work_type"],
                                other_description=quote["other_description"],
                            )
                        )

                    job = get_or_create_machine_job(
                        machine,
                        quote["work_type"],
                        quote["other_description"],
                    )
                    job.due_date = quote["due_date"]


        elif quoted_hours_total is not None and quoted_hours_total != "":
            parsed_quoted = parse_float_input(quoted_hours_total)
            if parsed_quoted is None:
                flash("Quoted hours must be a valid number.", "error")
                return redirect(url_for("project_detail", project_id=project.id))
            project.quoted_hours_total = parsed_quoted

        if status and status in ALLOWED_STATUSES:
            project.status = status
        elif status:
            flash("Invalid status value.", "error")
            return redirect(url_for("project_detail", project_id=project.id))

        db.session.commit()
        flash("Project updated.", "success")
        return redirect(url_for("project_detail", project_id=project.id))

    @app.route("/projects/<int:project_id>/comments", methods=["POST"])
    def add_comment(project_id):
        project = Project.query.get_or_404(project_id)

        comment_text = (request.form.get("comment") or "").strip()
        machine_id_raw = request.form.get("machine_id")

        if not comment_text:
            flash("Comment cannot be empty.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#comments")

        machine_id_value, machine_error = resolve_machine_id(machine_id_raw, project.id)
        if machine_error:
            flash(machine_error, "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#comments")

        db.session.add(
            Comment(
                project_id=project.id,
                machine_id=machine_id_value,
                comment=comment_text,
                created_at=datetime.today().date(),
            )
        )
        db.session.commit()
        flash("Comment added.", "success")

        return redirect(url_for("project_detail", project_id=project.id) + "#comments")

    @app.route("/projects/<int:project_id>/comments/<int:comment_id>/update", methods=["POST"])
    def update_comment(project_id, comment_id):
        project = Project.query.get_or_404(project_id)
        item = Comment.query.filter_by(id=comment_id, project_id=project.id).first_or_404()

        comment_text = (request.form.get("comment") or "").strip()
        machine_id_raw = request.form.get("machine_id")

        if not comment_text:
            flash("Comment cannot be empty.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_comment=item.id) + "#comments")

        machine_id_value, machine_error = resolve_machine_id(machine_id_raw, project.id)
        if machine_error:
            flash(machine_error, "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_comment=item.id) + "#comments")

        item.comment = comment_text
        item.machine_id = machine_id_value
        db.session.commit()

        flash("Comment updated.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#comments")

    @app.route("/projects/<int:project_id>/comments/<int:comment_id>/delete", methods=["POST"])
    def delete_comment(project_id, comment_id):
        project = Project.query.get_or_404(project_id)
        item = Comment.query.filter_by(id=comment_id, project_id=project.id).first_or_404()

        db.session.delete(item)
        db.session.commit()

        flash("Comment deleted.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#comments")

    return app


def ensure_machine_schema():
    existing_cols = {
        row[1]
        for row in db.session.execute(text("PRAGMA table_info(machines)")).fetchall()
    }

    required_cols = {
        "status": "TEXT DEFAULT 'N/S'",
        "parent_machine_id": "INTEGER",
        "version_number": "INTEGER DEFAULT 1",
        "report_cas_approval_date": "DATE",
        "report_sent_customer_date": "DATE",
        "report_sent_review_edb_date": "DATE",
        "released_in_edb_date": "DATE",
        "uploaded_s_drive_reports_date": "DATE",
        "uploaded_s_drive_jsa_date": "DATE",
        "uploaded_s_drive_photos_date": "DATE",
        "uploaded_s_drive_vizio_date": "DATE",
        "log_updated_date": "DATE",
        "product_line_id": "INTEGER",
    }

    for col_name, col_def in required_cols.items():
        if col_name not in existing_cols:
            db.session.execute(text(f"ALTER TABLE machines ADD COLUMN {col_name} {col_def}"))
            db.session.commit()

    if "version_number" not in existing_cols:
        db.session.execute(text("UPDATE machines SET version_number = 1 WHERE version_number IS NULL OR version_number = 0"))
        db.session.commit()

    machines_without_version = Machine.query.filter(
        (Machine.version.is_(None)) | (Machine.version == "")
    ).all()
    for machine in machines_without_version:
        machine.version_number = machine.version_number or 1
        machine.version = machine.version_label

    machines_without_version_number = Machine.query.filter(
        (Machine.version_number.is_(None)) | (Machine.version_number == 0)
    ).all()
    for machine in machines_without_version_number:
        machine.version_number = 1
        if not machine.version:
            machine.version = machine.version_label

    if machines_without_version or machines_without_version_number:
        db.session.commit()

    # Backfill Product / Line structure for legacy projects and machines.
    projects = Project.query.order_by(Project.id.asc()).all()
    for project in projects:
        general_line = ProductLine.query.filter_by(project_id=project.id, name="General").first()
        if not general_line:
            general_line = ProductLine(project_id=project.id, name="General")
            db.session.add(general_line)
            db.session.flush()

        Machine.query.filter_by(project_id=project.id, product_line_id=None).update(
            {"product_line_id": general_line.id}
        )

    # Normalize legacy status values to the current vocabulary.
    db.session.execute(
        text(
            """
            UPDATE projects
               SET status = CASE
                 WHEN status IN ('Not Started', 'N/A') THEN 'N/S'
                 WHEN status = 'Review' THEN 'In Review'
                 WHEN status = 'Complete' THEN 'Completed'
                 ELSE status
               END
             WHERE status IN ('Not Started', 'N/A', 'Review', 'Complete')
            """
        )
    )
    db.session.execute(
        text(
            """
            UPDATE machines
               SET status = CASE
                 WHEN status IN ('Not Started', 'N/A') THEN 'N/S'
                 WHEN status = 'Review' THEN 'In Review'
                 WHEN status = 'Complete' THEN 'Completed'
                 ELSE status
               END
             WHERE status IN ('Not Started', 'N/A', 'Review', 'Complete')
            """
        )
    )

    db.session.commit()


def ensure_machine_job_schema():
    """Create/backfill job-level tracking rows for machine work types.
    Also ensures parent_job_id and version_number columns exist.
    """
    project_job_quote_cols = {
        row[1]
        for row in db.session.execute(text("PRAGMA table_info(project_job_quotes)")).fetchall()
    }
    has_project_job_quote_due_date = "due_date" in project_job_quote_cols
    if not has_project_job_quote_due_date:
        db.session.execute(text("ALTER TABLE project_job_quotes ADD COLUMN due_date DATE"))
        db.session.commit()
        has_project_job_quote_due_date = True

    # 1. Ensure machine_job_id column exists in time_entries
    time_entry_cols = {
        row[1]
        for row in db.session.execute(text("PRAGMA table_info(time_entries)")).fetchall()
    }
    if "machine_job_id" not in time_entry_cols:
        db.session.execute(text("ALTER TABLE time_entries ADD COLUMN machine_job_id INTEGER"))
        db.session.commit()

    # 2. Ensure required columns exist in machine_jobs table
    machine_job_cols = {
        row[1]
        for row in db.session.execute(text("PRAGMA table_info(machine_jobs)")).fetchall()
    }

    # Add parent_job_id if missing (this fixes your exact error)
    if "parent_job_id" not in machine_job_cols:
        db.session.execute(text("ALTER TABLE machine_jobs ADD COLUMN parent_job_id INTEGER"))
        db.session.commit()
        machine_job_cols.add("parent_job_id")

    # Add version_number if missing
    if "version_number" not in machine_job_cols:
        db.session.execute(text("ALTER TABLE machine_jobs ADD COLUMN version_number INTEGER DEFAULT 1"))
        db.session.commit()
        machine_job_cols.add("version_number")

    # Add incurred_hours if missing (your existing code)
    if "incurred_hours" not in machine_job_cols:
        db.session.execute(text("ALTER TABLE machine_jobs ADD COLUMN incurred_hours FLOAT DEFAULT 0.0"))
        db.session.commit()
        machine_job_cols.add("incurred_hours")

    if "due_date" not in machine_job_cols:
        db.session.execute(text("ALTER TABLE machine_jobs ADD COLUMN due_date DATE"))
        db.session.commit()
        machine_job_cols.add("due_date")

    if has_project_job_quote_due_date:
        db.session.execute(text("""
            UPDATE machine_jobs
               SET due_date = (
                   SELECT project_job_quotes.due_date
                     FROM project_job_quotes
                     JOIN machines ON machines.project_id = project_job_quotes.project_id
                    WHERE machines.id = machine_jobs.machine_id
                      AND project_job_quotes.work_type = machine_jobs.work_type
                      AND (
                          project_job_quotes.other_description = machine_jobs.other_description
                          OR (project_job_quotes.other_description IS NULL AND machine_jobs.other_description IS NULL)
                      )
                    LIMIT 1
               )
             WHERE due_date IS NULL
        """))
        db.session.commit()

    for item in MACHINE_MILESTONE_DEFINITIONS:
        na_field = item["na_field"]
        if na_field not in machine_job_cols:
            db.session.execute(text(f"ALTER TABLE machine_jobs ADD COLUMN {na_field} BOOLEAN DEFAULT 0"))
            db.session.commit()
            machine_job_cols.add(na_field)

    # Backfill defaults for existing rows
    if "version_number" in machine_job_cols:
        db.session.execute(text("""
            UPDATE machine_jobs 
            SET version_number = 1 
            WHERE version_number IS NULL OR version_number = 0
        """))
        db.session.commit()

    # 3. Rest of your existing backfill logic (kept mostly the same)
    milestone_fields = [item["field"] for item in MACHINE_MILESTONE_DEFINITIONS]

    def job_label(job):
        return format_work_type_label_value(job.work_type, job.other_description)

    def machine_work_type_specs(machine):
        specs = []
        seen = set()
        for wt in sorted(machine.work_types, key=lambda item: item.id):
            key = (wt.work_type, wt.other_description or None)
            if key in seen:
                continue
            seen.add(key)
            specs.append({"work_type": wt.work_type, "other_description": wt.other_description or None})

        if not specs:
            specs.append({"work_type": "RA", "other_description": None})
            db.session.add(MachineWorkType(machine_id=machine.id, work_type="RA", other_description=None))

        return specs

    def get_or_create_job(machine, work_type, other_description=None):
        # Use parent_job_id=None to only match root jobs (consistent with top-level function)
        existing = MachineJob.query.filter_by(
            machine_id=machine.id,
            work_type=work_type,
            other_description=other_description or None,
            parent_job_id=None,          # ← important for hierarchy
        ).first()
        if existing:
            return existing, False

        job = MachineJob(
            machine_id=machine.id,
            work_type=work_type,
            other_description=other_description or None,
            status="N/S",
            version_number=1,
            parent_job_id=None,          # ← explicitly set for new root jobs
        )
        db.session.add(job)
        db.session.flush()
        return job, True

    # ... (rest of the function stays exactly the same as you have it)
    machines = Machine.query.order_by(Machine.id.asc()).all()
    for machine in machines:
        for spec in machine_work_type_specs(machine):
            job, created = get_or_create_job(machine, spec["work_type"], spec["other_description"])
            if created and job.work_type == "RA" and not job.other_description:
                job.status = machine.status or job.status or "N/S"
                job.quoted_hours = machine.quoted_hours or job.quoted_hours or 0.0
                job.incurred_hours = machine.incurred_hours or job.incurred_hours or 0.0
                for field in milestone_fields:
                    if getattr(job, field, None) is None:
                        setattr(job, field, getattr(machine, field, None))

    db.session.flush()

    # ... (the TimeEntry backfill part stays the same)
    jobs_by_machine = {}
    for job in MachineJob.query.order_by(MachineJob.id.asc()).all():
        jobs_by_machine.setdefault(job.machine_id, []).append(job)

    for entry in TimeEntry.query.filter(TimeEntry.machine_id.isnot(None)).all():
        if entry.machine_job_id:
            continue

        jobs = jobs_by_machine.get(entry.machine_id, [])
        entry_label = (entry.work_type or "").strip() or "RA"
        match = next((job for job in jobs if job_label(job) == entry_label), None)

        if not match:
            machine = Machine.query.get(entry.machine_id)
            if not machine:
                continue

            if entry_label in WORK_TYPE_OPTIONS:
                work_type = entry_label
                other_description = None
            elif entry_label.startswith("Other - "):
                work_type = "Other"
                other_description = entry_label.replace("Other - ", "", 1).strip() or None
            else:
                work_type = "Other"
                other_description = entry_label

            match, _ = get_or_create_job(machine, work_type, other_description)
            jobs_by_machine.setdefault(machine.id, []).append(match)

        entry.machine_job_id = match.id

    db.session.commit()

def ensure_project_schema():
    """Ensure legacy project tables have newer project fields."""
    existing_cols = {
        row[1]
        for row in db.session.execute(text("PRAGMA table_info(projects)")).fetchall()
    }

    # Add created_at column if it doesn't exist
    if "created_at" not in existing_cols:
        db.session.execute(text("ALTER TABLE projects ADD COLUMN created_at DATETIME"))
        db.session.commit()

    if "expenses_submitted_date" not in existing_cols:
        db.session.execute(text("ALTER TABLE projects ADD COLUMN expenses_submitted_date DATE"))
        db.session.commit()

    if "project_manager" not in existing_cols:
        db.session.execute(text("ALTER TABLE projects ADD COLUMN project_manager VARCHAR(255)"))
        db.session.commit()

    # Set created_at for existing projects that don't have it
    # For existing projects, set created_at to their current modification time or a reasonable default
    projects_without_created_at = Project.query.filter(Project.created_at.is_(None)).all()
    for project in projects_without_created_at:
        # Set created_at to the current time for existing projects
        # In a real scenario, you might want to set this to a more accurate historical date
        project.created_at = datetime.utcnow()
    
    if projects_without_created_at:
        db.session.commit()


if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=False)
