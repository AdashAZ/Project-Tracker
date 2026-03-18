# app.py
from datetime import datetime
import re
import os
import subprocess
import secrets

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)
from sqlalchemy import text
from urllib.parse import quote
from markupsafe import Markup, escape

from models import db, Project, Machine, TimeEntry, Comment

ALLOWED_STATUSES = {"N/S", "WIP", "Stopped", "In Review", "Completed"}
MACHINE_STATUS_OPTIONS = ["N/S", "WIP", "Stopped", "In Review", "Completed"]
MACHINE_MILESTONE_DEFINITIONS = [
    {
        "key": "cas_approval",
        "label": "Report CAS Approval Date",
        "field": "report_cas_approval_date",
    },
    {
        "key": "sent_customer",
        "label": "Report Sent to Customer Date",
        "field": "report_sent_customer_date",
    },
    {
        "key": "sent_review_edb",
        "label": "Report Sent for Review in EDB",
        "field": "report_sent_review_edb_date",
    },
    {
        "key": "released_edb",
        "label": "Released in EDB",
        "field": "released_in_edb_date",
    },
]
MILESTONE_FIELD_BY_KEY = {item["key"]: item["field"] for item in MACHINE_MILESTONE_DEFINITIONS}


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    db_path = os.path.join(app.instance_path, "app.db")
    os.makedirs(app.instance_path, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()
        ensure_machine_schema()

    def parse_date_input(value: str | None):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def parse_float_input(value: str | None):
        if value in (None, ""):
            return None
        try:
            return float(value)
        except ValueError:
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

    def compute_machine_stats(machines, time_entries):
        machine_hours = {machine.id: 0.0 for machine in machines}
        machine_entry_counts = {machine.id: 0 for machine in machines}
        for entry in time_entries:
            if entry.machine_id in machine_hours:
                machine_hours[entry.machine_id] += entry.hours or 0.0
                machine_entry_counts[entry.machine_id] += 1
        return machine_hours, machine_entry_counts

    def get_machine_milestone_view(machines):
        milestone_values = {}
        row_complete = {}
        milestone_fields = [item["field"] for item in MACHINE_MILESTONE_DEFINITIONS]

        for machine in machines:
            per_machine = {}
            for item in MACHINE_MILESTONE_DEFINITIONS:
                per_machine[item["key"]] = getattr(machine, item["field"])
            milestone_values[machine.id] = per_machine
            row_complete[machine.id] = machine.status == "Completed"

        return milestone_values, row_complete


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
            expected = session.get("_csrf_token")
            received = request.form.get("_csrf_token")
            if not expected or expected != received:
                flash("Invalid form token. Please try again.", "error")
                return redirect(request.referrer or url_for("dashboard"))

    @app.route("/")
    def dashboard():
        status_filter = request.args.get("status", type=str)

        query = Project.query
        if status_filter and status_filter in ALLOWED_STATUSES:
            query = query.filter_by(status=status_filter)

        projects = query.order_by(Project.due_date).all()

        for project in projects:
            total_incurred = sum(te.hours for te in project.time_entries)
            project.incurred_hours_total = total_incurred

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
    @app.route("/projects/new", methods=["GET", "POST"])
    def new_project():
        if request.method == "POST":
            customer = request.form.get("customer")
            location = request.form.get("location")
            product_line = request.form.get("product_line")
            na_number = request.form.get("na_number")
            edb_number = request.form.get("edb_number")
            due_date_str = request.form.get("due_date")
            quoted_hours_total = request.form.get("quoted_hours_total") or "0"
            machines_raw = request.form.get("machines")

            if not customer:
                flash("Customer is required.", "error")
                return redirect(url_for("new_project"))

            due_date = parse_date_input(due_date_str)
            if due_date_str and due_date is None:
                flash("Invalid due date format.", "error")
                return redirect(url_for("new_project"))

            quoted_hours = parse_float_input(quoted_hours_total)
            if quoted_hours is None:
                flash("Quoted hours must be a valid number.", "error")
                return redirect(url_for("new_project"))

            project = Project(
                customer=customer,
                location=location,
                product_line=product_line,
                na_number=na_number,
                edb_number=edb_number,
                due_date=due_date,
                quoted_hours_total=quoted_hours,
            )
            db.session.add(project)
            db.session.commit()

            if machines_raw:
                machine_names = [line.strip() for line in machines_raw.splitlines() if line.strip()]
                for name in machine_names:
                    db.session.add(Machine(project_id=project.id, machine_name=name, status="N/S"))
                db.session.commit()

            flash("Project created.", "success")
            return redirect(url_for("project_detail", project_id=project.id))

        return render_template("project_form.html")

    @app.route("/projects/<int:project_id>")
    def project_detail(project_id):
        project = Project.query.get_or_404(project_id)
        machines = Machine.query.filter_by(project_id=project.id).order_by(Machine.id.asc()).all()
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

        edit_machine_id = request.args.get("edit_machine", type=int)
        if edit_machine_id and not any(machine.id == edit_machine_id for machine in machines):
            edit_machine_id = None

        edit_time_entry_id = request.args.get("edit_time_entry", type=int)
        if edit_time_entry_id and not any(entry.id == edit_time_entry_id for entry in time_entries):
            edit_time_entry_id = None

        edit_comment_id = request.args.get("edit_comment", type=int)
        if edit_comment_id and not any(item.id == edit_comment_id for item in comments):
            edit_comment_id = None

        return render_template(
            "project_detail.html",
            project=project,
            machines=machines,
            time_entries=time_entries,
            comments=comments,
            machine_hours=machine_hours,
            machine_entry_counts=machine_entry_counts,
            machine_milestones=machine_milestones,
            machine_row_complete=machine_row_complete,
            machine_status_options=MACHINE_STATUS_OPTIONS,
            milestone_definitions=MACHINE_MILESTONE_DEFINITIONS,
            edit_machine_id=edit_machine_id,
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

        if not machine_name:
            flash("Machine / Asset # cannot be empty.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#machines")

        db.session.add(Machine(project_id=project.id, machine_name=machine_name, status="N/S"))
        db.session.commit()

        flash("Machine / Asset # added.", "success")
        return redirect(url_for("project_detail", project_id=project.id) + "#machines")

    @app.route("/projects/<int:project_id>/machines/<int:machine_id>/update", methods=["POST"])
    def update_machine(project_id, machine_id):
        project = Project.query.get_or_404(project_id)
        machine = Machine.query.filter_by(id=machine_id, project_id=project.id).first_or_404()

        machine_name = (request.form.get("machine_name") or "").strip()
        status = request.form.get("status")
        quoted_hours_raw = request.form.get("quoted_hours")
        incurred_hours_raw = request.form.get("incurred_hours")
        version = (request.form.get("version") or "").strip() or None
        nctp = request.form.get("nctp") == "on"

        cas_approval_raw = request.form.get("report_cas_approval_date")
        sent_customer_raw = request.form.get("report_sent_customer_date")
        sent_review_edb_raw = request.form.get("report_sent_review_edb_date")
        released_edb_raw = request.form.get("released_in_edb_date")

        if not machine_name:
            flash("Machine / Asset # cannot be empty.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        if status not in MACHINE_STATUS_OPTIONS:
            flash("Invalid machine status value.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_machine=machine.id) + "#machines")

        quoted_hours = parse_float_input(quoted_hours_raw)
        if quoted_hours is None and (quoted_hours_raw or "") != "":
            flash("Quoted hours must be a valid number.", "error")
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

        machine.machine_name = machine_name
        machine.status = status
        machine.quoted_hours = quoted_hours if quoted_hours is not None else 0.0
        machine.incurred_hours = incurred_hours if incurred_hours is not None else 0.0
        machine.version = version
        machine.nctp = nctp
        machine.report_cas_approval_date = cas_approval
        machine.report_sent_customer_date = sent_customer
        machine.report_sent_review_edb_date = sent_review_edb
        machine.released_in_edb_date = released_edb
        db.session.commit()

        flash("Machine row updated.", "success")
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

        TimeEntry.query.filter_by(project_id=project.id, machine_id=machine.id).update({"machine_id": None})
        Comment.query.filter_by(project_id=project.id, machine_id=machine.id).update({"machine_id": None})

        db.session.delete(machine)
        db.session.commit()

        flash("Machine / Asset # deleted.", "success")
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

    @app.route("/projects/<int:project_id>/time_entries", methods=["POST"])
    def add_time_entry(project_id):
        project = Project.query.get_or_404(project_id)

        date_str = request.form.get("date")
        work_type = request.form.get("work_type")
        hours_str = request.form.get("hours")
        machine_id_raw = request.form.get("machine_id")
        notes = request.form.get("notes")
        has_machines = Machine.query.filter_by(project_id=project.id).count() > 0

        if not hours_str:
            flash("Hours are required.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#time-entries")
        if has_machines and not machine_id_raw:
            flash("Select a machine / asset # for this time entry.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#time-entries")

        entry_date = parse_date_input(date_str)
        if date_str and entry_date is None:
            flash("Invalid date format.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#time-entries")

        hours = parse_float_input(hours_str)
        if hours is None:
            flash("Hours must be a valid number.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#time-entries")

        machine_id_value, machine_error = resolve_machine_id(machine_id_raw, project.id)
        if machine_error:
            flash(machine_error, "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#time-entries")

        db.session.add(
            TimeEntry(
                project_id=project.id,
                machine_id=machine_id_value,
                date=entry_date,
                work_type=work_type,
                hours=hours,
                notes=notes,
            )
        )
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
        notes = request.form.get("notes")
        has_machines = Machine.query.filter_by(project_id=project.id).count() > 0

        if not hours_str:
            flash("Hours are required.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_time_entry=entry.id) + "#time-entries")
        if has_machines and not machine_id_raw:
            flash("Select a machine / asset # for this time entry.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_time_entry=entry.id) + "#time-entries")

        entry_date = parse_date_input(date_str)
        if date_str and entry_date is None:
            flash("Invalid date format.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_time_entry=entry.id) + "#time-entries")

        hours = parse_float_input(hours_str)
        if hours is None:
            flash("Hours must be a valid number.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_time_entry=entry.id) + "#time-entries")

        machine_id_value, machine_error = resolve_machine_id(machine_id_raw, project.id)
        if machine_error:
            flash(machine_error, "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_time_entry=entry.id) + "#time-entries")

        entry.date = entry_date
        entry.work_type = work_type
        entry.hours = hours
        entry.machine_id = machine_id_value
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
        location = request.form.get("location")
        product_line = request.form.get("product_line")
        na_number = request.form.get("na_number")
        edb_number = request.form.get("edb_number")
        due_date_str = request.form.get("due_date")
        quoted_hours_total = request.form.get("quoted_hours_total")
        status = request.form.get("status")

        if customer is not None:
            project.customer = customer
        if location is not None:
            project.location = location
        if product_line is not None:
            project.product_line = product_line
        if na_number is not None:
            project.na_number = na_number
        if edb_number is not None:
            project.edb_number = edb_number

        if due_date_str:
            parsed_due = parse_date_input(due_date_str)
            if parsed_due is None:
                flash("Invalid due date format.", "error")
                return redirect(url_for("project_detail", project_id=project.id))
            project.due_date = parsed_due
        else:
            project.due_date = None

        if quoted_hours_total is not None and quoted_hours_total != "":
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
        author = request.form.get("author") or "System"

        if not comment_text:
            flash("Comment cannot be empty.", "error")
            return redirect(url_for("project_detail", project_id=project.id) + "#comments")

        db.session.add(
            Comment(
                project_id=project.id,
                comment=comment_text,
                author=author,
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
        author = request.form.get("author") or "System"

        if not comment_text:
            flash("Comment cannot be empty.", "error")
            return redirect(url_for("project_detail", project_id=project.id, edit_comment=item.id) + "#comments")

        item.comment = comment_text
        item.author = author
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
        "report_cas_approval_date": "DATE",
        "report_sent_customer_date": "DATE",
        "report_sent_review_edb_date": "DATE",
        "released_in_edb_date": "DATE",
    }

    for col_name, col_def in required_cols.items():
        if col_name not in existing_cols:
            db.session.execute(text(f"ALTER TABLE machines ADD COLUMN {col_name} {col_def}"))

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


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)

