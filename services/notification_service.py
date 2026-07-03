# services/notification_service.py
from flask import flash

class NotificationService:
    @staticmethod
    def flash_success(message):
        """Send a success flash notification to the frontend."""
        flash(message, 'success')

    @staticmethod
    def flash_error(message):
        """Send an error flash notification to the frontend."""
        flash(message, 'danger')

    @staticmethod
    def flash_warning(message):
        """Send a warning flash notification to the frontend."""
        flash(message, 'warning')

    @staticmethod
    def flash_info(message):
        """Send an info flash notification to the frontend."""
        flash(message, 'info')
