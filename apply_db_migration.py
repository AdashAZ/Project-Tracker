#!/usr/bin/env python3
"""
Run this script when you get schema errors (especially parent_job_id).
It safely adds missing columns without losing data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from models import db

def apply_migrations():
    app = create_app()
    with app.app_context():
        print("Applying database schema migrations...")

        from app import (
            ensure_project_schema,
            ensure_machine_schema,
            ensure_machine_job_schema,
        )

        ensure_project_schema()
        ensure_machine_schema()
        ensure_machine_job_schema()   # ← This now also adds parent_job_id

        print("✅ All schema migrations applied successfully!")
        print("You can now run the app normally.")

if __name__ == "__main__":
    apply_migrations()