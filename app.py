# app.py
from datetime import datetime
import os

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)
from models import db, Project, Machine, TimeEntry, Comment


def create_app():
    app = Flask(__name__)

    # Basic config
    app.config["SECRET_KEY"] = "change-me-in-production"
    # SQLite DB in instance/ folder (created if it doesn't exist)
    db_path = os.path.join(app.instance_path, "app.db")
    os.makedirs(app.instance_path, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()

    # ---------------------------
    # Routes
    # ---------------------------

    @app.route("/")
    def dashboard():
        # Read optional status filter from query string, e.g. /?status=WIP
        status_filter = request.args.get("status", type=str)

        # Build base query
        query = Project.query
        if status_filter:
            query = query.filter_by(status=status_filter)

        projects = query.order_by(Project.due_date).all()

        # Recalculate incurred_hours_total on the fly for each project
        for project in projects:
            total_incurred = sum(te.hours for te in project.time_entries)
            project.incurred_hours_total = total_incurred
            # Note: we don't need to commit this; it's just for display

        # Pass status_filter so the template can keep the dropdown in sync
        return render_template("dashboard.html", projects=projects, status_filter=status_filter)

    @app.route("/projects/new", methods=["GET", "POST"])
    def new_project():
        if request.method == "POST":
            customer = request.form.get("customer")
            location = request.form.get("location")
            product_line = request.form.get("product_line")
            na_number = request.form.get("na_number")
            edb_number = request.form.get("edb_number")
            due_date_str = request.form.get("due_date")
            quoted_hours_total = request.form.get("quoted_hours_total") or 0

            # NEW: optional multi-line machines / asset numbers
            machines_raw = request.form.get("machines")

            if not customer:
                flash("Customer is required.", "error")
                return redirect(url_for("new_project"))

            due_date = None
            if due_date_str:
                due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()

            project = Project(
                customer=customer,
                location=location,
                product_line=product_line,
                na_number=na_number,
                edb_number=edb_number,
                due_date=due_date,
                quoted_hours_total=float(quoted_hours_total),
            )
            db.session.add(project)
            db.session.commit()

            # NEW: if machines were provided, create one Machine row per line
            if machines_raw:
                # split on new lines, strip whitespace, ignore empty lines
                machine_names = [
                    line.strip() for line in machines_raw.splitlines() if line.strip()
                ]
                for name in machine_names:
                    machine = Machine(
                        project_id=project.id,
                        machine_name=name
                    )
                    db.session.add(machine)
                db.session.commit()

            flash("Project created.", "success")
            return redirect(url_for("project_detail", project_id=project.id))

        return render_template("project_form.html")

    @app.route("/projects/<int:project_id>")
    def project_detail(project_id):
        project = Project.query.get_or_404(project_id)
        machines = Machine.query.filter_by(project_id=project.id).all()
        time_entries = (
            TimeEntry.query.filter_by(project_id=project.id)
            .order_by(TimeEntry.date.desc())
            .all()
        )
        comments = (
            Comment.query.filter_by(project_id=project.id)
            .order_by(Comment.created_at.desc())
            .all()
        )

        total_incurred = sum(te.hours for te in time_entries)
        project.incurred_hours_total = total_incurred

        return render_template(
            "project_detail.html",
            project=project,
            machines=machines,
            time_entries=time_entries,
            comments=comments,
        )

    @app.route("/projects/<int:project_id>/delete", methods=["POST"])
    def delete_project(project_id):
        project = Project.query.get_or_404(project_id)

        # This will also delete related machines, time entries, and comments
        # because in models.py you set cascade="all, delete-orphan" on relationships.
        db.session.delete(project)
        db.session.commit()

        flash("Project deleted successfully.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/projects/<int:project_id>/status", methods=["POST"])
    def update_project_status(project_id):
        project = Project.query.get_or_404(project_id)
        new_status = request.form.get("status")

        # Optional: restrict to known statuses
        allowed_statuses = ["Not Started", "WIP", "Stopped", "Complete"]
        if new_status not in allowed_statuses:
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
        machine_id = request.form.get("machine_id") or None
        notes = request.form.get("notes")

        if not hours_str:
            flash("Hours are required.", "error")
            return redirect(url_for("project_detail", project_id=project.id))

        entry_date = None
        if date_str:
            entry_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        time_entry = TimeEntry(
            project_id=project.id,
            machine_id=int(machine_id) if machine_id else None,
            date=entry_date,
            work_type=work_type,
            hours=float(hours_str),
            notes=notes,
        )
        db.session.add(time_entry)
        db.session.commit()
        flash("Time entry added.", "success")

        return redirect(url_for("project_detail", project_id=project.id))

    @app.route("/projects/<int:project_id>/comments", methods=["POST"])
    def add_comment(project_id):
        project = Project.query.get_or_404(project_id)

        comment_text = request.form.get("comment")
        author = request.form.get("author") or "System"

        if not comment_text:
            flash("Comment cannot be empty.", "error")
            return redirect(url_for("project_detail", project_id=project.id))

        comment = Comment(
            project_id=project.id,
            comment=comment_text,
            author=author,
            created_at=datetime.today().date(),
        )
        db.session.add(comment)
        db.session.commit()
        flash("Comment added.", "success")

        return redirect(url_for("project_detail", project_id=project.id))

    return app


if __name__ == "__main__":
    app = create_app()
    # For development only; use a proper server in production
    app.run(debug=True)