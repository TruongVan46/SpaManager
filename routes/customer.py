from flask import render_template, redirect, url_for, request, jsonify
from routes import customer_bp
from services.customer_service import CustomerService
from services.auth_service import AuthService
from utils.pagination import get_pagination_params
from core.exceptions import BusinessException, NotFoundException
from services.notification_service import NotificationService

CUSTOMER_DETAIL_PARTIAL_TEMPLATES = {
    'appointments': 'customer/_appointment_history.html',
    'invoices': 'customer/_invoice_history.html',
}


def _build_customer_detail_url(customer_id, appointment_page, appointment_per_page, invoice_page, invoice_per_page):
    return url_for(
        'customer.detail',
        id=customer_id,
        appointment_page=appointment_page,
        appointment_per_page=appointment_per_page,
        invoice_page=invoice_page,
        invoice_per_page=invoice_per_page,
    )


@customer_bp.route('/customers')
def index():
    query = request.args.get('q', '')
    sort_by  = request.args.get('sort_by', 'id')
    sort_dir = request.args.get('sort_dir', 'desc')
    page, per_page = get_pagination_params()

    customers = CustomerService.search_paginated(
        query, page=page, per_page=per_page,
        sort_by=sort_by, sort_dir=sort_dir
    )
    return render_template(
        'customer/index.html',
        customers=customers, q=query,
        per_page=per_page, sort_by=sort_by, sort_dir=sort_dir
    )

@customer_bp.route('/customers/create', methods=['GET', 'POST'])
def create():
    errors = {}
    form_data = {}
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json() or {}
            name = data.get('name', '').strip()
            phone = data.get('phone', '').strip()
            email = data.get('email', '').strip()
            address = data.get('address', '').strip()
        else:
            name = request.form.get('name', '').strip()
            phone = request.form.get('phone', '').strip()
            email = request.form.get('email', '').strip()
            address = request.form.get('address', '').strip()
        
        form_data = {
            'name': name,
            'phone': phone,
            'email': email,
            'address': address
        }
        
        try:
            CustomerService.create(name=name, phone=phone, email=email, address=address)
            NotificationService.flash_success('Đã lưu khách hàng thành công.')
            return redirect(url_for('customer.index'))
        except BusinessException as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                raise e
            NotificationService.flash_error(e.message)
            errors['general'] = e.message
            if "Số điện thoại" in e.message:
                errors['phone'] = e.message
            elif "Email" in e.message:
                errors['email'] = e.message
            elif "Họ tên" in e.message:
                errors['name'] = e.message
                
    return render_template('customer/create.html', errors=errors, form_data=form_data)

@customer_bp.route('/customers/<int:id>')
def detail(id):
    appointment_page = request.args.get('appointment_page', 1)
    appointment_per_page = request.args.get('appointment_per_page', 10)
    invoice_page = request.args.get('invoice_page', 1)
    invoice_per_page = request.args.get('invoice_per_page', 10)
    detail_data = CustomerService.get_customer_history(
        id,
        appointment_page=appointment_page,
        invoice_page=invoice_page,
        appointment_per_page=appointment_per_page,
        invoice_per_page=invoice_per_page,
    )
    if not detail_data:
        raise NotFoundException("Không tìm thấy khách hàng!")
    detail_data['customer_detail_url'] = _build_customer_detail_url(
        id,
        detail_data['appointment_page'],
        detail_data['appointment_per_page'],
        detail_data['invoice_page'],
        detail_data['invoice_per_page'],
    )
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        partial = request.args.get('partial')
        if partial in CUSTOMER_DETAIL_PARTIAL_TEMPLATES:
            return jsonify({
                'success': True,
                'partial': partial,
                'html': render_template(CUSTOMER_DETAIL_PARTIAL_TEMPLATES[partial], **detail_data),
                'url': detail_data['customer_detail_url'],
            })
        if partial is not None:
            return jsonify({'success': False, 'message': 'Partial không hợp lệ.'}), 400
    return render_template('customer/detail.html', **detail_data)

@customer_bp.route('/customers/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    customer = CustomerService.get_by_id(id)
    if not customer:
        raise NotFoundException("Không tìm thấy khách hàng!")
        
    errors = {}
    form_data = {
        'name': customer.name,
        'phone': customer.phone or '',
        'email': customer.email or '',
        'address': customer.address or ''
    }
    
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json() or {}
            name = data.get('name', '').strip()
            phone = data.get('phone', '').strip()
            email = data.get('email', '').strip()
            address = data.get('address', '').strip()
        else:
            name = request.form.get('name', '').strip()
            phone = request.form.get('phone', '').strip()
            email = request.form.get('email', '').strip()
            address = request.form.get('address', '').strip()
        
        form_data = {
            'name': name,
            'phone': phone,
            'email': email,
            'address': address
        }
        
        try:
            CustomerService.update(id, name=name, phone=phone, email=email, address=address)
            NotificationService.flash_success('Đã lưu khách hàng thành công.')
            return redirect(url_for('customer.index'))
        except BusinessException as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                raise e
            NotificationService.flash_error(e.message)
            errors['general'] = e.message
            if "Số điện thoại" in e.message:
                errors['phone'] = e.message
            elif "Email" in e.message:
                errors['email'] = e.message
            elif "Họ tên" in e.message:
                errors['name'] = e.message
                
    return render_template('customer/edit.html', customer=customer, errors=errors, form_data=form_data)

@customer_bp.route('/customers/<int:id>/can-delete', methods=['GET'])
def check_can_delete(id):
    customer = CustomerService.get_by_id(id)
    if not customer:
        raise NotFoundException("Không tìm thấy khách hàng")
    
    status = CustomerService.can_delete(id)
    return jsonify({
        'success': True,
        'customer_name': customer.name,
        'can_delete': status['can_delete'],
        'appointment_count': status['appointment_count'],
        'invoice_count': status['invoice_count']
    })

@customer_bp.route('/customers/<int:id>/delete', methods=['POST'])
def delete(id):
    from core.error_handler import ErrorHandler
    is_ajax = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.is_json
        or 'application/json' in request.headers.get('Accept', '')
        or ErrorHandler.is_json_request()
    )
    try:
        CustomerService.delete(id, actor=AuthService.require_current_username())
        if is_ajax:
            return jsonify({'success': True, 'message': 'Đã xóa khách hàng thành công.'})
        NotificationService.flash_success('Đã xóa khách hàng thành công.')
    except BusinessException as e:
        if is_ajax:
            return jsonify({'success': False, 'message': e.message}), e.status_code
        NotificationService.flash_error(e.message)
    return redirect(url_for('customer.index'))

@customer_bp.route('/customers/search')
def search():
    query = request.args.get('q', '')
    customers = CustomerService.search(query)
    return jsonify([{
        'id': c.id,
        'text': f"{c.name} - {c.phone if c.phone else ''}"
    } for c in customers])
