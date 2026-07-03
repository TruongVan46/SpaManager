from app import db
from models.invoice import Invoice
from models.appointment import Appointment
from datetime import datetime, date


def _coerce_report_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return value

class ReportService:
    @staticmethod
    def get_revenue_report(start_date, end_date):
        # Calculate total revenue within the date range
        start_date = _coerce_report_date(start_date)
        end_date = _coerce_report_date(end_date)
        revenue = db.session.query(db.func.sum(Invoice.total_amount)).filter(
            Invoice.invoice_date >= start_date,
            Invoice.invoice_date <= end_date
        ).scalar()
        return revenue if revenue else 0

    @staticmethod
    def get_appointments_by_status(start_date, end_date):
        # Count appointments by status within the date range
        start_date = _coerce_report_date(start_date)
        end_date = _coerce_report_date(end_date)
        appointments = Appointment.query.filter(
            db.func.date(Appointment.appointment_time) >= start_date,
            db.func.date(Appointment.appointment_time) <= end_date
        ).all()
        
        status_counts = {
            'Pending': 0,
            'Confirmed': 0,
            'Completed': 0,
            'Cancelled': 0
        }
        
        for appt in appointments:
            status_counts[appt.status] += 1
            
        return status_counts
