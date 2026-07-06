import calendar
from datetime import datetime, timedelta

from sqlalchemy import or_, func

from extensions import db
from models.appointment import Appointment
from models.customer import Customer
from models.service import Service
from core.exceptions import ConflictException, ValidationException, NotFoundException
from core.cache import dashboard_cache
from services.auth_service import AuthService
from validators.appointment_validator import AppointmentValidator
from services.activity_log_service import ActivityLogService
from utils.timezone_utils import local_now_naive, local_today, utc_now

class AppointmentService:
    STATUS_DISPLAY_LABELS = {
        "pending": "Chờ xử lý",
        "confirmed": "Đã xác nhận",
        "completed": "Hoàn thành",
        "cancelled": "Đã hủy",
        "canceled": "Đã hủy",
        "no_show": "Không đến",
        "noshow": "Không đến",
    }

    @staticmethod
    def _normalize_status(status):
        return (status or "").strip().lower()

    @staticmethod
    def _status_display_label(status):
        normalized = AppointmentService._normalize_status(status)
        if not normalized or normalized == "none":
            return "Không rõ"
        return AppointmentService.STATUS_DISPLAY_LABELS.get(normalized, status if status else "Không rõ")

    @staticmethod
    def _attach_flags(appt):
        if not appt or not appt.appointment_time:
            appt.is_today = False
            appt.is_upcoming = False
            appt.is_overdue = False
            if appt:
                appt.display_status = AppointmentService._status_display_label(appt.status)
            return

        now = local_now_naive()
        today = now.date()
        appt.is_today = (appt.appointment_time.date() == today)
        status_key = AppointmentService._normalize_status(appt.status)
        appt.display_status = AppointmentService._status_display_label(appt.status)

        if appt.is_today and status_key in ['pending', 'confirmed']:
            time_diff = (appt.appointment_time - now).total_seconds()
            appt.is_upcoming = (0 <= time_diff <= 30 * 60)
        else:
            appt.is_upcoming = False

        if appt.is_today and status_key not in ['completed', 'cancelled', 'canceled']:
            appt.is_overdue = (now > appt.appointment_time)
        else:
            appt.is_overdue = False

    @staticmethod
    def get_all():
        from services.workspace_service import WorkspaceService
        appointments = WorkspaceService.scoped_query(Appointment).filter(Appointment.deleted_at.is_(None)).all()
        for appt in appointments:
            AppointmentService._attach_flags(appt)
        return appointments

    @staticmethod
    def get_by_id(appointment_id):
        from services.workspace_service import WorkspaceService
        appt = WorkspaceService.scoped_query(Appointment).filter(Appointment.id == appointment_id, Appointment.deleted_at.is_(None)).first()
        if appt:
            AppointmentService._attach_flags(appt)
        return appt

    @staticmethod
    def create_appointment(customer_id, service_id, appointment_date, appointment_time=None, notes=None, status='Pending'):
        # Normalize combined formats (e.g., datetime objects or "dateTtime" strings)
        if appointment_time is None:
            if isinstance(appointment_date, datetime):
                dt_obj = appointment_date
                appointment_date = dt_obj.strftime('%Y-%m-%d')
                appointment_time = dt_obj.strftime('%H:%M')
            elif isinstance(appointment_date, str):
                combined = appointment_date.strip()
                if 'T' in combined:
                    appointment_date, appointment_time = combined.split('T')
                elif ' ' in combined:
                    appointment_date, appointment_time = combined.split(' ')
                else:
                    appointment_time = ""
            else:
                appointment_time = ""


        # 1. Validation
        data = {
            'customer_id': customer_id,
            'service_id': service_id,
            'date': appointment_date,
            'time': appointment_time
        }
        validator = AppointmentValidator()
        validator.validate(data)
        validator.raise_if_invalid("Thông tin lịch hẹn không hợp lệ.")

        from services.customer_service import CustomerService
        from services.service_service import ServiceService
        if not CustomerService.get_by_id(customer_id):
            raise ValidationException("Khách hàng không tồn tại hoặc không thuộc Workspace này.")
        if not ServiceService.get_service_by_id(service_id):
            raise ValidationException("Dịch vụ không tồn tại hoặc không thuộc Workspace này.")

        # 2. Parse time
        try:
            full_time = datetime.strptime(f"{appointment_date} {appointment_time}", '%Y-%m-%d %H:%M')
        except ValueError:
            raise ValidationException("Định dạng ngày giờ hẹn không hợp lệ.")

        # 3. Conflict check
        if not AppointmentService.validate(full_time, service_id):
            raise ConflictException("Khung giờ này đã được đặt cho dịch vụ này.")

        from services.customer_service import CustomerService
        from services.service_service import ServiceService
        if not CustomerService.get_by_id(customer_id):
            raise ValidationException("Khách hàng không tồn tại hoặc không thuộc Workspace này.")
        if not ServiceService.get_service_by_id(service_id):
            raise ValidationException("Dịch vụ không tồn tại hoặc không thuộc Workspace này.")

        new_appointment = Appointment(
            customer_id=customer_id,
            service_id=service_id,
            appointment_time=full_time,
            notes=notes,
            status=status
        )
        from services.workspace_service import WorkspaceService
        WorkspaceService.assign_workspace(new_appointment)
        db.session.add(new_appointment)
        db.session.commit()
        AppointmentService._attach_flags(new_appointment)

        customer_name = new_appointment.customer.name if new_appointment.customer else "Khách hàng"
        ActivityLogService.log_create(
            module=ActivityLogService.MODULE_APPOINTMENT,
            description=f'Đặt lịch hẹn cho "{customer_name}"',
            reference_id=new_appointment.id
        )

        dashboard_cache.invalidate('dashboard_data')
        return new_appointment

    @staticmethod
    def create(customer_id, service_id, appointment_time, notes=None):
        # Compatibility wrapper for older tests
        return AppointmentService.create_appointment(customer_id, service_id, appointment_time, notes=notes)

    @staticmethod
    def search(query):
        from services.workspace_service import WorkspaceService
        if not query:
            appointments = WorkspaceService.scoped_query(Appointment).filter(Appointment.deleted_at.is_(None)).all()
        else:
            appointments = WorkspaceService.scoped_query(Appointment).join(Customer).join(Service).filter(
                Appointment.deleted_at.is_(None),
                or_(
                    Customer.name.ilike(f'%{query}%'),
                    Customer.phone.ilike(f'%{query}%'),
                    Service.name.ilike(f'%{query}%')
                )
            ).all()
        for appt in appointments:
            AppointmentService._attach_flags(appt)
        return appointments

    @staticmethod
    def _build_filtered_query(search=None, status=None, from_date=None, to_date=None, period=None):
        from services.workspace_service import WorkspaceService
        query = WorkspaceService.scoped_query(Appointment).join(Customer).join(Service).options(
            db.contains_eager(Appointment.customer),
            db.contains_eager(Appointment.service)
        ).filter(Appointment.deleted_at.is_(None))

        if search:
            query = query.filter(
                or_(
                    Customer.name.ilike(f'%{search}%'),
                    Customer.phone.ilike(f'%{search}%'),
                    Service.name.ilike(f'%{search}%')
                )
            )

        if status:
            query = query.filter(func.lower(Appointment.status) == str(status).strip().lower())

        if period == 'today':
            today = local_today()
            from_date = today
            to_date = today
        elif period == 'this_week':
            today = local_today()
            from_date = today - timedelta(days=today.weekday())
            to_date = from_date + timedelta(days=6)
        elif period == 'this_month':
            today = local_today()
            from_date = today.replace(day=1)
            _, last_day = calendar.monthrange(today.year, today.month)
            to_date = today.replace(day=last_day)
        elif period == 'all':
            from_date = None
            to_date = None
        elif period == 'custom':
            pass
        else:
            if not from_date and not to_date:
                from_date = None
                to_date = None

        if from_date:
            try:
                if isinstance(from_date, str):
                    from_date_obj = datetime.strptime(from_date, '%Y-%m-%d').date()
                elif isinstance(from_date, datetime):
                    from_date_obj = from_date.date()
                else:
                    from_date_obj = from_date
                query = query.filter(func.date(Appointment.appointment_time) >= from_date_obj)
            except (ValueError, TypeError):
                pass

        if to_date:
            try:
                if isinstance(to_date, str):
                    to_date_obj = datetime.strptime(to_date, '%Y-%m-%d').date()
                elif isinstance(to_date, datetime):
                    to_date_obj = to_date.date()
                else:
                    to_date_obj = to_date
                query = query.filter(func.date(Appointment.appointment_time) <= to_date_obj)
            except (ValueError, TypeError):
                pass

        return query

    @staticmethod
    def get_filtered(search=None, status=None, from_date=None, to_date=None, sort_by='date', order='desc', page=1, per_page=10, period=None):
        query = AppointmentService._build_filtered_query(
            search=search,
            status=status,
            from_date=from_date,
            to_date=to_date,
            period=period
        )

        if sort_by == 'customer':
            sort_col = Customer.name
        elif sort_by == 'status':
            sort_col = Appointment.status
        else:
            sort_col = Appointment.appointment_time

        if order == 'asc':
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(sort_col.desc())

        paginated = query.paginate(page=page, per_page=per_page, error_out=False)

        for item in paginated.items:
            AppointmentService._attach_flags(item)
            item.display_status = AppointmentService._status_display_label(item.status)

        return paginated

    @staticmethod
    def get_appointment_summary(search=None, status=None, from_date=None, to_date=None, period=None):
        query = AppointmentService._build_filtered_query(
            search=search,
            status=status,
            from_date=from_date,
            to_date=to_date,
            period=period
        )

        results = query.with_entities(Appointment.status).all()

        summary = {
            "total": len(results),
            "pending": 0,
            "confirmed": 0,
            "completed": 0,
            "cancelled": 0
        }

        for (st,) in results:
            status_key = AppointmentService._normalize_status(st)
            if status_key == 'pending':
                summary['pending'] += 1
            elif status_key == 'confirmed':
                summary['confirmed'] += 1
            elif status_key == 'completed':
                summary['completed'] += 1
            elif status_key in ('cancelled', 'canceled'):
                summary['cancelled'] += 1

        return summary

    @staticmethod
    def update(appointment_id, **kwargs):
        appointment = AppointmentService.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Không tìm thấy lịch hẹn!")

        old_status = appointment.status

        customer_id = kwargs.get('customer_id', appointment.customer_id)
        service_id = kwargs.get('service_id', appointment.service_id)

        # Normalize date and time
        appointment_date = kwargs.get('appointment_date')
        appointment_time = kwargs.get('appointment_time')

        if appointment_date is None:
            # We didn't receive explicit appointment_date, so try to extract it from appointment_time
            if appointment_time is not None:
                if isinstance(appointment_time, datetime):
                    dt_obj = appointment_time
                    appointment_date = dt_obj.strftime('%Y-%m-%d')
                    appointment_time = dt_obj.strftime('%H:%M')
                elif isinstance(appointment_time, str):
                    combined = appointment_time.strip()
                    if 'T' in combined:
                        appointment_date, appointment_time = combined.split('T')
                    elif ' ' in combined:
                        appointment_date, appointment_time = combined.split(' ')
                    else:
                        appointment_date = combined
                        appointment_time = ""
                else:
                    appointment_date = appointment.appointment_time.strftime('%Y-%m-%d')
                    appointment_time = appointment.appointment_time.strftime('%H:%M')
            else:
                # Both are None, so use existing appointment time
                appointment_date = appointment.appointment_time.strftime('%Y-%m-%d')
                appointment_time = appointment.appointment_time.strftime('%H:%M')
        elif appointment_time is None:
            # We got appointment_date but not appointment_time, so use existing time part
            appointment_time = appointment.appointment_time.strftime('%H:%M')


        # 1. Validation
        data = {
            'customer_id': customer_id,
            'service_id': service_id,
            'date': appointment_date,
            'time': appointment_time
        }
        validator = AppointmentValidator()
        validator.validate(data)
        validator.raise_if_invalid("Thông tin lịch hẹn không hợp lệ.")

        from services.customer_service import CustomerService
        from services.service_service import ServiceService
        if not CustomerService.get_by_id(customer_id):
            raise ValidationException("Khách hàng không tồn tại hoặc không thuộc Workspace này.")
        if not ServiceService.get_service_by_id(service_id):
            raise ValidationException("Dịch vụ không tồn tại hoặc không thuộc Workspace này.")

        # 2. Parse time
        try:
            full_time = datetime.strptime(f"{appointment_date} {appointment_time}", '%Y-%m-%d %H:%M')
        except ValueError:
            raise ValidationException("Định dạng ngày giờ hẹn không hợp lệ.")

        # 3. Conflict check
        if not AppointmentService.validate(full_time, service_id, exclude_id=appointment_id):
            raise ConflictException("Khung giờ này đã được đặt cho dịch vụ này.")

        appointment.customer_id = customer_id
        appointment.service_id = service_id
        appointment.appointment_time = full_time
        if 'status' in kwargs:
            appointment.status = kwargs['status']
        if 'notes' in kwargs:
            appointment.notes = kwargs['notes']

        db.session.commit()
        AppointmentService._attach_flags(appointment)

        new_status = kwargs.get('status')
        if new_status and new_status != old_status:
            new_status_key = AppointmentService._normalize_status(new_status)
            if new_status_key in ('cancelled', 'canceled'):
                ActivityLogService.log_action(
                    module=ActivityLogService.MODULE_APPOINTMENT,
                    action=ActivityLogService.ACTION_STATUS_CHANGE,
                    description=f'Hủy lịch hẹn #{appointment.id}',
                    reference_id=appointment.id,
                    severity=ActivityLogService.SEVERITY_SUCCESS
                )
            else:
                ActivityLogService.log_action(
                    module=ActivityLogService.MODULE_APPOINTMENT,
                    action=ActivityLogService.ACTION_STATUS_CHANGE,
                    description=f'Đổi trạng thái lịch hẹn #{appointment.id} sang "{AppointmentService._status_display_label(new_status)}"',
                    reference_id=appointment.id,
                    severity=ActivityLogService.SEVERITY_SUCCESS
                )

        if any(k in kwargs for k in ['appointment_date', 'appointment_time', 'service_id', 'customer_id', 'notes']):
            customer_name = appointment.customer.name if appointment.customer else "Khách hàng"
            ActivityLogService.log_update(
                module=ActivityLogService.MODULE_APPOINTMENT,
                description=f'Cập nhật lịch hẹn cho "{customer_name}"',
                reference_id=appointment.id
            )

        dashboard_cache.invalidate('dashboard_data')
        return appointment

    @staticmethod
    def update_status(appointment_id, new_status):
        return AppointmentService.update(appointment_id, status=new_status)

    @staticmethod
    def delete(appointment_id, actor=None):
        """Xóa mềm lịch hẹn và chuyển vào thùng rác"""
        from services.workspace_service import WorkspaceService
        appointment = WorkspaceService.scoped_query(Appointment).filter(Appointment.id == appointment_id).first()
        if appointment and appointment.deleted_at is None:
            customer_name = appointment.customer.name if appointment.customer else "Khách hàng"
            try:
                actor_name = actor
                if actor_name is None or not str(actor_name).strip():
                    actor_name = AuthService.require_current_username()
                current_user = AuthService.get_current_user()

                appointment.deleted_at = utc_now()
                appointment.deleted_by = actor_name
                ActivityLogService.write_log(
                    module=ActivityLogService.MODULE_APPOINTMENT,
                    action=ActivityLogService.ACTION_DELETE,
                    description=f'{actor_name} chuyển lịch hẹn #{appointment_id} của "{customer_name}" vào Thùng rác',
                    reference_id=appointment_id,
                    session_override=db.session,
                    commit=False,
                    user_id_override=current_user.id if current_user and actor_name != "Hệ thống" else None
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
                db.session.remove()
                raise

            dashboard_cache.invalidate('dashboard_data')
            return True, None
        return False, "Appointment not found"

    @staticmethod
    def restore(appointment_id, actor=None):
        """Khôi phục lịch hẹn từ Thùng rác"""
        from services.workspace_service import WorkspaceService
        appointment = WorkspaceService.scoped_query(Appointment).filter(Appointment.id == appointment_id).first()
        if appointment and appointment.deleted_at is not None:
            from services.customer_service import CustomerService
            from services.service_service import ServiceService
            customer = CustomerService.get_by_id(appointment.customer_id)
            if not customer:
                raise ValueError("Không thể khôi phục lịch hẹn vì khách hàng liên quan đã bị xóa vĩnh viễn khỏi hệ thống hoặc thuộc Workspace khác.")

            service = ServiceService.get_service_by_id(appointment.service_id)
            if not service:
                raise ValueError("Không thể khôi phục lịch hẹn vì dịch vụ liên quan đã bị xóa vĩnh viễn khỏi hệ thống.")

            try:
                actor_name = actor
                if actor_name is None or not str(actor_name).strip():
                    actor_name = AuthService.require_current_username()
                current_user = AuthService.get_current_user()
                appointment.deleted_at = None
                appointment.deleted_by = None
                customer_name = customer.name
                ActivityLogService.write_log(
                    module=ActivityLogService.MODULE_APPOINTMENT,
                    action=ActivityLogService.ACTION_RESTORE,
                    description=f'{actor_name} khôi phục lịch hẹn #{appointment_id} của "{customer_name}" từ Thùng rác',
                    reference_id=appointment_id,
                    severity=ActivityLogService.SEVERITY_SUCCESS,
                    session_override=db.session,
                    commit=False,
                    user_id_override=current_user.id if current_user and actor_name != "Hệ thống" else None
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
                db.session.remove()
                raise
            dashboard_cache.invalidate('dashboard_data')
            return True
        return False

    @staticmethod
    def permanent_delete(appointment_id, actor=None):
        """Xóa vĩnh viễn lịch hẹn khỏi cơ sở dữ liệu"""
        from services.workspace_service import WorkspaceService
        appointment = WorkspaceService.scoped_query(Appointment).filter(Appointment.id == appointment_id).first()
        if appointment:
            customer_name = appointment.customer.name if appointment.customer else "Khách hàng"
            try:
                actor_name = actor
                if actor_name is None or not str(actor_name).strip():
                    actor_name = AuthService.require_current_username()
                current_user = AuthService.get_current_user()
                ActivityLogService.write_log(
                    module=ActivityLogService.MODULE_APPOINTMENT,
                    action='PERMANENT_DELETE',
                    description=f'{actor_name} xóa vĩnh viễn lịch hẹn #{appointment_id} của "{customer_name}" khỏi cơ sở dữ liệu',
                    reference_id=appointment_id,
                    severity=ActivityLogService.SEVERITY_WARNING,
                    session_override=db.session,
                    commit=False,
                    user_id_override=current_user.id if current_user and actor_name != "Hệ thống" else None
                )
                db.session.delete(appointment)
                db.session.commit()
            except Exception:
                db.session.rollback()
                db.session.remove()
                raise
            dashboard_cache.invalidate('dashboard_data')
            return True
        return False

    @staticmethod
    def validate(appointment_time, service_id, exclude_id=None):
        if isinstance(appointment_time, str):
            try:
                appointment_time = datetime.strptime(appointment_time, '%Y-%m-%dT%H:%M')
            except ValueError:
                return False

        from services.workspace_service import WorkspaceService
        query = WorkspaceService.scoped_query(Appointment).filter(
            Appointment.appointment_time == appointment_time,
            Appointment.service_id == service_id,
            Appointment.status != 'Cancelled',
            Appointment.deleted_at.is_(None)
        )
        if exclude_id:
            query = query.filter(Appointment.id != exclude_id)

        conflict = query.first()
        return conflict is None
