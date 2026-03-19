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
    status = db.Column(db.String(50), default="N/S")

    quoted_hours_total = db.Column(db.Float, default=0.0)
    incurred_hours_total = db.Column(db.Float, default=0.0)

    machines = db.relationship(
        "Machine",
        backref="project",
        lazy=True,
        cascade="all, delete-orphan"
    )
    product_lines = db.relationship(
        "ProductLine",
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
        if not self.due_date:
            return None
        return (self.due_date - date.today()).days

    @property
    def percent_used(self) -> float:
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
    product_line_id = db.Column(
        db.Integer,
        db.ForeignKey("product_lines.id"),
        nullable=True
    )

    machine_name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(50), default="N/S")

    report_cas_approval_date = db.Column(db.Date, nullable=True)
    report_sent_customer_date = db.Column(db.Date, nullable=True)
    report_sent_review_edb_date = db.Column(db.Date, nullable=True)
    released_in_edb_date = db.Column(db.Date, nullable=True)

    quoted_hours = db.Column(db.Float, default=0.0)
    incurred_hours = db.Column(db.Float, default=0.0)

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
    work_types = db.relationship(
        "MachineWorkType",
        backref="machine",
        lazy=True,
        cascade="all, delete-orphan"
    )

    @property
    def balance_hours(self) -> float:
        return (self.quoted_hours or 0.0) - (self.incurred_hours or 0.0)


class ProductLine(db.Model):
    __tablename__ = "product_lines"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id"),
        nullable=False
    )
    name = db.Column(db.String(255), nullable=False)

    machines = db.relationship(
        "Machine",
        backref="product_line",
        lazy=True
    )


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
    work_type = db.Column(db.String(100))
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


class MachineWorkType(db.Model):
    __tablename__ = "machine_work_types"

    id = db.Column(db.Integer, primary_key=True)
    machine_id = db.Column(
        db.Integer,
        db.ForeignKey("machines.id"),
        nullable=False
    )
    work_type = db.Column(db.String(50), nullable=False)
    other_description = db.Column(db.String(255))
