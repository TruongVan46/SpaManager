from flask import render_template, request, redirect, url_for, jsonify
from routes import service_bp
from services.service_service import ServiceService
from utils.pagination import get_pagination_params
from core.exceptions import BusinessException, NotFoundException
from services.notification_service import NotificationService

@service_bp.route('/services')
def index():
    query = request.args.get('q', '')
    service_type = request.args.get('service_type', '')
    sort_by  = request.args.get('sort_by', 'name')
    sort_dir = request.args.get('sort_dir', 'asc')
    page, per_page = get_pagination_params()

    services = ServiceService.get_services_paginated(
        query=query, service_type=service_type,
        page=page, per_page=per_page,
        sort_by=sort_by, sort_dir=sort_dir
    )
    return render_template(
        'service/index.html',
        services=services, q=query,
        service_type=service_type, per_page=per_page,
        sort_by=sort_by, sort_dir=sort_dir
    )

@service_bp.route('/services/create', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form.to_dict()
            ServiceService.create_service(data)
            NotificationService.flash_success('Thêm dịch vụ thành công!')
            return redirect(url_for('service.index'))
        except BusinessException as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                raise e
            NotificationService.flash_error(e.message)
    
    return render_template('service/create.html')

@service_bp.route('/services/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    service = ServiceService.get_service_by_id(id)
    if not service:
        raise NotFoundException("Không tìm thấy dịch vụ!")

    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form.to_dict()
            ServiceService.update_service(id, data)
            NotificationService.flash_success('Cập nhật dịch vụ thành công!')
            return redirect(url_for('service.index'))
        except BusinessException as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                raise e
            NotificationService.flash_error(e.message)

    return render_template('service/edit.html', service=service)

@service_bp.route('/services/delete/<int:id>', methods=['POST'])
def delete(id):
    ServiceService.delete_service(id)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({'success': True, 'message': 'Đã chuyển dịch vụ vào Thùng rác.'})
    NotificationService.flash_success('Đã chuyển dịch vụ vào Thùng rác.')
    return redirect(url_for('service.index'))