# models.py
from datetime import date, datetime
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
    expenses_submitted_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(50), default="N/S")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    job_quotes = db.relationship(
        "ProjectJobQuote",
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
    parent_machine_id = db.Column(db.Integer, db.ForeignKey("machines.id"), nullable=True)
    version_number = db.Column(db.Integer, default=1)

    report_cas_approval_date = db.Column(db.Date, nullable=True)
    report_sent_customer_date = db.Column(db.Date, nullable=True)
    report_sent_review_edb_date = db.Column(db.Date, nullable=True)
    released_in_edb_date = db.Column(db.Date, nullable=True)
    uploaded_s_drive_reports_date = db.Column(db.Date, nullable=True)
    uploaded_s_drive_jsa_date = db.Column(db.Date, nullable=True)
    uploaded_s_drive_photos_date = db.Column(db.Date, nullable=True)
    uploaded_s_drive_vizio_date = db.Column(db.Date, nullable=True)
    log_updated_date = db.Column(db.Date, nullable=True)

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
    jobs = db.relationship(
        "MachineJob",
        backref="machine",
        lazy=True,
        cascade="all, delete-orphan"
    )
    parent_machine = db.relationship(
        "Machine",
        remote_side=[id],
        foreign_keys=[parent_machine_id],
        backref="versions",
        lazy=True,
    )

    @property
    def balance_hours(self) -> float:
        return (self.quoted_hours or 0.0) - (self.incurred_hours or 0.0)

    @property
    def version_label(self) -> str:
        version_num = self.version_number or 1
        return f"V{version_num}.0"


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


class ProjectJobQuote(db.Model):
    __tablename__ = "project_job_quotes"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id"),
        nullable=False
    )
    work_type = db.Column(db.String(50), nullable=False)
    other_description = db.Column(db.String(255))
    quoted_hours = db.Column(db.Float, default=0.0)


class WorkType(db.Model):
    __tablename__ = 'work_types'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<WorkType {self.name}>'


class MilestoneDefinition(db.Model):
    __tablename__ = 'milestone_definitions'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    percentage = db.Column(db.Float, nullable=False)  # Percentage of total project hours
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<MilestoneDefinition {self.name}>'


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
    machine_job_id = db.Column(
        db.Integer,
        db.ForeignKey("machine_jobs.id"),
        nullable=True
    )

    date = db.Column(db.Date)
    work_type = db.Column(db.String(100))
    hours = db.Column(db.Float, nullable=False)
    notes = db.Column(db.Text)

    machine_job = db.relationship("MachineJob", backref="time_entries")


class DailyActivityLog(db.Model):
    __tablename__ = "daily_activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    status = db.Column(db.String(50), default="Draft")
    total_hours = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    posted_at = db.Column(db.DateTime, nullable=True)

    entries = db.relationship(
        "DailyActivityEntry",
        backref="daily_log",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="DailyActivityEntry.entry_order",
    )
    postings = db.relationship(
        "DailyActivityPosting",
        backref="daily_log",
        lazy=True,
        cascade="all, delete-orphan",
    )


class DailyActivityEntry(db.Model):
    __tablename__ = "daily_activity_entries"

    id = db.Column(db.Integer, primary_key=True)
    daily_log_id = db.Column(
        db.Integer,
        db.ForeignKey("daily_activity_logs.id"),
        nullable=False
    )
    entry_order = db.Column(db.Integer, default=0)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    duration_hours = db.Column(db.Float, nullable=False, default=0.0)
    category = db.Column(db.String(50), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    machine_id = db.Column(db.Integer, db.ForeignKey("machines.id"), nullable=True)
    machine_job_id = db.Column(db.Integer, db.ForeignKey("machine_jobs.id"), nullable=True)
    subcategory = db.Column(db.String(255))
    adp_number = db.Column(db.String(50))
    notes = db.Column(db.Text)
    is_billable = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship("Project")
    machine = db.relationship("Machine")
    machine_job = db.relationship("MachineJob")


class DailyActivityPosting(db.Model):
    __tablename__ = "daily_activity_postings"

    id = db.Column(db.Integer, primary_key=True)
    daily_log_id = db.Column(
        db.Integer,
        db.ForeignKey("daily_activity_logs.id"),
        nullable=False
    )
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    machine_id = db.Column(db.Integer, db.ForeignKey("machines.id"), nullable=False)
    machine_job_id = db.Column(db.Integer, db.ForeignKey("machine_jobs.id"), nullable=False)
    category = db.Column(db.String(50), nullable=False, default="Project")
    duration_hours = db.Column(db.Float, nullable=False, default=0.0)
    notes_summary = db.Column(db.Text)
    time_entry_id = db.Column(db.Integer, db.ForeignKey("time_entries.id"), nullable=True)
    posted_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship("Project")
    machine = db.relationship("Machine")
    machine_job = db.relationship("MachineJob")
    time_entry = db.relationship("TimeEntry")


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


class MachineJob(db.Model):
    __tablename__ = "machine_jobs"

    id = db.Column(db.Integer, primary_key=True)
    parent_job_id = db.Column(db.Integer, db.ForeignKey("machine_jobs.id"), nullable=True)
    machine_id = db.Column(
        db.Integer,
        db.ForeignKey("machines.id"),
        nullable=False
    )
    work_type = db.Column(db.String(50), nullable=False)
    other_description = db.Column(db.String(255))
    version_number = db.Column(db.Integer, default=1)
    status = db.Column(db.String(50), default="N/S")
    due_date = db.Column(db.Date, nullable=True)

    report_cas_approval_date = db.Column(db.Date, nullable=True)
    report_sent_customer_date = db.Column(db.Date, nullable=True)
    report_sent_review_edb_date = db.Column(db.Date, nullable=True)
    released_in_edb_date = db.Column(db.Date, nullable=True)
    uploaded_s_drive_reports_date = db.Column(db.Date, nullable=True)
    uploaded_s_drive_jsa_date = db.Column(db.Date, nullable=True)
    uploaded_s_drive_photos_date = db.Column(db.Date, nullable=True)
    uploaded_s_drive_vizio_date = db.Column(db.Date, nullable=True)
    log_updated_date = db.Column(db.Date, nullable=True)

    report_cas_approval_na = db.Column(db.Boolean, default=False)
    report_sent_customer_na = db.Column(db.Boolean, default=False)
    report_sent_review_edb_na = db.Column(db.Boolean, default=False)
    released_in_edb_na = db.Column(db.Boolean, default=False)
    uploaded_s_drive_reports_na = db.Column(db.Boolean, default=False)
    uploaded_s_drive_jsa_na = db.Column(db.Boolean, default=False)
    uploaded_s_drive_photos_na = db.Column(db.Boolean, default=False)
    uploaded_s_drive_vizio_na = db.Column(db.Boolean, default=False)
    log_updated_na = db.Column(db.Boolean, default=False)

    quoted_hours = db.Column(db.Float, default=0.0)
    incurred_hours = db.Column(db.Float, default=0.0)

    parent_job = db.relationship(
        "MachineJob",
        remote_side=[id],
        foreign_keys=[parent_job_id],
        backref="versions",
        lazy=True,
    )

    @property
    def version_label(self) -> str:
        version_num = self.version_number or 1
        return f"V{version_num}.0"
