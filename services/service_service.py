from extensions import db
from models.service import Service
from models.appointment import Appointment
from models.invoice_detail import InvoiceDetail
from core.exceptions import NotFoundException, ConflictException
from core.cache import dashboard_cache
from services.auth_service import AuthService
from validators.service_validator import ServiceValidator
from services.activity_log_service import ActivityLogService
from utils.timezone_utils import utc_now


class ServiceService:
    @staticmethod
    def get_all_services():
        """Lấy danh sách tất cả dịch vụ hoạt động (chưa xóa mềm)"""
        from services.workspace_service import WorkspaceService
        return WorkspaceService.scoped_query(Service).filter(Service.deleted_at.is_(None)).all()

    @staticmethod
    def get_services_paginated(query='', service_type='', page=1, per_page=25, sort_by='name', sort_dir='asc'):
        """Lay danh sach dich vu hoat dong co phan trang, tim kiem va loc theo nhom"""
        from services.workspace_service import WorkspaceService
        db_query = WorkspaceService.scoped_query(Service).filter(Service.deleted_at.is_(None))
        if query:
            db_query = db_query.filter(
                (Service.name.ilike(f'%{query}%')) |
                (Service.description.ilike(f'%{query}%'))
            )
        if service_type:
            db_query = db_query.filter(Service.category == service_type)
        # Dynamic sort
        sort_col = getattr(Service, sort_by, None)
        if sort_col is None:
            sort_col = Service.name
        if sort_dir == 'desc':
            db_query = db_query.order_by(sort_col.desc())
        else:
            db_query = db_query.order_by(sort_col.asc())
        return db_query.paginate(page=page, per_page=per_page, error_out=False)

    @staticmethod
    def get_service_by_id(service_id):
        """Lấy chi tiết một dịch vụ hoạt động theo ID"""
        from services.workspace_service import WorkspaceService
        return WorkspaceService.scoped_query(Service).filter(Service.id == service_id, Service.deleted_at.is_(None)).first()

    @staticmethod
    def create_service(data):
        """Tạo dịch vụ mới"""

        # 1. Validation
        validator = ServiceValidator()
        validator.validate(data)
        validator.raise_if_invalid("Thông tin dịch vụ không hợp lệ.")

        new_service = Service(
            name=data.get('name', '').strip(),
            price=float(data.get('price', 0)) if data.get('price') else 0.0,
            duration=int(data.get('duration', 0)) if data.get('duration') else None,
            description=data.get('description'),
            category=data.get('category', 'other')
        )
        from services.workspace_service import WorkspaceService
        WorkspaceService.assign_workspace(new_service)
        db.session.add(new_service)
        db.session.commit()

        ActivityLogService.log_create(
            module=ActivityLogService.MODULE_SERVICE,
            description=f'Thêm dịch vụ "{new_service.name}"',
            reference_id=new_service.id
        )

        dashboard_cache.invalidate('dashboard_data')
        return new_service

    @staticmethod
    def update_service(service_id, data):
        """Cập nhật thông tin dịch vụ hoạt động"""
        service = ServiceService.get_service_by_id(service_id)
        if not service:
            raise NotFoundException("Không tìm thấy dịch vụ!")


        # 1. Validation
        validator = ServiceValidator()
        validator.validate(data)
        validator.raise_if_invalid("Thông tin dịch vụ không hợp lệ.")

        service.name = data.get('name', '').strip()
        service.price = float(data.get('price')) if data.get('price') else 0.0
        service.duration = int(data.get('duration')) if data.get('duration') else None
        service.description = data.get('description')
        service.category = data.get('category', 'other')
        db.session.commit()

        ActivityLogService.log_update(
            module=ActivityLogService.MODULE_SERVICE,
            description=f'Cập nhật dịch vụ "{service.name}"',
            reference_id=service.id
        )

        dashboard_cache.invalidate('dashboard_data')
        return service

    @staticmethod
    def can_delete(service_id):
        """
        Kiểm tra xem dịch vụ có thể xóa hay không theo quy tắc nghiệp vụ.
        Chỉ được xóa khi chưa từng có lịch hẹn và chi tiết hóa đơn nào liên kết.
        """

        from services.workspace_service import WorkspaceService
        appointment_count = WorkspaceService.scoped_query(Appointment).filter_by(service_id=service_id).count()
        invoice_detail_count = InvoiceDetail.query.filter_by(service_id=service_id).count()

        can_del = (appointment_count == 0 and invoice_detail_count == 0)

        return {
            "can_delete": can_del,
            "appointment_count": appointment_count,
            "invoice_detail_count": invoice_detail_count
        }

    @staticmethod
    def delete_service(service_id, actor=None):
        """Xóa mềm dịch vụ và chuyển vào thùng rác"""
        from services.workspace_service import WorkspaceService
        service = WorkspaceService.scoped_query(Service).filter(Service.id == service_id).first()
        if not service or service.deleted_at is not None:
            raise NotFoundException("Không tìm thấy dịch vụ hoặc dịch vụ đã bị xóa.")

        status = ServiceService.can_delete(service_id)
        if not status["can_delete"]:
            raise ConflictException("Không thể xóa dịch vụ này vì đã phát sinh lịch hẹn hoặc chi tiết hóa đơn liên quan.")
        try:
            actor_name = actor
            if actor_name is None or not str(actor_name).strip():
                actor_name = AuthService.require_current_username()
            current_user = AuthService.get_current_user()
            name = service.name
            service.deleted_at = utc_now()
            service.deleted_by = actor_name
            ActivityLogService.write_log(
                module=ActivityLogService.MODULE_SERVICE,
                action=ActivityLogService.ACTION_DELETE,
                description=f'{actor_name} chuyển dịch vụ "{name}" vào Thùng rác',
                reference_id=service_id,
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
    def restore_service(service_id, actor=None):
        """Khôi phục dịch vụ từ thùng rác"""
        from services.workspace_service import WorkspaceService
        service = WorkspaceService.scoped_query(Service).filter(Service.id == service_id).first()
        if not service or service.deleted_at is None:
            raise NotFoundException("Không tìm thấy dịch vụ trong Thùng rác.")

        try:
            actor_name = actor
            if actor_name is None or not str(actor_name).strip():
                actor_name = AuthService.require_current_username()
            current_user = AuthService.get_current_user()
            service.deleted_at = None
            service.deleted_by = None
            ActivityLogService.write_log(
                module=ActivityLogService.MODULE_SERVICE,
                action=ActivityLogService.ACTION_UPDATE,
                description=f'{actor_name} khôi phục dịch vụ "{service.name}" từ Thùng rác',
                reference_id=service_id,
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
    def permanent_delete_service(service_id, actor=None):
        """Xóa vĩnh viễn dịch vụ khỏi cơ sở dữ liệu"""
        from services.workspace_service import WorkspaceService
        service = WorkspaceService.scoped_query(Service).filter(Service.id == service_id).first()
        if service:
            status = ServiceService.can_delete(service_id)
            if not status["can_delete"]:
                raise ValueError("Không thể xóa vĩnh viễn dịch vụ này vì đã phát sinh lịch hẹn hoặc chi tiết hóa đơn liên quan.")

            name = service.name
            try:
                actor_name = actor
                if actor_name is None or not str(actor_name).strip():
                    actor_name = AuthService.require_current_username()
                current_user = AuthService.get_current_user()
                ActivityLogService.write_log(
                    module=ActivityLogService.MODULE_SERVICE,
                    action='PERMANENT_DELETE',
                    description=f'{actor_name} xóa vĩnh viễn dịch vụ "{name}" khỏi cơ sở dữ liệu',
                    reference_id=service_id,
                    severity=ActivityLogService.SEVERITY_WARNING,
                    session_override=db.session,
                    commit=False,
                    user_id_override=current_user.id if current_user and actor_name != "Hệ thống" else None
                )
                db.session.delete(service)
                db.session.commit()
            except Exception:
                db.session.rollback()
                db.session.remove()
                raise
            dashboard_cache.invalidate('dashboard_data')
            return True
        return False
