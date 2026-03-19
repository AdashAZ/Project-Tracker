**# Project Tracker**

A lightweight, web-based Flask application for managing engineering/manufacturing projects, including machines/assets, milestones, comments, and detailed labor tracking.

**Live demo not available** — self-hosted on your local machine with automatic SQLite database setup.

## Description

**Project Tracker** helps teams track the full lifecycle of projects: from quoting hours and adding machines/assets, through milestone dates, to logging actual work.

**Hours worked on task/job tracking** is a core feature. The app uses a dedicated **TimeEntry** system where you log hours against specific **tasks/jobs** (via the `work_type` field). Each entry records the date, hours spent, optional machine/asset link, and notes. These entries automatically roll up into per-machine and project-level "incurred hours" totals, giving you real-time visibility into progress against quoted hours (with % used and remaining balance calculations). You can add, edit, or delete time entries directly in the project detail view — perfect for daily timesheet-style job tracking.

## Main Features

- **Dashboard** — Overview of all projects with status filtering (N/S, WIP, Stopped, In Review, Completed). Shows key metrics: quoted hours, incurred hours, % done, days left to due date, and clickable links to details.
- **Project Management** — Create, edit, update status, or delete projects. Fields include customer, location, product line, due date, quoted hours total, and status.
- **Machines / Assets** — Add unlimited machines per project. Track per-machine: status, quoted/incurred hours, balance, version, NCTP flag, and four custom milestones (CAS approval, sent to customer, EDB review, released in EDB) with one-click "set today" buttons.
- **Time Tracking (Hours on Tasks/Jobs)** — Log labor hours with date, work type (your task/job name), hours, notes, and optional machine link. Full CRUD (add/edit/delete). Hours instantly contribute to project and machine totals.
- **Comments** — Project- or machine-level notes with author and date. Windows file paths (e.g. `C:\path\to\file`) become clickable links that open directly in File Explorer.
- **Milestone & Status Management** — Quick updates for machine status or milestone dates. Project status updates too.
- **Automatic Calculations** — Incurred hours, % used, balance hours, and days left are computed live.
- **Data Persistence** — SQLite database (auto-created in `/instance/app.db`) with full relationships and cascading deletes.
- **UI/UX** — Clean table-based interface with inline editing, flash messages, CSRF protection, and responsive design.

## Technologies Used

- **Backend**: Flask + Flask-SQLAlchemy
- **Database**: SQLite (local, no setup required)
- **Frontend**: HTML templates + CSS + JavaScript (inline editing, no heavy frameworks)
- **Other**: Standard library (datetime, subprocess for path opening, etc.)

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/AdashAZ/Project-Tracker.git
   cd Project-Tracker
   ```

2. (Recommended) Create and activate a virtual environment:
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   (Only `flask` and `flask_sqlalchemy` are required.)

4. The database and folders (`instance/`) will be created automatically on first run.

## How to Run

1. Start the server:
   ```bash
   flask --app app run
   ```
   For development with debugger:
   ```bash
   flask --app app run --debug
   ```

2. Open your browser and go to **http://127.0.0.1:5000**

3. You’ll land on the dashboard. Click **New Project** to get started!

> **Tip**: The app uses Flask’s application factory pattern (`create_app()`). If you prefer, you can add this at the bottom of `app.py` for direct `python app.py` execution:
> ```python:disable-run
> if __name__ == "__main__":
>     app = create_app()
>     app.run(debug=True)
> ```

## Usage Quick Start

- **Dashboard** → Filter by status or click any project.
- **Project Detail** → Add machines, log time entries (your "hours worked on task/job"), set milestones, or add comments.
- All changes save instantly to the local database.

## Legacy CSV Backfill (Dry Run + Import)

Use the one-time importer script for historical projects exported from older spreadsheets.

1. Dry run preview (no DB writes):
   ```bash
   python scripts/import_legacy_csv_project.py --csv "C:\path\legacy.csv"
   ```

2. Apply import:
   ```bash
   python scripts/import_legacy_csv_project.py --csv "C:\path\legacy.csv" --apply
   ```

3. Optional overrides:
   ```bash
   python scripts/import_legacy_csv_project.py \
     --csv "C:\path\legacy.csv" \
     --customer "SICK" \
     --machine-name "Press 3 & 4" \
     --status "Completed" \
     --apply
   ```

## Folder Structure (key files)

- `app.py` — Main Flask app with all routes and logic
- `models.py` — SQLAlchemy models (Project, Machine, TimeEntry, Comment)
- `templates/` — HTML views (`dashboard.html`, `project_detail.html`, etc.)
- `static/` — CSS/JS assets
- `instance/app.db` — Your data (auto-generated)

## Contributing

Fork the repo, make changes, and submit a pull request. New features (export to CSV, user auth, etc.) are welcome!

---

**Ready to track your projects and hours?** Clone it, run it, and start logging those task/job hours today! 🚀

(Originally created by AdashAZ — feel free to star the repo on GitHub if you find it useful.)
```
