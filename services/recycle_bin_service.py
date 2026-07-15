from models.customer import Customer
from models.service import Service
from models.appointment import Appointment
from models.invoice import Invoice
from models.invoice_detail import InvoiceDetail
from datetime import datetime
from core.exceptions import ValidationException
from core.exceptions import NotFoundException
from extensions import db
from services.auth_service import AuthService
from services.activity_log_service import ActivityLogService

class PythonPagination:
    """A pagination helper that mimics Flask-SQLAlchemy's Pagination object."""
    def __init__(self, items, page, per_page):
        self.total = len(items)
        self.page = page
        self.per_page = per_page
        self.pages = (self.total + per_page - 1) // per_page if per_page > 0 else 0
        
        start = (page - 1) * per_page
        end = start + per_page
        self.items = items[start:end]
        
        self.has_prev = page > 1
        self.prev_num = page - 1 if self.has_prev else None
        
        self.has_next = page < self.pages
        self.next_num = page + 1 if self.has_next else None

    def iter_pages(self, left_edge=1, right_edge=1, left_current=2, right_current=2):
        last_page = self.pages
        current_page = self.page
        for i in range(1, last_page + 1):
            if i <= left_edge or i > last_page - right_edge or \
               (i >= current_page - left_current and i <= current_page + right_current):
                yield i


class RecycleBinRegistry:
    _registry = {}

    @classmethod
    def register(cls, key, metadata):
        """Register model metadata for the generic Recycle Bin."""
        cls._registry[key] = metadata

    @classmethod
    def get(cls, key):
        return cls._registry.get(key)

    @classmethod
    def get_all(cls):
        return cls._registry


class RecycleBinService:
    _PERMANENT_DELETE_MODELS = {
        'Customer': Customer,
        'Service': Service,
        'Appointment': Appointment,
        'Invoice': Invoice,
    }

    _PERMANENT_DELETE_LABELS = {
        'Customer': 'KHÁCH HÀNG',
        'Service': 'DỊCH VỤ',
        'Appointment': 'LỊCH HẸN',
        'Invoice': 'HÓA ĐƠN',
    }

    @classmethod
    def permanent_delete_phrase(cls, item_type, item_id):
        label = cls._PERMANENT_DELETE_LABELS.get(item_type)
        if label is None:
            return None
        return f"XÓA VĨNH VIỄN {label} {item_id}"

    @classmethod
    def _dependency_status(cls, item_type, item_id, workspace_id):
        if item_type == 'Customer':
            appointment_count = Appointment.query.filter(
                Appointment.customer_id == item_id,
                Appointment.workspace_id == workspace_id,
            ).count()
            invoice_count = Invoice.query.filter(
                Invoice.customer_id == item_id,
                Invoice.workspace_id == workspace_id,
            ).count()
            can_delete = appointment_count == 0 and invoice_count == 0
            reason = (
                f"Không thể xóa vĩnh viễn khách hàng vì còn "
                f"{appointment_count} lịch hẹn và {invoice_count} hóa đơn liên quan."
                if not can_delete else ""
            )
            return {
                'can_delete': can_delete,
                'reason': reason,
                'appointment_count': appointment_count,
                'invoice_count': invoice_count,
            }

        if item_type == 'Service':
            appointment_count = Appointment.query.filter(
                Appointment.service_id == item_id,
                Appointment.workspace_id == workspace_id,
            ).count()
            invoice_detail_count = InvoiceDetail.query.join(
                Invoice, Invoice.id == InvoiceDetail.invoice_id
            ).filter(
                InvoiceDetail.service_id == item_id,
                Invoice.workspace_id == workspace_id,
            ).count()
            can_delete = appointment_count == 0 and invoice_detail_count == 0
            reason = (
                f"Không thể xóa vĩnh viễn dịch vụ vì còn "
                f"{appointment_count} lịch hẹn và {invoice_detail_count} "
                f"chi tiết hóa đơn liên quan."
                if not can_delete else ""
            )
            return {
                'can_delete': can_delete,
                'reason': reason,
                'appointment_count': appointment_count,
                'invoice_detail_count': invoice_detail_count,
            }

        return {'can_delete': True, 'reason': ''}

    @classmethod
    def get_permanent_delete_status(cls, item_type, item_id, workspace_id=None):
        """Return safe, workspace-scoped delete readiness for the recycle-bin UI."""
        model = cls._PERMANENT_DELETE_MODELS.get(item_type)
        if model is None or not isinstance(item_id, int) or isinstance(item_id, bool):
            return {'can_delete': False, 'reason': 'Loại dữ liệu không hợp lệ.'}

        if workspace_id is None:
            from services.workspace_service import WorkspaceService
            workspace_id = WorkspaceService.get_current_workspace_id()
        if workspace_id is None:
            return {'can_delete': False, 'reason': 'Không xác định được workspace hiện tại.'}

        record = model.query.filter(
            model.id == item_id,
            model.workspace_id == workspace_id,
        ).first()
        if record is None:
            return {'can_delete': False, 'reason': 'Không tìm thấy bản ghi trong workspace hiện tại.'}
        if record.deleted_at is None:
            return {'can_delete': False, 'reason': 'Chỉ bản ghi đã xóa mềm mới được xóa vĩnh viễn.'}

        return cls._dependency_status(item_type, item_id, workspace_id)

    @classmethod
    def permanent_delete(cls, item_type, item_id, actor=None):
        """Permanently delete one soft-deleted, workspace-scoped business record."""
        model = cls._PERMANENT_DELETE_MODELS.get(item_type)
        if model is None or not isinstance(item_id, int) or isinstance(item_id, bool):
            raise NotFoundException('Loại dữ liệu hoặc mã bản ghi không hợp lệ.')

        from services.workspace_service import WorkspaceService
        workspace_id = WorkspaceService.require_current_workspace_id()
        target = model.query.filter(
            model.id == item_id,
            model.workspace_id == workspace_id,
        ).with_for_update().first()
        if target is None:
            raise NotFoundException('Không tìm thấy bản ghi trong workspace hiện tại.')
        if target.deleted_at is None:
            raise ValidationException('Chỉ bản ghi đã xóa mềm mới được xóa vĩnh viễn.')

        status = cls._dependency_status(item_type, item_id, workspace_id)
        if not status['can_delete']:
            raise ValidationException(status['reason'])

        current_user = AuthService.get_current_user()
        actor_name = actor
        if actor_name is None or not str(actor_name).strip():
            actor_name = AuthService.require_current_username()
        snapshot_name = getattr(target, 'name', None)
        if snapshot_name is None and item_type == 'Appointment':
            snapshot_name = f'Lịch hẹn #{target.id}'
        if snapshot_name is None and item_type == 'Invoice':
            snapshot_name = f'Hóa đơn HD{target.id:06d}'

        try:
            if item_type == 'Invoice':
                details = InvoiceDetail.query.filter(
                    InvoiceDetail.invoice_id == target.id
                ).with_for_update().all()
                for detail in details:
                    db.session.delete(detail)

            db.session.delete(target)
            audit_ok = ActivityLogService.write_log(
                module=item_type,
                action=ActivityLogService.ACTION_PERMANENT_DELETE,
                description=(
                    f'{actor_name} xóa vĩnh viễn {item_type} '
                    f'"{snapshot_name}" (id={item_id}, workspace_id={workspace_id})'
                ),
                reference_id=item_id,
                session_override=db.session,
                commit=False,
                user_id_override=(current_user.id if current_user else None),
                workspace_id=workspace_id,
            )
            if not audit_ok:
                raise ValidationException('Không thể ghi nhật ký xóa vĩnh viễn; thao tác đã được hoàn tác.')
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        return {
            'item_type': item_type,
            'item_id': item_id,
            'workspace_id': workspace_id,
            'name': snapshot_name,
        }

    @staticmethod
    def get_statistics():
        """Retrieve count of all registered deleted items generically."""
        from services.workspace_service import WorkspaceService
        stats = {
            'total': 0,
            'customer': 0,
            'service': 0,
            'appointment': 0,
            'invoice': 0
        }
        for key, config in RecycleBinRegistry.get_all().items():
            model = config['model_class']
            count = WorkspaceService.scoped_query(model).filter(model.deleted_at.isnot(None)).count()
            stats[key.lower()] = count
            stats['total'] += count
        return stats

    @staticmethod
    def get_deleted_items(query='', item_type='', sort_by='newest_deleted', page=1, per_page=10):
        """Retrieve, search, filter, and paginate all soft-deleted records generically."""
        from services.workspace_service import WorkspaceService
        items = []
        registry = RecycleBinRegistry.get_all()
        types_to_fetch = [item_type] if item_type in registry else list(registry.keys())
        
        for k in types_to_fetch:
            config = registry[k]
            model = config['model_class']
            deleted_records = WorkspaceService.scoped_query(model).filter(model.deleted_at.isnot(None)).all()
            for rec in deleted_records:
                delete_status = RecycleBinService.get_permanent_delete_status(
                    k,
                    rec.id,
                    workspace_id=getattr(rec, 'workspace_id', None),
                )
                items.append({
                    'id': rec.id,
                    'type': k,
                    'name': config['get_name_func'](rec),
                    'deleted_at': rec.deleted_at,
                    'deleted_by': rec.deleted_by,
                    'badge_class': config['badge_class'],
                    'vn_name': config['vn_name'],
                    'can_permanently_delete': delete_status['can_delete'],
                    'permanent_delete_reason': delete_status['reason'],
                    'permanent_delete_phrase': RecycleBinService.permanent_delete_phrase(k, rec.id),
                })

        # Apply search query (matching name, type, and Vietnamese translation)
        if query:
            q_lower = query.strip().lower()
            filtered_items = []
            for item in items:
                if (q_lower in item['name'].lower()) or \
                   (q_lower in item['type'].lower()) or \
                   (q_lower in item['vn_name'].lower()):
                    filtered_items.append(item)
            items = filtered_items

        # Apply sorting
        if sort_by == 'oldest_deleted':
            items.sort(key=lambda x: x['deleted_at'] if x['deleted_at'] else datetime.min)
        else: # newest_deleted is default
            items.sort(key=lambda x: x['deleted_at'] if x['deleted_at'] else datetime.min, reverse=True)

        # Paginate using PythonPagination
        return PythonPagination(items, page, per_page)

    @staticmethod
    def cleanup_old_records(days=30):
        """Fail closed because automatic permanent deletion is not supported."""
        raise ValidationException("Tự động xóa vĩnh viễn hiện chưa được hỗ trợ.")


# Register all system models into the Recycle Bin Registry
# Using dynamic imports inside lambdas prevents circular imports at load time.

RecycleBinRegistry.register('Customer', {
    'model_class': Customer,
    'vn_name': 'Khách hàng',
    'badge_class': 'badge-type-customer',
    'get_name_func': lambda item: item.name,
    'restore_func': lambda item_id, actor=None: __import__('services.customer_service', fromlist=['CustomerService']).CustomerService.restore(item_id, actor=actor),
    'info_func': lambda item_id: {
        'name': __import__('services.workspace_service', fromlist=['WorkspaceService']).WorkspaceService.scoped_query(Customer).filter(Customer.id == item_id).first().name if __import__('services.workspace_service', fromlist=['WorkspaceService']).WorkspaceService.scoped_query(Customer).filter(Customer.id == item_id).first() else 'Khách hàng',
        'details': [
            {'label': 'lịch hẹn', 'count': __import__('services.workspace_service', fromlist=['WorkspaceService']).WorkspaceService.scoped_query(Appointment).filter_by(customer_id=item_id).count()},
            {'label': 'hóa đơn', 'count': __import__('services.workspace_service', fromlist=['WorkspaceService']).WorkspaceService.scoped_query(Invoice).filter_by(customer_id=item_id).count()}
        ]
    }
})

RecycleBinRegistry.register('Service', {
    'model_class': Service,
    'vn_name': 'Dịch vụ',
    'badge_class': 'badge-type-service',
    'get_name_func': lambda item: item.name,
    'restore_func': lambda item_id, actor=None: __import__('services.service_service', fromlist=['ServiceService']).ServiceService.restore_service(item_id, actor=actor),
    'info_func': lambda item_id: {
        'name': __import__('services.workspace_service', fromlist=['WorkspaceService']).WorkspaceService.scoped_query(Service).filter(Service.id == item_id).first().name if __import__('services.workspace_service', fromlist=['WorkspaceService']).WorkspaceService.scoped_query(Service).filter(Service.id == item_id).first() else 'Dịch vụ',
        'details': [
            {'label': 'lịch hẹn', 'count': __import__('services.workspace_service', fromlist=['WorkspaceService']).WorkspaceService.scoped_query(Appointment).filter_by(service_id=item_id).count()},
            {'label': 'chi tiết hóa đơn', 'count': __import__('extensions', fromlist=['db']).db.session.query(InvoiceDetail).join(Invoice).filter(Invoice.workspace_id == __import__('services.workspace_service', fromlist=['WorkspaceService']).WorkspaceService.get_current_workspace_id(), InvoiceDetail.service_id == item_id).count()}
        ]
    }
})

RecycleBinRegistry.register('Appointment', {
    'model_class': Appointment,
    'vn_name': 'Lịch hẹn',
    'badge_class': 'badge-type-appointment',
    'get_name_func': lambda item: f"Lịch hẹn #{item.id} - {item.customer.name if item.customer else 'Khách hàng'} ({item.appointment_time.strftime('%d/%m/%Y %H:%M') if item.appointment_time else ''})",
    'restore_func': lambda item_id, actor=None: __import__('services.appointment_service', fromlist=['AppointmentService']).AppointmentService.restore(item_id, actor=actor),
    'info_func': lambda item_id: {
        'name': f"Lịch hẹn #{item_id}" if __import__('services.workspace_service', fromlist=['WorkspaceService']).WorkspaceService.scoped_query(Appointment).filter(Appointment.id == item_id).first() else 'Lịch hẹn',
        'details': []
    }
})

RecycleBinRegistry.register('Invoice', {
    'model_class': Invoice,
    'vn_name': 'Hóa đơn',
    'badge_class': 'badge-type-invoice',
    'get_name_func': lambda item: f"Hóa đơn HD{item.id:06d} - {item.customer.name if item.customer else 'Khách hàng'} ({item.invoice_date.strftime('%d/%m/%Y') if item.invoice_date else ''})",
    'restore_func': lambda item_id, actor=None: __import__('services.invoice_service', fromlist=['InvoiceService']).InvoiceService.restore(item_id, actor=actor),
    'info_func': lambda item_id: {
        'name': f"Hóa đơn HD{item_id:06d}" if __import__('services.workspace_service', fromlist=['WorkspaceService']).WorkspaceService.scoped_query(Invoice).filter(Invoice.id == item_id).first() else 'Hóa đơn',
        'details': [
            {'label': 'chi tiết hóa đơn', 'count': __import__('extensions', fromlist=['db']).db.session.query(InvoiceDetail).join(Invoice).filter(Invoice.workspace_id == __import__('services.workspace_service', fromlist=['WorkspaceService']).WorkspaceService.get_current_workspace_id(), InvoiceDetail.invoice_id == item_id).count()}
        ] if __import__('services.workspace_service', fromlist=['WorkspaceService']).WorkspaceService.scoped_query(Invoice).filter(Invoice.id == item_id).first() else []
    }
})
