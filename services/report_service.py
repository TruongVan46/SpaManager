from app import db
from models.invoice import Invoice
from models.appointment import Appointment

class ReportService:
    @staticmethod
    def get_revenue_report(start_date, end_date):
        # Calculate total revenue within the date range
        revenue = db.session.query(db.func.sum(Invoice.total_amount)).filter(
            Invoice.created_at >= start_date,
            Invoice.created_at <= end_date
        ).scalar()
        return revenue if revenue else 0

    @staticmethod
    def get_appointments_by_status(start_date, end_date):
        # Count appointments by status within the date range
        appointments = Appointment.query.filter(
            Appointment.appointment_time >= start_date,
            Appointment.appointment_time <= end_date
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