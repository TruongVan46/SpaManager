from flask import render_template, redirect, url_for, request, jsonify
from routes import customer_bp
from services.customer_service import CustomerService
from utils.pagination import get_pagination_params
from core.exceptions import BusinessException, NotFoundException
from services.notification_service import NotificationService

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
    customer = CustomerService.get_by_id(id)
    if not customer:
        raise NotFoundException("Không tìm thấy khách hàng!")
    return render_template('customer/detail.html', customer=customer)

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
    try:
        CustomerService.delete(id)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': True, 'message': 'Đã xóa khách hàng thành công.'})
        NotificationService.flash_success('Đã xóa khách hàng thành công.')
    except BusinessException as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': False, 'message': e.message})
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
