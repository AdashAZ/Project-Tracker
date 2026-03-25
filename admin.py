import os
import sqlite3
import shutil
import csv
import json
import logging
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, send_file
from flask_wtf.csrf import validate_csrf
from werkzeug.exceptions import BadRequest
from functools import wraps
from models import db, Project, Machine, TimeEntry, Comment, ProductLine, WorkType, MilestoneDefinition

def csrf_exempt(f):
    """Decorator to exempt a route from CSRF protection"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Skip CSRF validation for JSON API endpoints
        content_type = request.headers.get('Content-Type', '')
        if 'application/json' in content_type:
            return f(*args, **kwargs)
        # For non-JSON requests, validate CSRF as normal
        try:
            validate_csrf(request.headers.get('X-CSRFToken'))
        except BadRequest:
            return jsonify({'success': False, 'message': 'CSRF token missing or invalid'}), 400
        return f(*args, **kwargs)
    return decorated_function

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('admin.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Create backup directory if it doesn't exist
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Backup')
os.makedirs(BACKUP_DIR, exist_ok=True)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def get_db_size():
    """Get the size of the database file in MB"""
    try:
        # Try to get database path from current_app context
        from flask import current_app
        db_path = current_app.config.get('DATABASE', 'instance/app.db')
        if os.path.exists(db_path):
            size_bytes = os.path.getsize(db_path)
            size_mb = size_bytes / (1024 * 1024)
            return round(size_mb, 2)
        return 0
    except Exception as e:
        logger.error(f"Error getting database size: {e}")
        return 0

def get_last_backup_info():
    """Get information about the last backup"""
    try:
        backup_files = [f for f in os.listdir(BACKUP_DIR) if f.startswith('backup_') and f.endswith('.db')]
        if not backup_files:
            return None
        
        # Sort by modification time, get the most recent
        backup_files.sort(key=lambda x: os.path.getmtime(os.path.join(BACKUP_DIR, x)), reverse=True)
        latest_backup = backup_files[0]
        backup_path = os.path.join(BACKUP_DIR, latest_backup)
        
        backup_time = datetime.fromtimestamp(os.path.getmtime(backup_path))
        backup_size = round(os.path.getsize(backup_path) / (1024 * 1024), 2)
        
        return {
            'filename': latest_backup,
            'time': backup_time.strftime('%Y-%m-%d %H:%M:%S'),
            'size_mb': backup_size
        }
    except Exception as e:
        logger.error(f"Error getting last backup info: {e}")
        return None

def get_system_stats():
    """Get system statistics"""
    try:
        stats = {
            'total_projects': Project.query.count(),
            'total_machines': Machine.query.count(),
            'total_time_entries': TimeEntry.query.count(),
            'total_comments': Comment.query.count(),
            'total_product_lines': ProductLine.query.count(),
            'total_work_types': WorkType.query.count(),
            'db_size_mb': get_db_size(),
            'last_backup': get_last_backup_info()
        }
        return stats
    except Exception as e:
        logger.error(f"Error getting system stats: {e}")
        return {}

def backup_database():
    """Create a backup of the database"""
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d')
        backup_filename = f'backup_{timestamp}.db'
        backup_path = os.path.join(BACKUP_DIR, backup_filename)
        
        # Copy the database file
        from flask import current_app
        db_path = current_app.config.get('DATABASE', 'instance/app.db')
        shutil.copy2(db_path, backup_path)
        
        logger.info(f"Database backup created: {backup_filename}")
        return backup_filename
    except Exception as e:
        logger.error(f"Error creating database backup: {e}")
        raise

def restore_database(backup_filename):
    """Restore database from backup"""
    try:
        backup_path = os.path.join(BACKUP_DIR, backup_filename)
        from flask import current_app
        db_path = current_app.config.get('DATABASE', 'instance/app.db')
        
        # Create a backup of current database before restoring
        current_backup = backup_database()
        logger.info(f"Current database backed up before restore: {current_backup}")
        
        # Restore from backup
        shutil.copy2(backup_path, db_path)
        
        logger.info(f"Database restored from: {backup_filename}")
        return True
    except Exception as e:
        logger.error(f"Error restoring database: {e}")
        raise

def export_to_csv():
    """Export all tables to CSV files"""
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        export_dir = os.path.join(BACKUP_DIR, f'export_{timestamp}')
        os.makedirs(export_dir, exist_ok=True)
        
        tables = [
            ('projects', Project),
            ('machines', Machine),
            ('time_entries', TimeEntry),
            ('comments', Comment),
            ('product_lines', ProductLine),
            ('work_types', WorkType),
            ('milestone_definitions', MilestoneDefinition)
        ]
        
        exported_files = []
        
        for table_name, model in tables:
            csv_path = os.path.join(export_dir, f'{table_name}.csv')
            
            # Get all records
            records = model.query.all()
            
            if records:
                # Get field names from the first record
                fieldnames = [column.name for column in model.__table__.columns]
                
                with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    
                    for record in records:
                        # Convert record to dictionary
                        row_data = {}
                        for field in fieldnames:
                            value = getattr(record, field)
                            # Handle datetime objects
                            if hasattr(value, 'isoformat'):
                                value = value.isoformat()
                            row_data[field] = value
                        writer.writerow(row_data)
                
                exported_files.append(f'{table_name}.csv')
        
        # Create a zip file of all CSV files
        zip_path = os.path.join(BACKUP_DIR, f'export_{timestamp}.zip')
        shutil.make_archive(zip_path[:-4], 'zip', export_dir)
        
        # Clean up the export directory
        shutil.rmtree(export_dir)
        
        logger.info(f"CSV export created: export_{timestamp}.zip")
        return f'export_{timestamp}.zip'
    except Exception as e:
        logger.error(f"Error exporting to CSV: {e}")
        raise

def get_backup_files():
    """Get list of all backup files"""
    try:
        backup_files = []
        for filename in os.listdir(BACKUP_DIR):
            if filename.endswith('.db') and filename.startswith('backup_'):
                filepath = os.path.join(BACKUP_DIR, filename)
                file_stat = os.stat(filepath)
                backup_files.append({
                    'filename': filename,
                    'size_mb': round(file_stat.st_size / (1024 * 1024), 2),
                    'created': datetime.fromtimestamp(file_stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
                })
        
        # Sort by creation time (newest first)
        backup_files.sort(key=lambda x: x['created'], reverse=True)
        return backup_files
    except Exception as e:
        logger.error(f"Error getting backup files: {e}")
        return []

def get_export_files():
    """Get list of all export files"""
    try:
        export_files = []
        for filename in os.listdir(BACKUP_DIR):
            if filename.endswith('.zip') and filename.startswith('export_'):
                filepath = os.path.join(BACKUP_DIR, filename)
                file_stat = os.stat(filepath)
                export_files.append({
                    'filename': filename,
                    'size_mb': round(file_stat.st_size / (1024 * 1024), 2),
                    'created': datetime.fromtimestamp(file_stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
                })
        
        # Sort by creation time (newest first)
        export_files.sort(key=lambda x: x['created'], reverse=True)
        return export_files
    except Exception as e:
        logger.error(f"Error getting export files: {e}")
        return []

@admin_bp.route('/')
def admin_dashboard():
    """Admin dashboard page"""
    stats = get_system_stats()
    backup_files = get_backup_files()
    export_files = get_export_files()
    
    return render_template('admin.html', 
                         stats=stats, 
                         backup_files=backup_files,
                         export_files=export_files)

@admin_bp.route('/backup', methods=['POST'])
@csrf_exempt
def create_backup():
    """Create a database backup"""
    try:
        backup_filename = backup_database()
        return jsonify({
            'success': True,
            'message': f'Database backup created successfully: {backup_filename}',
            'filename': backup_filename
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error creating backup: {str(e)}'
        }), 500

@admin_bp.route('/restore', methods=['POST'])
@csrf_exempt
def restore_backup():
    """Restore database from backup"""
    try:
        backup_filename = request.json.get('filename')
        if not backup_filename:
            return jsonify({
                'success': False,
                'message': 'No backup file specified'
            }), 400
        
        restore_database(backup_filename)
        return jsonify({
            'success': True,
            'message': f'Database restored successfully from: {backup_filename}'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error restoring backup: {str(e)}'
        }), 500

@admin_bp.route('/export', methods=['POST'])
@csrf_exempt
def export_data():
    """Export data to CSV"""
    try:
        zip_filename = export_to_csv()
        return jsonify({
            'success': True,
            'message': f'Data exported successfully: {zip_filename}',
            'filename': zip_filename
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error exporting data: {str(e)}'
        }), 500

@admin_bp.route('/download/<filename>')
def download_file(filename):
    """Download backup or export file"""
    try:
        file_path = os.path.join(BACKUP_DIR, filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            return jsonify({'success': False, 'message': 'File not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error downloading file: {str(e)}'}), 500

@admin_bp.route('/delete_backup/<filename>', methods=['POST'])
@csrf_exempt
def delete_backup(filename):
    """Delete a backup file"""
    try:
        file_path = os.path.join(BACKUP_DIR, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return jsonify({
                'success': True,
                'message': f'Backup file deleted: {filename}'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'File not found'
            }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error deleting backup: {str(e)}'
        }), 500

@admin_bp.route('/delete_export/<filename>', methods=['POST'])
@csrf_exempt
def delete_export(filename):
    """Delete an export file"""
    try:
        file_path = os.path.join(BACKUP_DIR, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return jsonify({
                'success': True,
                'message': f'Export file deleted: {filename}'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'File not found'
            }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error deleting export: {str(e)}'
        }), 500

@admin_bp.route('/logs')
def view_logs():
    """View admin logs"""
    try:
        log_file = 'admin.log'
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                logs = f.read()
        else:
            logs = "No logs available."
        
        return render_template('admin_logs.html', logs=logs)
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error reading logs: {str(e)}'}), 500

@admin_bp.route('/clear_logs', methods=['POST'])
def clear_logs():
    """Clear admin logs"""
    try:
        log_file = 'admin.log'
        if os.path.exists(log_file):
            with open(log_file, 'w') as f:
                f.write('')
            logger.info("Admin logs cleared")
            return jsonify({
                'success': True,
                'message': 'Logs cleared successfully'
            })
        else:
            return jsonify({
                'success': True,
                'message': 'No logs to clear'
            })
    except Exception as e:
        logger.error(f"Error clearing logs: {e}")
        return jsonify({
            'success': False,
            'message': f'Error clearing logs: {str(e)}'
        }), 500
