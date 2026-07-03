# services/dashboard_statistics_service.py
from datetime import date, datetime, time, timedelta
from extensions import db
from models.customer import Customer
from models.appointment import Appointment
from models.invoice import Invoice
from models.service import Service
from models.invoice_detail import InvoiceDetail
from models.activity_log import ActivityLog
from sqlalchemy import func, or_
from utils.timezone_utils import format_local_datetime, local_day_bounds, local_today


def _coerce_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _appointment_bounds_for_date_range(from_date=None, to_date=None):
    start_dt = None
    end_dt = None
    if from_date:
        start_dt = datetime.combine(from_date, time.min)
    if to_date:
        end_dt = datetime.combine(to_date, time.max)
    return start_dt, end_dt

class DashboardStatisticsService:
    @staticmethod
    def get_dashboard_data():
        """Retrieve all data required for the main dashboard widget display, excluding soft-deleted items."""
        from core.cache import dashboard_cache
        cached_data = dashboard_cache.get('dashboard_data')
        if cached_data is not None:
            return cached_data

        today = local_today()
        today_start, today_end = local_day_bounds(today)
        
        # 1. Tổng khách hàng (hoạt động)
        customers_count = db.session.query(func.count(Customer.id)).filter(Customer.deleted_at.is_(None)).scalar() or 0
        
        # 2. Tổng dịch vụ (hoạt động)
        services_count = db.session.query(func.count(Service.id)).filter(Service.deleted_at.is_(None)).scalar() or 0
        
        # 3. Lịch hẹn hôm nay (hoạt động)
        appointments_today_count = db.session.query(func.count(Appointment.id)).filter(
            Appointment.appointment_time >= today_start,
            Appointment.appointment_time <= today_end,
            Appointment.deleted_at.is_(None)
        ).scalar() or 0
        
        # 4. Hóa đơn hôm nay (hoạt động)
        invoices_today_count = db.session.query(func.count(Invoice.id)).filter(
            Invoice.invoice_date == today,
            Invoice.deleted_at.is_(None)
        ).scalar() or 0
        
        # 5. Doanh thu hôm nay (hoạt động)
        revenue_today = db.session.query(func.sum(Invoice.total_amount)).filter(
            Invoice.invoice_date == today,
            Invoice.deleted_at.is_(None)
        ).scalar() or 0
        formatted_revenue_today = f"{int(revenue_today):,}".replace(',', '.') + 'đ'
        
        # 6. Danh sách lịch hẹn hôm nay (hoạt động) - OPTIMIZED with Eager Loading (joinedload) to prevent N+1 queries
        appointments = Appointment.query.options(
            db.joinedload(Appointment.customer),
            db.joinedload(Appointment.service)
        ).filter(
            Appointment.appointment_time >= today_start,
            Appointment.appointment_time <= today_end,
            Appointment.deleted_at.is_(None)
        ).order_by(Appointment.appointment_time.asc()).all()
        
        status_map = {
            'Pending': 'Chờ xác nhận',
            'Confirmed': 'Đã xác nhận',
            'Completed': 'Đã hoàn thành',
            'Cancelled': 'Đã hủy'
        }
        
        recent_appointments = [
            {
                'time': appt.appointment_time.strftime('%H:%M %d/%m'),
                'customer': appt.customer.name if appt.customer else 'N/A',
                'service': appt.service.name if appt.service else 'N/A',
                'status': status_map.get(appt.status, appt.status)
            }
            for appt in appointments
        ]
        
        # 7. 5 hóa đơn mới nhất (hoạt động) - OPTIMIZED with Eager Loading (joinedload) to prevent N+1 queries
        latest_invoices_query = Invoice.query.options(
            db.joinedload(Invoice.customer)
        ).filter(
            Invoice.deleted_at.is_(None)
        ).order_by(Invoice.created_at.desc()).limit(5).all()
        
        latest_invoices = [
            {
                'id': inv.id,
                'customer': inv.customer.name if inv.customer else 'N/A',
                'total': f"{int(inv.total_amount):,}".replace(',', '.') + 'đ',
                'date': format_local_datetime(inv.created_at, assume_utc=True) if inv.created_at else 'N/A',
                'status': 'Hoàn thành'
            }
            for inv in latest_invoices_query
        ]
 
        # 8. Hoạt động gần đây (Recent Activities) lấy từ ActivityLog
        recent_logs = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(5).all()
        recent_activities = [
            {
                'module': log.module,
                'action': log.action,
                'description': log.description,
                'time': format_local_datetime(log.created_at, assume_utc=True) if log.created_at else 'N/A',
                'severity': log.severity
            }
            for log in recent_logs
        ]
        
        result_data = {
            'stats': {
                'revenue': {'label': 'Doanh thu hôm nay', 'value': formatted_revenue_today, 'icon': 'bi-cash-stack', 'color': 'text-primary'},
                'customers': {'label': 'Tổng khách hàng', 'value': str(customers_count), 'icon': 'bi-people', 'color': 'text-success'},
                'appointments': {'label': 'Lịch hẹn hôm nay', 'value': str(appointments_today_count), 'icon': 'bi-calendar-event', 'color': 'text-warning'},
                'invoices': {'label': 'Hóa đơn hôm nay', 'value': str(invoices_today_count), 'icon': 'bi-receipt', 'color': 'text-info'},
            },
            'services_count': services_count,
            'revenue_chart': DashboardStatisticsService.get_revenue_chart_data(),
            'today_appointments': recent_appointments,
            'latest_customers': [],
            'top_services': [],
            'latest_invoices': latest_invoices,
            'recent_activities': recent_activities,
            'notifications': [],
            'notes': []
        }
        
        dashboard_cache.set('dashboard_data', result_data)
        return result_data

    @staticmethod
    def get_revenue_chart_data():
        """Retrieve last 7 days revenue, excluding soft-deleted invoices."""
        today = local_today()
        labels = []
        values = []
        
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            labels.append(day.strftime('%d/%m'))
            
            # Tính tổng doanh thu theo invoice_date cho ngày đó
            rev = db.session.query(func.sum(Invoice.total_amount)).filter(
                Invoice.invoice_date == day,
                Invoice.deleted_at.is_(None)
            ).scalar() or 0
            values.append(float(rev))
            
        return {'labels': labels, 'values': values}

    @staticmethod
    def get_summary(from_date=None, to_date=None):
        """Retrieve overall summary numbers for stats calculations, excluding soft-deleted items."""
        # Revenue calculation (active only)
        from_date = _coerce_date(from_date)
        to_date = _coerce_date(to_date)

        rev_query = db.session.query(func.sum(Invoice.total_amount)).filter(Invoice.deleted_at.is_(None))
        if from_date:
            rev_query = rev_query.filter(Invoice.invoice_date >= from_date)
        if to_date:
            rev_query = rev_query.filter(Invoice.invoice_date <= to_date)
        revenue = rev_query.scalar() or 0

        # Invoice count calculation (active only)
        count_query = db.session.query(func.count(Invoice.id)).filter(Invoice.deleted_at.is_(None))
        if from_date:
            count_query = count_query.filter(Invoice.invoice_date >= from_date)
        if to_date:
            count_query = count_query.filter(Invoice.invoice_date <= to_date)
        invoice_count = count_query.scalar() or 0
        
        # Customer count calculation (active only)
        customer_count = db.session.query(func.count(Customer.id)).filter(Customer.deleted_at.is_(None)).scalar() or 0
        
        # Appointment count calculation (active only)
        app_query = db.session.query(func.count(Appointment.id)).filter(Appointment.deleted_at.is_(None))
        if from_date:
            app_query = app_query.filter(Appointment.appointment_time >= datetime.combine(from_date, time.min))
        if to_date:
            app_query = app_query.filter(Appointment.appointment_time <= datetime.combine(to_date, time.max))
        appointment_count = app_query.scalar() or 0
        
        return {
            "revenue": revenue,
            "invoice_count": invoice_count,
            "customer_count": customer_count,
            "appointment_count": appointment_count
        }

    @staticmethod
    def get_revenue_chart(from_date=None, to_date=None, group_by="day"):
        """Get revenue chart data, excluding soft-deleted invoices."""
        today = local_today()

        if hasattr(from_date, 'date'):
            from_date = from_date.date()
        if hasattr(to_date, 'date'):
            to_date = to_date.date()

        from_date = _coerce_date(from_date)
        to_date = _coerce_date(to_date)

        if group_by in ("month", "year"):
            if not to_date:
                max_date = db.session.query(func.max(Invoice.invoice_date)).filter(Invoice.deleted_at.is_(None)).scalar()
                to_date = max_date if max_date else today
            if not from_date:
                min_date = db.session.query(func.min(Invoice.invoice_date)).filter(Invoice.deleted_at.is_(None)).scalar()
                from_date = min_date if min_date else today
        else:
            if not to_date:
                to_date = today
            if not from_date:
                from_date = to_date - timedelta(days=29)

        # Query total revenue grouped by date within the range
        results = db.session.query(
            Invoice.invoice_date, 
            func.sum(Invoice.total_amount)
        ).filter(
            Invoice.invoice_date >= from_date,
            Invoice.invoice_date <= to_date,
            Invoice.deleted_at.is_(None)
        ).group_by(Invoice.invoice_date).all()

        labels = []
        values = []

        if group_by == "month":
            revenue_map = {}
            for d, rev in results:
                if rev is not None:
                    month_key = (d.year, d.month)
                    revenue_map[month_key] = revenue_map.get(month_key, 0.0) + float(rev)

            current_date = date(from_date.year, from_date.month, 1)
            end_normalized = date(to_date.year, to_date.month, 1)
            while current_date <= end_normalized:
                label = current_date.strftime("%m/%Y")
                labels.append(label)
                month_key = (current_date.year, current_date.month)
                values.append(revenue_map.get(month_key, 0.0))

                if current_date.month == 12:
                    current_date = date(current_date.year + 1, 1, 1)
                else:
                    current_date = date(current_date.year, current_date.month + 1, 1)

        elif group_by == "year":
            revenue_map = {}
            for d, rev in results:
                if rev is not None:
                    year_key = d.year
                    revenue_map[year_key] = revenue_map.get(year_key, 0.0) + float(rev)

            current_year = from_date.year
            end_year = to_date.year
            while current_year <= end_year:
                label = str(current_year)
                labels.append(label)
                values.append(revenue_map.get(current_year, 0.0))
                current_year += 1

        else:
            revenue_map = {d: (float(rev) if rev is not None else 0.0) for d, rev in results}

            current_date = from_date
            while current_date <= to_date:
                labels.append(current_date.strftime("%d/%m"))
                values.append(revenue_map.get(current_date, 0.0))
                current_date += timedelta(days=1)

        return {"labels": labels, "values": values}

    @staticmethod
    def get_customer_statistics(from_date=None, to_date=None, keyword=None):
        """Retrieve customer sales rankings, excluding soft-deleted customers and invoices."""
        query = db.session.query(
            Customer.id,
            Customer.name,
            Customer.phone,
            func.count(Invoice.id),
            func.sum(Invoice.total_amount)
        ).join(Invoice, Invoice.customer_id == Customer.id).filter(
            Customer.deleted_at.is_(None),
            Invoice.deleted_at.is_(None)
        )

        if keyword:
            keyword = f"%{keyword.strip()}%"
            query = query.filter(
                or_(
                    Customer.name.ilike(keyword),
                    Customer.phone.ilike(keyword)
                )
            )

        if from_date:
            query = query.filter(Invoice.invoice_date >= from_date)
        if to_date:
            query = query.filter(Invoice.invoice_date <= to_date)

        results = query.group_by(
            Customer.id, 
            Customer.name, 
            Customer.phone
        ).order_by(func.sum(Invoice.total_amount).desc()).all()

        return [
            {
                "id": row[0],
                "name": row[1],
                "phone": row[2],
                "invoice_count": row[3],
                "total_spent": row[4] or 0
            }
            for row in results
        ]

    @staticmethod
    def get_service_statistics(from_date=None, to_date=None, keyword=None):
        """Retrieve service performance stats, excluding soft-deleted services and invoices."""
        query = db.session.query(
            Service.id,
            Service.name,
            func.sum(InvoiceDetail.quantity),
            func.sum(InvoiceDetail.price * InvoiceDetail.quantity)
        ).join(InvoiceDetail, InvoiceDetail.service_id == Service.id) \
         .join(Invoice, InvoiceDetail.invoice_id == Invoice.id).filter(
             Service.deleted_at.is_(None),
             Invoice.deleted_at.is_(None)
         )

        if keyword:
            keyword = f"%{keyword.strip()}%"
            query = query.filter(Service.name.ilike(keyword))

        if from_date:
            query = query.filter(Invoice.invoice_date >= from_date)
        if to_date:
            query = query.filter(Invoice.invoice_date <= to_date)

        results = query.group_by(Service.id, Service.name) \
                       .order_by(func.sum(InvoiceDetail.price * InvoiceDetail.quantity).desc()) \
                       .all()

        return [
            {
                "service_id": row[0],
                "service_name": row[1],
                "quantity_sold": row[2] or 0,
                "revenue": row[3] or 0.0
            }
            for row in results
        ]

    @staticmethod
    def get_service_invoice_details(service_id, from_date=None, to_date=None):
        """Get invoice lines for a service, excluding soft-deleted invoices/customers."""
        query = db.session.query(
            InvoiceDetail.invoice_id,
            Invoice.invoice_date,
            Customer.name.label('customer_name'),
            InvoiceDetail.quantity,
            InvoiceDetail.price,
            Invoice.total_amount.label('invoice_total')
        ).join(Invoice, InvoiceDetail.invoice_id == Invoice.id) \
         .join(Customer, Invoice.customer_id == Customer.id) \
         .filter(
             InvoiceDetail.service_id == service_id,
             Invoice.deleted_at.is_(None),
             Customer.deleted_at.is_(None)
         )

        if from_date:
            query = query.filter(Invoice.invoice_date >= from_date)
        if to_date:
            query = query.filter(Invoice.invoice_date <= to_date)

        results = query.order_by(Invoice.invoice_date.desc()).all()

        service_invoices = []
        for row in results:
            invoice_id = row[0]
            service_invoices.append({
                "invoice_id": invoice_id,
                "invoice_code": f"HD{invoice_id}",
                "invoice_date": row[1],
                "customer_name": row[2],
                "quantity": row[3],
                "price": row[4],
                "line_total": row[3] * row[4],
                "invoice_total": row[5]
            })

        return service_invoices

    @staticmethod
    def get_customer_invoice_statistics(customer_id, from_date=None, to_date=None):
        """Get total invoices for a customer, excluding soft-deleted records."""
        customer = Customer.query.filter(Customer.id == customer_id, Customer.deleted_at.is_(None)).first()
        if not customer:
            return None

        query = Invoice.query.filter(Invoice.customer_id == customer_id, Invoice.deleted_at.is_(None))
        if from_date:
            query = query.filter(Invoice.invoice_date >= from_date)
        if to_date:
            query = query.filter(Invoice.invoice_date <= to_date)
        
        invoices = query.all()
        
        total_spent = sum(invoice.total_amount for invoice in invoices)
        invoice_count = len(invoices)
        
        return {
            "customer": customer,
            "invoices": invoices,
            "summary": {
                "invoice_count": invoice_count,
                "total_spent": total_spent
            }
        }

    @staticmethod
    def get_customer_statistics_paginated(from_date=None, to_date=None, page=1, per_page=25, sort_by='total_spent', order='desc', keyword=None):
        """Retrieve paginated customer sales rankings."""

        query = db.session.query(
            Customer.id,
            Customer.name,
            Customer.phone,
            func.count(Invoice.id).label('invoice_count'),
            func.sum(Invoice.total_amount).label('total_spent')
        ).join(Invoice, Invoice.customer_id == Customer.id).filter(
            Customer.deleted_at.is_(None),
            Invoice.deleted_at.is_(None)
        )
        if keyword:
            keyword = f"%{keyword.strip()}%"
            query = query.filter(
                or_(
                    Customer.name.ilike(keyword),
                    Customer.phone.ilike(keyword)
                )
            )
        if from_date:
            query = query.filter(Invoice.invoice_date >= from_date)
        if to_date:
            query = query.filter(Invoice.invoice_date <= to_date)
            
        query = query.group_by(Customer.id, Customer.name, Customer.phone)
        
        # Sort key map
        sort_fields = {
            'name': Customer.name,
            'phone': Customer.phone,
            'invoice_count': func.count(Invoice.id),
            'total_spent': func.sum(Invoice.total_amount)
        }
        sort_col = sort_fields.get(sort_by, func.sum(Invoice.total_amount))
        if order == 'desc':
            query = query.order_by(sort_col.desc())
        else:
            query = query.order_by(sort_col.asc())
            
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        pagination.items = [
            {
                "id": row[0],
                "name": row[1],
                "phone": row[2],
                "invoice_count": row[3],
                "total_spent": row[4] or 0
            }
            for row in pagination.items
        ]
        return pagination

    @staticmethod
    def get_service_statistics_paginated(from_date=None, to_date=None, page=1, per_page=25, sort_by='revenue', order='desc', keyword=None):
        """Retrieve paginated service performance stats."""

        query = db.session.query(
            Service.id,
            Service.name,
            func.sum(InvoiceDetail.quantity).label('quantity_sold'),
            func.sum(InvoiceDetail.price * InvoiceDetail.quantity).label('revenue')
        ).join(InvoiceDetail, InvoiceDetail.service_id == Service.id) \
         .join(Invoice, InvoiceDetail.invoice_id == Invoice.id).filter(
             Service.deleted_at.is_(None),
             Invoice.deleted_at.is_(None)
         )
        if keyword:
            keyword = f"%{keyword.strip()}%"
            query = query.filter(Service.name.ilike(keyword))
        if from_date:
            query = query.filter(Invoice.invoice_date >= from_date)
        if to_date:
            query = query.filter(Invoice.invoice_date <= to_date)
            
        query = query.group_by(Service.id, Service.name)
        
        sort_fields = {
            'service_name': Service.name,
            'quantity_sold': func.sum(InvoiceDetail.quantity),
            'revenue': func.sum(InvoiceDetail.price * InvoiceDetail.quantity)
        }
        sort_col = sort_fields.get(sort_by, func.sum(InvoiceDetail.price * InvoiceDetail.quantity))
        if order == 'desc':
            query = query.order_by(sort_col.desc())
        else:
            query = query.order_by(sort_col.asc())
            
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        pagination.items = [
            {
                "service_id": row[0],
                "service_name": row[1],
                "quantity_sold": row[2] or 0,
                "revenue": row[3] or 0.0
            }
            for row in pagination.items
        ]
        return pagination
