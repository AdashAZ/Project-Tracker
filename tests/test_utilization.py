"""Run with python -B -m unittest discover -s tests -v; never uses the live DB."""
from datetime import date, timedelta
import json
import unittest
from unittest.mock import patch

from app import create_app, UTILIZATION_START_DATE, utilization_project_hours
from models import db, Project, Machine, MachineJob, DailyActivityLog, DailyActivityEntry


def create_test_app():
    original_init = db.init_app

    def init_memory(app):
        app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", TESTING=True)
        original_init(app)

    with patch.object(db, "init_app", side_effect=init_memory):
        return create_app()


class UtilizationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()
        self.project = Project(customer="Test", na_number="UTIL", status="WIP")
        self.machine = Machine(project=self.project, machine_name="Test machine")
        self.job = MachineJob(machine=self.machine, work_type="RA")
        db.session.add(self.project)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()

    def add_day(self, day, hours, status="Draft"):
        log = DailyActivityLog(date=day, status=status)
        log.entries.append(DailyActivityEntry(
            category="Project", duration_hours=hours, project_id=self.project.id,
            machine_id=self.machine.id, machine_job_id=self.job.id,
        ))
        db.session.add(log)
        db.session.commit()
        return log

    def test_cutoff_excludes_history_and_get_requests_preserve_entries(self):
        old = self.add_day(date(2026, 10, 16), 8, "Submitted")
        before = [tuple(row) for row in db.session.execute(db.text("SELECT * FROM daily_activity_entries"))]
        current = self.add_day(UTILIZATION_START_DATE, 6)
        self.assertEqual(utilization_project_hours([old, current]), 6)
        for path in ["/daily-activity?date=2026-10-16", "/daily-activity/week?date=2026-10-17"]:
            html = self.client.get(path).get_data(as_text=True)
            self.assertNotIn('class="utilization-card"', html)
        after = [tuple(row) for row in db.session.execute(
            db.text("SELECT * FROM daily_activity_entries WHERE daily_log_id=:id"), {"id": old.id}
        )]
        self.assertEqual(before, after)
        self.assertEqual(old.status, "Submitted")

    def test_only_assigned_project_hours_count(self):
        log = self.add_day(UTILIZATION_START_DATE, 6)
        for category in ["Admin", "INM", "Sales Support", "TCB111 - Competency Training",
                         "TCT333 - Certification Training", "Travel", "Other"]:
            log.entries.append(DailyActivityEntry(category=category, duration_hours=2,
                                                  project_id=self.project.id))
        log.entries.append(DailyActivityEntry(category="Project", duration_hours=4))
        db.session.commit()
        self.assertEqual(utilization_project_hours([log]), 6)
        html = self.client.get("/daily-activity?date=2026-10-26").get_data(as_text=True)
        self.assertIn('id="daily-utilization-percent">75</span>', html)
        self.assertIn('id="daily-utilization-hours">6.00</span> / 8', html)

    def test_daily_overtime_and_empty_dates(self):
        self.add_day(UTILIZATION_START_DATE, 10)
        html = self.client.get("/daily-activity?date=2026-10-26").get_data(as_text=True)
        self.assertIn('id="daily-utilization-percent">125</span>', html)
        html = self.client.get("/daily-activity?date=2026-10-27").get_data(as_text=True)
        self.assertIn('id="daily-utilization-percent">0</span>', html)
        html = self.client.get("/daily-activity/week?date=2026-11-02").get_data(as_text=True)
        self.assertIn("0.00 / 40 project hours", html)

    def test_week_fixed_baseline_drafts_submitted_weekends_and_boundaries(self):
        monday = UTILIZATION_START_DATE
        self.add_day(monday - timedelta(days=1), 20)
        self.add_day(monday + timedelta(days=7), 20)
        self.add_day(monday, 24)
        self.add_day(monday + timedelta(days=6), 8, "Submitted")
        url = "/daily-activity/week?date=2026-11-01"
        html = self.client.get(url).get_data(as_text=True)
        self.assertIn('<span>80</span><span class="utilization-symbol">%</span>', html)
        self.assertIn("32.00 / 40 project hours", html)
        extra = self.add_day(monday + timedelta(days=1), 16)
        html = self.client.get(url).get_data(as_text=True)
        self.assertIn('<span>120</span><span class="utilization-symbol">%</span>', html)
        db.session.delete(extra)
        db.session.commit()
        self.assertIn("32.00 / 40 project hours", self.client.get(url).get_data(as_text=True))

    def test_historical_missing_references_render_without_rewriting_entries(self):
        log = self.add_day(date(2026, 10, 16), 8, "Submitted")
        entry = log.entries[0]
        for project_id in [999999, None]:
            entry.project_id = project_id
            entry.machine_id = 999999
            entry.machine_job_id = 999999
            db.session.commit()
            before = [tuple(row) for row in db.session.execute(db.text("SELECT * FROM daily_activity_entries"))]
            for sort in ["grouped", "time"]:
                response = self.client.get(f"/daily-activity/week?date=2026-10-17&sort={sort}")
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn("Project 999999" if project_id else "Unassigned Project", html)
                self.assertNotIn('class="utilization-card"', html)
            after = [tuple(row) for row in db.session.execute(db.text("SELECT * FROM daily_activity_entries"))]
            self.assertEqual(before, after)

    def test_saving_editing_and_clearing_refreshes_utilization(self):
        with self.client.session_transaction() as session:
            session["_csrf_token"] = "test-token"
        for hours, expected in [(6, "15"), (10, "25")]:
            self.client.post("/daily-activity/save", data={
                "_csrf_token": "test-token", "date": "2026-10-26",
                "entries_payload": json.dumps([{
                    "category": "Project", "duration_hours": str(hours),
                    "project_id": str(self.project.id), "machine_id": str(self.machine.id),
                    "machine_job_id": str(self.job.id),
                }]),
            })
            html = self.client.get("/daily-activity/week?date=2026-10-26").get_data(as_text=True)
            self.assertIn(f'<span>{expected}</span><span class="utilization-symbol">%</span>', html)
        self.client.post("/daily-activity/clear", data={
            "_csrf_token": "test-token", "date": "2026-10-26",
        })
        html = self.client.get("/daily-activity/week?date=2026-10-26").get_data(as_text=True)
        self.assertIn("0.00 / 40 project hours", html)
