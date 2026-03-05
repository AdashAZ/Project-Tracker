# models.py
from datetime import date
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)

    customer = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(255))
    product_line = db.Column(db.String(255))
    na_number = db.Column(db.String(100))   # NA# / SO#
    edb_number = db.Column(db.String(100))

    due_date = db.Column(db.Date)
    status = db.Column(db.String(50), default="Not Started")

    # Totals for the whole project (you can keep them derived if you prefer)
    quoted_hours_total = db.Column(db.Float, default=0.0)
    incurred_hours_total = db.Column(db.Float, default=0.0)

    # Relationships
    machines = db.relationship(
        "Machine",
        backref="project",
        lazy=True,
        cascade="all, delete-orphan"
    )
    time_entries = db.relationship(
        "TimeEntry",
        backref="project",
        lazy=True,
        cascade="all, delete-orphan"
    )
    comments = db.relationship(
        "Comment",
        backref="project",
        lazy=True,
        cascade="all, delete-orphan"
    )

    @property
    def days_left(self) -> int | None:
        """Days until due date (like your Excel formulas)."""
        if not self.due_date:
            return None
        return (self.due_date - date.today()).days

    @property
    def percent_used(self) -> float:
        """% of hours used."""
        if not self.quoted_hours_total:
            return 0.0
        return (self.incurred_hours_total or 0.0) / self.quoted_hours_total * 100.0


class Machine(db.Model):
    __tablename__ = "machines"

    id = db.Column(db.Integer, primary_key=True)

    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id"),
        nullable=False
    )

    machine_name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(50), default="Not Started")

    quoted_hours = db.Column(db.Float, default=0.0)
    incurred_hours = db.Column(db.Float, default=0.0)

    # Optional fields for your use-case (NCTP, version, etc.)
    nctp = db.Column(db.Boolean, default=False)
    version = db.Column(db.String(50))

    time_entries = db.relationship(
        "TimeEntry",
        backref="machine",
        lazy=True
    )
    comments = db.relationship(
        "Comment",
        backref="machine",
        lazy=True
    )

    @property
    def balance_hours(self) -> float:
        return (self.quoted_hours or 0.0) - (self.incurred_hours or 0.0)


class TimeEntry(db.Model):
    __tablename__ = "time_entries"

    id = db.Column(db.Integer, primary_key=True)

    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id"),
        nullable=False
    )
    machine_id = db.Column(
        db.Integer,
        db.ForeignKey("machines.id"),
        nullable=True
    )

    date = db.Column(db.Date)
    work_type = db.Column(db.String(100))   # e.g. "RA On-site", "SC Off-site"
    hours = db.Column(db.Float, nullable=False)
    notes = db.Column(db.Text)


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)

    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id"),
        nullable=False
    )
    machine_id = db.Column(
        db.Integer,
        db.ForeignKey("machines.id"),
        nullable=True
    )

    author = db.Column(db.String(100))
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.Date, default=date.today)