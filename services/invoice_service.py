from datetime import datetime

from sqlalchemy import or_, cast, String, func

from extensions import db
from models.invoice import Invoice
from models.invoice_detail import InvoiceDetail
from models.service import Service
from models.customer import Customer
from core.exceptions import ValidationException
from core.exceptions import AuthenticationException
from core.cache import dashboard_cache
from services.auth_service import AuthService
from validators.invoice_validator import InvoiceValidator
from services.activity_log_service import ActivityLogService
from utils.timezone_utils import local_today, utc_now


class InvoiceService:
    PAYMENT_METHOD_LABELS = {
        "cash": "Tiền mặt",
        "card": "Thẻ",
        "transfer": "Chuyển khoản",
        "bank_transfer": "Chuyển khoản",
        "momo": "MoMo",
        "vnpay": "VNPay",
        "paid": "Đã thanh toán",
        "unpaid": "Chưa thanh toán",
        "partial": "Thanh toán một phần",
        "pending": "Chờ xử lý",
        "cancelled": "Đã hủy",
        "canceled": "Đã hủy",
        "refunded": "Đã hoàn tiền",
        "unknown": "Không rõ",
    }
    PAYMENT_METHOD_FILTER_ALIASES = {
        "cash": {"cash", "tiền mặt"},
        "card": {"card", "thẻ"},
        "transfer": {"transfer", "bank_transfer", "chuyển khoản"},
        "bank_transfer": {"transfer", "bank_transfer", "chuyển khoản"},
        "momo": {"momo", "ví điện tử"},
        "vnpay": {"vnpay", "ví điện tử"},
        "paid": {"paid", "đã thanh toán"},
        "unpaid": {"unpaid", "chưa thanh toán"},
        "partial": {"partial", "thanh toán một phần"},
        "pending": {"pending", "chờ xử lý"},
        "cancelled": {"cancelled", "canceled", "đã hủy"},
        "canceled": {"cancelled", "canceled", "đã hủy"},
        "refunded": {"refunded", "đã hoàn tiền"},
        "unknown": {"unknown", "không rõ"},
    }

    @staticmethod
    def _normalize_payment_method(value):
        normalized = (value or "").strip().lower()
        if not normalized or normalized == "none":
            return None
        for canonical, aliases in InvoiceService.PAYMENT_METHOD_FILTER_ALIASES.items():
            if normalized in aliases:
                return canonical
        return normalized

    @staticmethod
    def _payment_method_display_label(payment_method):
        canonical = InvoiceService._normalize_payment_method(payment_method)
        if not canonical:
            return "Không rõ"
        return InvoiceService.PAYMENT_METHOD_LABELS.get(canonical, payment_method if payment_method else "Không rõ")

    @staticmethod
    def _payment_method_filter_values(payment_method):
        normalized = (payment_method or "").strip().lower()
        if not normalized or normalized == "none":
            return set()
        for aliases in InvoiceService.PAYMENT_METHOD_FILTER_ALIASES.values():
            if normalized in aliases:
                return aliases
        return {normalized}

    @staticmethod
    def _attach_display_fields(invoice_or_invoices):
        if not invoice_or_invoices:
            return invoice_or_invoices
        if isinstance(invoice_or_invoices, list):
            for invoice in invoice_or_invoices:
                invoice.display_payment_method = InvoiceService._payment_method_display_label(invoice.payment_method)
            return invoice_or_invoices
        invoice_or_invoices.display_payment_method = InvoiceService._payment_method_display_label(invoice_or_invoices.payment_method)
        return invoice_or_invoices

    @staticmethod
    def get_by_id(invoice_id):
        """Lấy hóa đơn hoạt động theo ID"""
        from services.workspace_service import WorkspaceService
        invoice = WorkspaceService.scoped_query(Invoice).filter(Invoice.id == invoice_id, Invoice.deleted_at.is_(None)).first()
        return InvoiceService._attach_display_fields(invoice)

    @staticmethod
    def get_all():
        """Lấy tất cả hóa đơn hoạt động"""
        from services.workspace_service import WorkspaceService
        invoices = WorkspaceService.scoped_query(Invoice).options(db.joinedload(Invoice.customer)).filter(Invoice.deleted_at.is_(None)).order_by(Invoice.id.asc()).all()
        return InvoiceService._attach_display_fields(invoices)

    @staticmethod
    def get_all_paginated(page, per_page=10):
        """Lấy danh sách hóa đơn hoạt động phân trang"""
        from services.workspace_service import WorkspaceService
        pagination = WorkspaceService.scoped_query(Invoice).options(db.joinedload(Invoice.customer)).filter(Invoice.deleted_at.is_(None)).order_by(Invoice.id.desc()).paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
        InvoiceService._attach_display_fields(pagination.items)
        return pagination

    @staticmethod
    def _build_filtered_invoices_query(keyword=None, from_date=None, to_date=None, payment_method=None, sort_by=None, order=None):
        from services.workspace_service import WorkspaceService
        query = WorkspaceService.scoped_query(Invoice).join(Customer).options(db.contains_eager(Invoice.customer)).filter(Invoice.deleted_at.is_(None))

        # Apply date filters
        if from_date:
            if isinstance(from_date, str):
                try:
                    from_date = datetime.strptime(from_date.strip(), "%Y-%m-%d").date()
                except ValueError:
                    pass
            elif isinstance(from_date, datetime):
                from_date = from_date.date()
            query = query.filter(Invoice.invoice_date >= from_date)

        if to_date:
            if isinstance(to_date, str):
                try:
                    to_date = datetime.strptime(to_date.strip(), "%Y-%m-%d").date()
                except ValueError:
                    pass
            elif isinstance(to_date, datetime):
                to_date = to_date.date()
            query = query.filter(Invoice.invoice_date <= to_date)

        # Apply payment method filter
        if payment_method and payment_method != "Tất cả":
            aliases = InvoiceService._payment_method_filter_values(payment_method)
            if aliases:
                query = query.filter(
                    or_(*[func.lower(Invoice.payment_method) == alias for alias in aliases])
                )

        # Apply keyword filters
        if keyword:
            cleaned = keyword.strip()
            conditions = []
            conditions.append(Customer.name.ilike(f"%{cleaned}%"))
            conditions.append(Customer.phone.ilike(f"%{cleaned}%"))

            # Invoice ID parsing logic
            if cleaned.lower().startswith('hd'):
                id_str = cleaned[2:].lstrip('0')
                if id_str:
                    try:
                        conditions.append(Invoice.id == int(id_str))
                    except ValueError:
                        pass
                else:
                    try:
                        conditions.append(Invoice.id == int(cleaned[2:]))
                    except ValueError:
                        pass
            else:
                try:
                    conditions.append(Invoice.id == int(cleaned))
                except ValueError:
                    pass
                conditions.append(cast(Invoice.id, String).ilike(f"%{cleaned}%"))

            query = query.filter(or_(*conditions))

        # Apply sorting
        if not sort_by:
            sort_by = 'date'
        if not order:
            order = 'desc'

        if order == 'asc':
            if sort_by == 'date':
                query = query.order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
            elif sort_by == 'id':
                query = query.order_by(Invoice.id.asc())
            elif sort_by == 'total':
                query = query.order_by(Invoice.total_amount.asc())
            elif sort_by == 'customer':
                query = query.order_by(Customer.name.asc())
            else:
                query = query.order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
        else: # desc
            if sort_by == 'date':
                query = query.order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
            elif sort_by == 'id':
                query = query.order_by(Invoice.id.desc())
            elif sort_by == 'total':
                query = query.order_by(Invoice.total_amount.desc())
            elif sort_by == 'customer':
                query = query.order_by(Customer.name.desc())
            else:
                query = query.order_by(Invoice.invoice_date.desc(), Invoice.id.desc())

        return query

    @staticmethod
    def get_invoice_summary(keyword=None, from_date=None, to_date=None, payment_method=None):
        from services.workspace_service import WorkspaceService
        query = db.session.query(
            func.count(Invoice.id).label('invoice_count'),
            func.sum(Invoice.total_amount).label('total_revenue'),
            func.sum(Invoice.discount).label('total_discount')
        ).join(Customer).filter(Invoice.deleted_at.is_(None))
        wid = WorkspaceService.get_current_workspace_id()
        if wid is None:
            query = query.filter(Invoice.workspace_id == -1)
        else:
            query = query.filter(Invoice.workspace_id == wid)

        # Apply date filters
        if from_date:
            if isinstance(from_date, str):
                try:
                    from_date = datetime.strptime(from_date.strip(), "%Y-%m-%d").date()
                except ValueError:
                    pass
            elif isinstance(from_date, datetime):
                from_date = from_date.date()
            query = query.filter(Invoice.invoice_date >= from_date)

        if to_date:
            if isinstance(to_date, str):
                try:
                    to_date = datetime.strptime(to_date.strip(), "%Y-%m-%d").date()
                except ValueError:
                    pass
            elif isinstance(to_date, datetime):
                to_date = to_date.date()
            query = query.filter(Invoice.invoice_date <= to_date)

        # Apply payment method filter
        if payment_method and payment_method != "Tất cả":
            aliases = InvoiceService._payment_method_filter_values(payment_method)
            if aliases:
                query = query.filter(
                    or_(*[func.lower(Invoice.payment_method) == alias for alias in aliases])
                )

        # Apply keyword filters
        if keyword:
            cleaned = keyword.strip()
            conditions = []
            conditions.append(Customer.name.ilike(f"%{cleaned}%"))
            conditions.append(Customer.phone.ilike(f"%{cleaned}%"))

            # Invoice ID parsing logic
            if cleaned.lower().startswith('hd'):
                id_str = cleaned[2:].lstrip('0')
                if id_str:
                    try:
                        conditions.append(Invoice.id == int(id_str))
                    except ValueError:
                        pass
                else:
                    try:
                        conditions.append(Invoice.id == int(cleaned[2:]))
                    except ValueError:
                        pass
            else:
                try:
                    conditions.append(Invoice.id == int(cleaned))
                except ValueError:
                    pass
                conditions.append(cast(Invoice.id, String).ilike(f"%{cleaned}%"))

            query = query.filter(or_(*conditions))

        row = query.first()

        invoice_count = row.invoice_count or 0
        total_revenue = float(row.total_revenue or 0.0)
        total_discount = float(row.total_discount or 0.0)
        average_invoice = total_revenue / invoice_count if invoice_count > 0 else 0.0

        return {
            "invoice_count": invoice_count,
            "total_revenue": total_revenue,
            "total_discount": total_discount,
            "average_invoice": average_invoice
        }

    @staticmethod
    def get_filtered_invoices(keyword=None, from_date=None, to_date=None, payment_method=None, sort_by=None, order=None):
        query = InvoiceService._build_filtered_invoices_query(
            keyword=keyword,
            from_date=from_date,
            to_date=to_date,
            payment_method=payment_method,
            sort_by=sort_by,
            order=order
        )
        invoices = query.all()
        return InvoiceService._attach_display_fields(invoices)

    @staticmethod
    def search_invoices(keyword, page=1, per_page=10, from_date=None, to_date=None, payment_method=None, sort_by=None, order=None):
        query = InvoiceService._build_filtered_invoices_query(
            keyword=keyword,
            from_date=from_date,
            to_date=to_date,
            payment_method=payment_method,
            sort_by=sort_by,
            order=order
        )
        pagination = query.paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
        InvoiceService._attach_display_fields(pagination.items)
        return pagination

    @staticmethod
    def create_invoice(data):
        """
        Tạo hóa đơn mới
        """

        items = data.get("items", [])
        discount = float(data.get("discount", 0) or 0)

        subtotal = 0.0
        processed_items = []
        for item in items:
            service_id = item.get("service_id")
            if not service_id:
                raise ValidationException("Thông tin dịch vụ là bắt buộc.")

            from services.service_service import ServiceService
            service = ServiceService.get_service_by_id(int(service_id))
            if not service:
                raise ValidationException(f"Dịch vụ ID {service_id} không tồn tại hoặc không thuộc Workspace này.")

            quantity = int(item.get("quantity", 1))
            try:
                price = float(item.get("price", service.price))
            except (ValueError, TypeError):
                price = service.price

            if price < 0:
                raise ValidationException("Đơn giá không được âm.")

            item_total = quantity * price
            subtotal += item_total
            processed_items.append({
                "service_id": int(service_id),
                "quantity": quantity,
                "price": price
            })

        total_amount = subtotal - discount

        # 1. Validation
        from services.customer_service import CustomerService
        if data.get('customer_id') and not CustomerService.get_by_id(data.get('customer_id')):
            raise ValidationException("Khách hàng không tồn tại hoặc không thuộc Workspace này.")

        validation_data = {
            'customer_id': data.get('customer_id'),
            'services': processed_items,
            'total_amount': total_amount
        }
        validator = InvoiceValidator()
        validator.validate(validation_data)
        validator.raise_if_invalid("Thông tin hóa đơn không hợp lệ.")

        invoice_date_val = data.get("invoice_date")
        if isinstance(invoice_date_val, str) and invoice_date_val:
            try:
                invoice_date_val = datetime.strptime(invoice_date_val.strip(), "%Y-%m-%d").date()
            except ValueError:
                invoice_date_val = local_today()
        elif not invoice_date_val:
            invoice_date_val = local_today()

        try:
            invoice = Invoice(
                customer_id=data.get("customer_id"),
                invoice_date=invoice_date_val,
                payment_method=data.get("payment_method"),
                notes=data.get("notes"),
                subtotal=subtotal,
                discount=discount,
                total_amount=total_amount
            )
            from services.workspace_service import WorkspaceService
            WorkspaceService.assign_workspace(invoice)
            db.session.add(invoice)
            db.session.flush()

            for item in processed_items:
                detail = InvoiceDetail(
                    invoice_id=invoice.id,
                    service_id=item["service_id"],
                    quantity=item["quantity"],
                    price=item["price"]
                )
                db.session.add(detail)

            db.session.commit()
            InvoiceService._attach_display_fields(invoice)
            ActivityLogService.log_create(
                module=ActivityLogService.MODULE_INVOICE,
                description=f'Tạo hóa đơn HD{invoice.id:06d}',
                reference_id=invoice.id
            )

            dashboard_cache.invalidate('dashboard_data')
            return invoice

        except Exception as e:
            db.session.rollback()
            raise e

    @staticmethod
    def delete_invoice(invoice_id, actor=None):
        """Xóa mềm hóa đơn và chuyển vào thùng rác"""
        from services.workspace_service import WorkspaceService
        invoice = WorkspaceService.scoped_query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice or invoice.deleted_at is not None:
            return False

        try:
            actor_name = actor
            if actor_name is None or not str(actor_name).strip():
                actor_name = AuthService.require_current_username()
            current_user = AuthService.get_current_user()
            invoice.deleted_at = utc_now()
            invoice.deleted_by = actor_name
            ActivityLogService.write_log(
                module=ActivityLogService.MODULE_INVOICE,
                action=ActivityLogService.ACTION_DELETE,
                description=f'{actor_name} chuyển hóa đơn HD{invoice.id:06d} vào Thùng rác',
                reference_id=invoice_id,
                session_override=db.session,
                commit=False,
                user_id_override=current_user.id if current_user and actor_name != "Hệ thống" else None
            )
            db.session.commit()
            dashboard_cache.invalidate('dashboard_data')
            return True
        except AuthenticationException:
            raise
        except Exception:
            db.session.rollback()
            db.session.remove()
            raise

    @staticmethod
    def restore(invoice_id, actor=None):
        """Khôi phục hóa đơn từ Thùng rác"""
        from services.workspace_service import WorkspaceService
        invoice = WorkspaceService.scoped_query(Invoice).filter(Invoice.id == invoice_id).first()
        if invoice and invoice.deleted_at is not None:
            try:
                actor_name = actor
                if actor_name is None or not str(actor_name).strip():
                    actor_name = AuthService.require_current_username()
                current_user = AuthService.get_current_user()
                # Kiểm tra quan hệ dữ liệu: Khách hàng liên quan phải tồn tại trong workspace
                from services.customer_service import CustomerService
                customer = CustomerService.get_by_id(invoice.customer_id) if invoice.customer_id else None
                if invoice.customer_id and not customer:
                    raise ValueError(f"Không thể khôi phục hóa đơn vì khách hàng liên quan đã bị xóa vĩnh viễn khỏi hệ thống hoặc thuộc Workspace khác.")

                # Kiểm tra quan hệ dữ liệu: Tất cả dịch vụ trong chi tiết hóa đơn phải tồn tại trong workspace
                from services.service_service import ServiceService
                for detail in invoice.details:
                    service = ServiceService.get_service_by_id(detail.service_id)
                    if not service:
                        raise ValueError(f"Không thể khôi phục hóa đơn vì một hoặc nhiều dịch vụ liên quan đã bị xóa vĩnh viễn khỏi hệ thống.")

                invoice.deleted_at = None
                invoice.deleted_by = None
                ActivityLogService.write_log(
                    module=ActivityLogService.MODULE_INVOICE,
                    action=ActivityLogService.ACTION_RESTORE,
                    description=f'{actor_name} khôi phục hóa đơn HD{invoice.id:06d} từ Thùng rác',
                    reference_id=invoice_id,
                    severity=ActivityLogService.SEVERITY_SUCCESS,
                    session_override=db.session,
                    commit=False,
                    user_id_override=current_user.id if current_user and actor_name != "Hệ thống" else None
                )
                db.session.commit()
            except AuthenticationException:
                raise
            except Exception:
                db.session.rollback()
                db.session.remove()
                raise
            dashboard_cache.invalidate('dashboard_data')
            return True
        return False

    @staticmethod
    def permanent_delete(invoice_id, actor=None):
        """Xóa vĩnh viễn hóa đơn khỏi cơ sở dữ liệu"""
        from services.workspace_service import WorkspaceService
        invoice = WorkspaceService.scoped_query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            return False

        try:
            # Xóa các chi tiết hóa đơn liên quan trước
            actor_name = actor
            if actor_name is None or not str(actor_name).strip():
                actor_name = AuthService.require_current_username()
            current_user = AuthService.get_current_user()
            ActivityLogService.write_log(
                module=ActivityLogService.MODULE_INVOICE,
                action='PERMANENT_DELETE',
                description=f'{actor_name} xóa vĩnh viễn hóa đơn HD{invoice_id:06d} khỏi cơ sở dữ liệu',
                reference_id=invoice_id,
                severity=ActivityLogService.SEVERITY_WARNING,
                session_override=db.session,
                commit=False,
                user_id_override=current_user.id if current_user and actor_name != "Hệ thống" else None
            )
            for detail in invoice.details:
                db.session.delete(detail)

            db.session.delete(invoice)
            db.session.commit()
            dashboard_cache.invalidate('dashboard_data')
            return True
        except AuthenticationException:
            raise
        except Exception:
            db.session.rollback()
            db.session.remove()
            raise
