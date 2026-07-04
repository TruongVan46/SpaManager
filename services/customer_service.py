import math

from sqlalchemy import func

from extensions import db
from models.customer import Customer
from models.appointment import Appointment
from models.service import Service
from models.invoice import Invoice
from core.exceptions import NotFoundException, ConflictException
from core.cache import dashboard_cache
from services.auth_service import AuthService
from validators.customer_validator import CustomerValidator
from services.activity_log_service import ActivityLogService
from utils.timezone_utils import utc_now


class CustomerService:
    @staticmethod
    def get_all():
        """Lấy tất cả khách hàng hoạt động (chưa xóa mềm)"""
        return Customer.query.filter(Customer.deleted_at.is_(None)).all()

    @staticmethod
    def search(query):
        """Tìm kiếm khách hàng hoạt động theo tên, số điện thoại hoặc dịch vụ"""
        db_query = Customer.query.join(Appointment, isouter=True).join(Service, isouter=True).filter(Customer.deleted_at.is_(None))
        if query:
            db_query = db_query.filter(
                (Customer.name.ilike(f'%{query}%')) |
                (Customer.phone.ilike(f'%{query}%')) |
                (Service.name.ilike(f'%{query}%'))
            )
        
        return db_query.distinct().all()

    @staticmethod
    def search_paginated(query, page=1, per_page=25, sort_by='id', sort_dir='desc'):
        """Tim kiem va phan trang khach hang hoat dong"""
        db_query = Customer.query.join(Appointment, isouter=True).join(Service, isouter=True).filter(Customer.deleted_at.is_(None))
        if query:
            db_query = db_query.filter(
                (Customer.name.ilike(f'%{query}%')) |
                (Customer.phone.ilike(f'%{query}%')) |
                (Service.name.ilike(f'%{query}%'))
            )
        db_query = db_query.distinct()
        # Dynamic sort
        sort_col = getattr(Customer, sort_by, None)
        if sort_col is None:
            sort_col = Customer.id
        if sort_dir == 'asc':
            db_query = db_query.order_by(sort_col.asc())
        else:
            db_query = db_query.order_by(sort_col.desc())
        return db_query.paginate(page=page, per_page=per_page, error_out=False)

    @staticmethod
    def get_by_id(customer_id):
        """Lấy chi tiết một khách hàng hoạt động theo ID"""
        return Customer.query.filter(Customer.id == customer_id, Customer.deleted_at.is_(None)).first()

    @staticmethod
    def _coerce_page(value, default=1):
        try:
            page = int(value)
        except (TypeError, ValueError):
            return default
        return page if page > 0 else default

    @staticmethod
    def _paginate_query(query, page, per_page):
        total = query.count()
        total_pages = max(1, math.ceil(total / per_page)) if total else 1
        page = min(CustomerService._coerce_page(page), total_pages)
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        return pagination

    @staticmethod
    def get_customer_history(customer_id, appointment_page=1, invoice_page=1, per_page=10):
        customer = CustomerService.get_by_id(customer_id)
        if not customer:
            return None

        appointments_base_query = Appointment.query.options(
            db.joinedload(Appointment.service)
        ).filter(
            Appointment.customer_id == customer_id,
            Appointment.deleted_at.is_(None)
        ).order_by(
            Appointment.appointment_time.desc(),
            Appointment.id.desc()
        )

        invoices_base_query = Invoice.query.filter(
            Invoice.customer_id == customer_id,
            Invoice.deleted_at.is_(None)
        ).order_by(
            Invoice.invoice_date.desc(),
            Invoice.id.desc()
        )

        appointment_count = db.session.query(func.count(Appointment.id)).filter(
            Appointment.customer_id == customer_id,
            Appointment.deleted_at.is_(None)
        ).scalar() or 0
        invoice_count = db.session.query(func.count(Invoice.id)).filter(
            Invoice.customer_id == customer_id,
            Invoice.deleted_at.is_(None)
        ).scalar() or 0
        total_spent = db.session.query(func.coalesce(func.sum(Invoice.total_amount), 0)).filter(
            Invoice.customer_id == customer_id,
            Invoice.deleted_at.is_(None)
        ).scalar() or 0

        latest_appointment = appointments_base_query.first()
        appointment_history = CustomerService._paginate_query(appointments_base_query, appointment_page, per_page)
        invoice_history = CustomerService._paginate_query(invoices_base_query, invoice_page, per_page)

        return {
            "customer": customer,
            "summary": {
                "total_appointments": appointment_count,
                "total_invoices": invoice_count,
                "total_spent": total_spent,
                "latest_appointment_at": latest_appointment.appointment_time if latest_appointment else None,
                "latest_appointment_status": latest_appointment.status if latest_appointment else None,
                "appointment_count": appointment_count,
                "invoice_count": invoice_count,
            },
            "appointment_history": appointment_history,
            "invoice_history": invoice_history,
            "appointment_page": appointment_history.page,
            "invoice_page": invoice_history.page,
            "appointment_per_page": appointment_history.per_page,
            "invoice_per_page": invoice_history.per_page,
        }

    @staticmethod
    def clean_phone(phone):
        if not phone:
            return None
        # Loại bỏ khoảng trắng và ký tự phân cách
        cleaned = ''.join(c for c in phone if c.isdigit())
        return cleaned if cleaned else None

    @staticmethod
    def clean_email(email):
        if not email:
            return None
        # Loại bỏ khoảng trắng và chuyển thành chữ thường
        cleaned = email.strip().lower()
        return cleaned if cleaned else None

    @staticmethod
    def check_duplicate(phone=None, email=None, exclude_customer_id=None):
        """
        Kiểm tra trùng số điện thoại và email trong số các khách hàng hoạt động.
        Loại trừ customer có ID bằng exclude_customer_id (khi update).
        Trả về dictionary chứa kết quả kiểm tra.
        """
        errors = {}
        
        cleaned_phone = CustomerService.clean_phone(phone)
        cleaned_email = CustomerService.clean_email(email)
        
        if cleaned_phone:
            query = db.session.query(Customer.id).filter(
                Customer.phone == cleaned_phone,
                Customer.deleted_at.is_(None)
            )
            if exclude_customer_id:
                query = query.filter(Customer.id != exclude_customer_id)
            if query.count() > 0:
                errors['phone'] = 'Số điện thoại này đã tồn tại trong hệ thống.'
                
        if cleaned_email:
            query = db.session.query(Customer.id).filter(
                Customer.email == cleaned_email,
                Customer.deleted_at.is_(None)
            )
            if exclude_customer_id:
                query = query.filter(Customer.id != exclude_customer_id)
            if query.count() > 0:
                errors['email'] = 'Email này đã được sử dụng.'
                
        return errors

    @staticmethod
    def create(name, phone=None, email=None, address=None):
        
        # 1. Input Validation
        data = {'name': name, 'phone': phone, 'email': email}
        validator = CustomerValidator()
        validator.validate(data)
        validator.raise_if_invalid("Thông tin khách hàng không hợp lệ.")

        cleaned_phone = CustomerService.clean_phone(phone)
        cleaned_email = CustomerService.clean_email(email)
        
        errors = CustomerService.check_duplicate(phone=cleaned_phone, email=cleaned_email)
        if errors:
            raise ConflictException(", ".join(errors.values()))
            
        new_customer = Customer(
            name=name.strip(), 
            phone=cleaned_phone, 
            email=cleaned_email, 
            address=address.strip() if address else None
        )
        db.session.add(new_customer)
        db.session.commit()
        
        ActivityLogService.log_create(
            module=ActivityLogService.MODULE_CUSTOMER,
            description=f'Thêm khách hàng "{new_customer.name}"',
            reference_id=new_customer.id
        )

        dashboard_cache.invalidate('dashboard_data')
        return new_customer

    @staticmethod
    def update(customer_id, name=None, phone=None, email=None, address=None):
        customer = CustomerService.get_by_id(customer_id)
        if not customer:
            raise NotFoundException("Không tìm thấy khách hàng!")

        
        # 1. Input Validation
        data = {'name': name, 'phone': phone, 'email': email}
        validator = CustomerValidator()
        validator.validate(data)
        validator.raise_if_invalid("Thông tin khách hàng không hợp lệ.")

        cleaned_phone = CustomerService.clean_phone(phone)
        cleaned_email = CustomerService.clean_email(email)
        
        errors = CustomerService.check_duplicate(phone=cleaned_phone, email=cleaned_email, exclude_customer_id=customer_id)
        if errors:
            raise ConflictException(", ".join(errors.values()))
            
        customer.name = name.strip()
        customer.phone = cleaned_phone
        customer.email = cleaned_email
        if address is not None:
            customer.address = address.strip() if address else None
        db.session.commit()
        
        ActivityLogService.log_update(
            module=ActivityLogService.MODULE_CUSTOMER,
            description=f'Cập nhật khách hàng "{customer.name}"',
            reference_id=customer.id
        )

        dashboard_cache.invalidate('dashboard_data')
        return customer

    @staticmethod
    def can_delete(customer_id):
        """
        Kiểm tra xem khách hàng có thể xóa hay không theo quy tắc nghiệp vụ.
        Chỉ được xóa khi chưa từng có lịch hẹn và hóa đơn nào.
        """
        
        appointment_count = Appointment.query.filter_by(customer_id=customer_id).count()
        invoice_count = Invoice.query.filter_by(customer_id=customer_id).count()
        
        can_del = (appointment_count == 0 and invoice_count == 0)
        
        return {
            "can_delete": can_del,
            "appointment_count": appointment_count,
            "invoice_count": invoice_count
        }

    @staticmethod
    def delete(customer_id, actor=None):
        """Xóa mềm khách hàng và chuyển vào thùng rác"""
        customer = Customer.query.get(customer_id)
        if not customer or customer.deleted_at is not None:
            raise NotFoundException("Không tìm thấy khách hàng hoặc khách hàng đã bị xóa.")

        status = CustomerService.can_delete(customer_id)
        if not status["can_delete"]:
            raise ConflictException("Không thể xóa khách hàng này vì đã phát sinh lịch hẹn hoặc hóa đơn liên quan.")
        try:
            actor_name = actor
            if actor_name is None or not str(actor_name).strip():
                actor_name = AuthService.require_current_username()
            current_user = AuthService.get_current_user()
            name = customer.name
            customer.deleted_at = utc_now()
            customer.deleted_by = actor_name
            ActivityLogService.write_log(
                module=ActivityLogService.MODULE_CUSTOMER,
                action=ActivityLogService.ACTION_DELETE,
                description=f'{actor_name} chuyển khách hàng "{name}" vào Thùng rác',
                reference_id=customer_id,
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

    @staticmethod
    def restore(customer_id, actor=None):
        """Khôi phục khách hàng từ thùng rác"""
        customer = Customer.query.get(customer_id)
        if not customer or customer.deleted_at is None:
            raise NotFoundException("Không tìm thấy khách hàng trong Thùng rác.")

        try:
            actor_name = actor
            if actor_name is None or not str(actor_name).strip():
                actor_name = AuthService.require_current_username()
            current_user = AuthService.get_current_user()
            customer.deleted_at = None
            customer.deleted_by = None
            ActivityLogService.write_log(
                module=ActivityLogService.MODULE_CUSTOMER,
                action=ActivityLogService.ACTION_UPDATE,
                description=f'{actor_name} khôi phục khách hàng "{customer.name}" từ Thùng rác',
                reference_id=customer_id,
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

    @staticmethod
    def permanent_delete(customer_id, actor=None):
        """Xóa vĩnh viễn khách hàng khỏi cơ sở dữ liệu"""
        customer = Customer.query.get(customer_id)
        if customer:
            try:
                status = CustomerService.can_delete(customer_id)
                if not status["can_delete"]:
                    raise ValueError("Không thể xóa vĩnh viễn khách hàng này vì vẫn còn lịch hẹn hoặc hóa đơn liên quan.")
                name = customer.name
                actor_name = actor
                if actor_name is None or not str(actor_name).strip():
                    actor_name = AuthService.require_current_username()
                current_user = AuthService.get_current_user()
                ActivityLogService.write_log(
                    module=ActivityLogService.MODULE_CUSTOMER,
                    action='PERMANENT_DELETE',
                    description=f'{actor_name} xóa vĩnh viễn khách hàng "{name}" khỏi cơ sở dữ liệu',
                    reference_id=customer_id,
                    severity=ActivityLogService.SEVERITY_WARNING,
                    session_override=db.session,
                    commit=False,
                    user_id_override=current_user.id if current_user and actor_name != "Hệ thống" else None
                )
                db.session.delete(customer)
                db.session.commit()
            except Exception:
                db.session.rollback()
                db.session.remove()
                raise
            dashboard_cache.invalidate('dashboard_data')
            return True
        return False
