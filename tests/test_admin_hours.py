"""Admin hour totals, tested against an isolated in-memory database."""
from datetime import date
import unittest

from admin import get_project_hours_summary
from models import db, Project, TimeEntry, DailyActivityLog, DailyActivityPosting
from test_utilization import create_test_app


class AdminHoursTests(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()

    def add_project(self, status, quoted, hours):
        # Cached incurred values deliberately differ from the actual time records.
        project = Project(customer="Test", status=status, quoted_hours_total=quoted,
                          incurred_hours_total=9999)
        db.session.add(project)
        db.session.flush()
        for duration in hours:
            db.session.add(TimeEntry(project_id=project.id, date=date(2026, 10, 26), hours=duration))
        db.session.commit()
        return project

    def test_empty_portfolio_and_null_quotes(self):
        expected = {"quoted_hours": 0, "incurred_hours": 0, "remaining_hours": 0}
        self.assertEqual(get_project_hours_summary(), expected)
        project = self.add_project("WIP", 0, [])
        db.session.execute(db.text("UPDATE projects SET quoted_hours_total=NULL WHERE id=:id"), {"id": project.id})
        db.session.commit()
        self.assertEqual(get_project_hours_summary(), expected)
        self.assertEqual(self.app.test_client().get("/admin/").status_code, 200)

    def test_completed_excluded_and_totals_update_when_status_changes(self):
        active = self.add_project("WIP", 100, [10, 15])
        self.add_project("Stopped", 30, [5])
        self.add_project("In Review", 20, [2.5])
        self.add_project("N/S", 10, [])
        self.add_project("Completed", 500, [400])
        self.assertEqual(get_project_hours_summary(), {
            "quoted_hours": 160, "incurred_hours": 32.5, "remaining_hours": 127.5,
        })
        active.status = "Completed"
        db.session.commit()
        self.assertEqual(get_project_hours_summary(), {
            "quoted_hours": 60, "incurred_hours": 7.5, "remaining_hours": 52.5,
        })
        html = self.app.test_client().get("/admin/").get_data(as_text=True)
        self.assertIn('id="admin-remaining-hours">52.50<span>h</span>', html)
        active.status = "WIP"
        db.session.commit()
        self.assertEqual(get_project_hours_summary()["remaining_hours"], 127.5)

    def test_over_budget_project_contributes_zero_remaining_hours(self):
        self.add_project("WIP", 10.25, [6, 7.5])
        self.assertEqual(get_project_hours_summary(), {
            "quoted_hours": 10.25, "incurred_hours": 13.5, "remaining_hours": 0,
        })
        html = self.app.test_client().get("/admin/").get_data(as_text=True)
        self.assertIn('id="admin-remaining-hours">0.00<span>h</span>', html)

    def test_overruns_do_not_reduce_other_projects_remaining_hours(self):
        self.add_project("WIP", 10, [25])
        self.add_project("In Review", 100, [20, 30])
        self.add_project("N/S", 5, [])
        self.add_project("Stopped", 8, [8])
        self.add_project("Completed", 500, [10])
        self.assertEqual(get_project_hours_summary(), {
            "quoted_hours": 123, "incurred_hours": 83, "remaining_hours": 55,
        })

    def test_pending_postings_match_project_page_counting(self):
        project = self.add_project("WIP", 100, [8, 4])
        entry = TimeEntry.query.filter_by(project_id=project.id, hours=8).one()
        log = DailyActivityLog(date=date(2026, 10, 26), status="Needs Review")
        db.session.add(log)
        db.session.flush()
        db.session.add(DailyActivityPosting(
            daily_log_id=log.id, project_id=project.id, machine_id=999,
            machine_job_id=999, duration_hours=8, time_entry_id=entry.id,
        ))
        db.session.commit()
        self.assertEqual(get_project_hours_summary()["incurred_hours"], 4)
        log.status = "Submitted"
        db.session.commit()
        self.assertEqual(get_project_hours_summary()["incurred_hours"], 12)

    def test_missing_projects_and_stale_posting_links_do_not_distort_totals(self):
        project = self.add_project("WIP", 100, [8])
        entry = TimeEntry.query.filter_by(project_id=project.id).one()
        log = DailyActivityLog(date=date(2026, 10, 26), status="Draft")
        db.session.add(log)
        db.session.flush()
        db.session.add(DailyActivityPosting(
            daily_log_id=log.id, project_id=999, machine_id=999,
            machine_job_id=999, duration_hours=8, time_entry_id=entry.id,
        ))
        db.session.add(TimeEntry(project_id=999, hours=500))
        db.session.commit()
        self.assertEqual(get_project_hours_summary()["incurred_hours"], 8)
