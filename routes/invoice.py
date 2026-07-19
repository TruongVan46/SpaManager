from flask import render_template, request, redirect, url_for, flash, jsonify
from routes import invoice_bp
from models.setting import Setting
from services.customer_service import CustomerService
from services.service_service import ServiceService
from services.invoice_service import InvoiceService
from datetime import datetime
from flask import send_file
from utils.export_excel import generate_invoice_excel
from utils.export_pdf import generate_invoice_pdf
from utils.pagination import get_pagination_params
from utils.timezone_utils import local_now
from services.auth_service import AuthService
from core.exceptions import BusinessException
from utils.navigation import safe_return_url
















def _build_invoice_create_url(customer_id=None, return_to=None):
    params = {}
    if customer_id:
        params['customer_id'] = customer_id
    if return_to:
        params['return_to'] = return_to
    return url_for('invoice.create', **params)


def _apply_pdf_download_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response
@invoice_bp.route('/invoices')
def index():
    q = request.args.get('q', '').strip()
    from_date = request.args.get('from_date', '').strip()
    to_date = request.args.get('to_date', '').strip()
    payment_method = request.args.get('payment_method', '').strip()
    sort_by = request.args.get('sort_by', 'date').strip()
    order = request.args.get('order', 'desc').strip()
    
    page, per_page = get_pagination_params()
        
    invoices_pagination = InvoiceService.search_invoices(
        keyword=q,
        page=page,
        per_page=per_page,
        from_date=from_date if from_date else None,
        to_date=to_date if to_date else None,
        payment_method=payment_method if payment_method else None,
        sort_by=sort_by,
        order=order
    )
    
    summary = InvoiceService.get_invoice_summary(
        keyword=q,
        from_date=from_date if from_date else None,
        to_date=to_date if to_date else None,
        payment_method=payment_method if payment_method else None
    )
        
    return render_template(
        'invoice/index.html',
        invoices=invoices_pagination,
        q=q,
        from_date=from_date,
        to_date=to_date,
        payment_method=payment_method,
        sort_by=sort_by,
        order=order,
        per_page=per_page,
        summary=summary
    )

@invoice_bp.route('/invoices/create', methods=['GET', 'POST'])
def create():
    return_to = safe_return_url(request.args.get('return_to') or request.form.get('return_to'))
    back_url = return_to or url_for('invoice.index')

    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        invoice_date = request.form.get('invoice_date')
        payment_method = request.form.get('payment_method')
        notes = request.form.get('notes')
        
        try:
            discount = float(request.form.get('discount', 0) or 0)
        except ValueError:
            discount = 0

        service_ids = request.form.getlist('service_id[]')
        quantities = request.form.getlist('quantity[]')
        prices = request.form.getlist('price[]')
        
        # Validation
        errors = []
        if not customer_id:
            errors.append("Vui lòng chọn khách hàng.")
        if not invoice_date:
            errors.append("Vui lòng chọn ngày lập hóa đơn.")
        
        items = []
        for s_id, qty, price in zip(service_ids, quantities, prices):
            if not s_id:
                continue
            try:
                q = int(qty)
                p = float(price)

                if q < 1:
                    errors.append("Số lượng dịch vụ phải >= 1")

                if p < 0:
                    errors.append("Đơn giá không hợp lệ")

                if q >= 1 and p >= 0:
                    items.append({
                        "service_id": int(s_id),
                        "quantity": q,
                        "price": float(price)
                    })

            except ValueError:
                errors.append("Dữ liệu dịch vụ không hợp lệ.")

        if not items:
            errors.append("Vui lòng chọn ít nhất một dịch vụ.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return redirect(_build_invoice_create_url(customer_id, return_to))

        # Prepare data for service
        try:
            formatted_date = None
            if invoice_date:
                formatted_date = datetime.strptime(invoice_date, "%Y-%m-%d").date()

            data = {
                "customer_id": customer_id,
                "invoice_date": formatted_date,
                "payment_method": payment_method,
                "notes": notes,
                "discount": discount,
                "items": items
            }
            
            InvoiceService.create_invoice(data)
            flash("Tạo hóa đơn thành công.", "success")
            return redirect(return_to or url_for("invoice.index"))
        except Exception as e:
            flash(f"Lỗi khi tạo hóa đơn: {str(e)}", "danger")
            return redirect(_build_invoice_create_url(customer_id, return_to))

    customers = CustomerService.get_all()
    services = ServiceService.get_all_services()
    selected_customer_id = request.args.get('customer_id', type=int)
    selected_customer_name = None
    if selected_customer_id:
        selected_customer = CustomerService.get_by_id(selected_customer_id)
        if selected_customer:
            selected_customer_name = selected_customer.name
    return render_template(
        "invoice/create.html",
        customers=customers,
        services=services,
        selected_customer_id=selected_customer_id,
        selected_customer_name=selected_customer_name,
        return_to=return_to,
        back_url=back_url,
    )

@invoice_bp.route('/invoices/<int:invoice_id>')
def detail(invoice_id):
    invoice = InvoiceService.get_by_id(invoice_id)
    if not invoice:
        flash("Hóa đơn không tồn tại.", "danger")
        return redirect(url_for('invoice.index'))
    return_to = safe_return_url(request.args.get('return_to') or request.args.get('return_url'))
    back_url = return_to or url_for('invoice.index')
    return render_template('invoice/detail.html', invoice=invoice, back_url=back_url)

@invoice_bp.route('/invoices/print/<int:invoice_id>')
def print_invoice(invoice_id):
    invoice = InvoiceService.get_by_id(invoice_id)
    if not invoice:
        flash("Hóa đơn không tồn tại.", "danger")
        return redirect(url_for('invoice.index'))
    
    settings = Setting.get_workspace_settings_dict()
    return_to = safe_return_url(request.args.get('return_to') or request.args.get('return_url'))
    back_url = return_to or url_for('invoice.index')
    return render_template('invoice/print.html', invoice=invoice, settings=settings, back_url=back_url)

@invoice_bp.route('/invoices/delete/<int:invoice_id>', methods=['POST'])
def delete(invoice_id):
    try:
        success = InvoiceService.delete_invoice(invoice_id, actor=AuthService.require_current_username())

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            if success:
                return _ajax_invoice_delete_ok()
            else:
                return jsonify({'success': False, 'message': 'Không tìm thấy hóa đơn để xóa.'})

        if not success:
            flash('Không tìm thấy hóa đơn để xóa.', 'danger')
        else:
            flash('Xóa hóa đơn thành công', 'success')

        return_url = safe_return_url(request.args.get('return_url') or request.form.get('return_url'))
        if return_url:
            return redirect(return_url)
        return redirect(url_for('invoice.index'))
    except BusinessException as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': False, 'message': e.message}), e.status_code
        flash(e.message, 'danger')
        return redirect(url_for('invoice.index'))

@invoice_bp.route('/invoices/export/excel')
def export_excel():
    q = request.args.get('q', '').strip()
    from_date = request.args.get('from_date', '').strip()
    to_date = request.args.get('to_date', '').strip()
    payment_method = request.args.get('payment_method', '').strip()
    sort_by = request.args.get('sort_by', 'date').strip()
    order = request.args.get('order', 'desc').strip()
    
    invoices = InvoiceService.get_filtered_invoices(
        keyword=q,
        from_date=from_date if from_date else None,
        to_date=to_date if to_date else None,
        payment_method=payment_method if payment_method else None,
        sort_by=sort_by,
        order=order
    )
    
    summary = InvoiceService.get_invoice_summary(
        keyword=q,
        from_date=from_date if from_date else None,
        to_date=to_date if to_date else None,
        payment_method=payment_method if payment_method else None
    )
    
    excel_stream = generate_invoice_excel(invoices, summary)
    
    filename = f"Danh_sach_hoa_don_{local_now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        excel_stream,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename
    )

@invoice_bp.route('/invoices/export/pdf')
def export_pdf():
    q = request.args.get('q', '').strip()
    from_date = request.args.get('from_date', '').strip()
    to_date = request.args.get('to_date', '').strip()
    payment_method = request.args.get('payment_method', '').strip()
    sort_by = request.args.get('sort_by', 'date').strip()
    order = request.args.get('order', 'desc').strip()
    
    invoices = InvoiceService.get_filtered_invoices(
        keyword=q,
        from_date=from_date if from_date else None,
        to_date=to_date if to_date else None,
        payment_method=payment_method if payment_method else None,
        sort_by=sort_by,
        order=order
    )
    
    summary = InvoiceService.get_invoice_summary(
        keyword=q,
        from_date=from_date if from_date else None,
        to_date=to_date if to_date else None,
        payment_method=payment_method if payment_method else None
    )
    
    pdf_stream = generate_invoice_pdf(
        invoices=invoices,
        summary=summary,
        keyword=q if q else None,
        from_date=from_date if from_date else None,
        to_date=to_date if to_date else None,
        payment_method=payment_method if payment_method else None
    )
    
    filename = f"Danh_sach_hoa_don_{local_now().strftime('%Y%m%d_%H%M%S_%f')}.pdf"
    response = send_file(
        pdf_stream,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
    )
    return _apply_pdf_download_headers(response)


def _ajax_invoice_delete_ok():
    """Return a JSON success response for invoice soft-delete, including filtered KPI counts."""
    q = request.args.get('q', '').strip()
    from_date = request.args.get('from_date', '').strip()
    to_date = request.args.get('to_date', '').strip()
    payment_method = request.args.get('payment_method', '').strip()
    summary = InvoiceService.get_invoice_summary(
        keyword=q if q else None,
        from_date=from_date if from_date else None,
        to_date=to_date if to_date else None,
        payment_method=payment_method if payment_method else None
    )
    return jsonify({'success': True, 'message': 'Đã xóa hóa đơn thành công.', 'counts': summary})
