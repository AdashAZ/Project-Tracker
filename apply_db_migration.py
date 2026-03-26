#!/usr/bin/env python3
"""
Script to apply database schema migrations for the Project Tracker application.
Run this script if you encounter database schema issues.
"""

import os
import sys
from datetime import datetime

# Add the current directory to Python path so we can import models
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import db, Project
from app import create_app

def apply_migrations():
    """Apply database schema migrations"""
    app = create_app()
    
    with app.app_context():
        print("Applying database schema migrations...")
        
        # Import the migration functions
        from app import ensure_project_schema, ensure_machine_schema
        
        # Apply migrations
        ensure_project_schema()
        ensure_machine_schema()
        
        print("Database schema migrations applied successfully!")
        print("The created_at field has been added to existing projects.")
        print("You can now run the application normally.")

if __name__ == "__main__":
    apply_migrations()