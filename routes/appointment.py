from flask import render_template, request, jsonify, flash, redirect, url_for
from routes import appointment_bp
from services.appointment_service import AppointmentService
from services.customer_service import CustomerService
from services.service_service import ServiceService
from models.appointment import Appointment
from datetime import datetime
from utils.pagination import get_pagination_params
from core.exceptions import BusinessException
from services.notification_service import NotificationService

@appointment_bp.route('/appointments')
def index():
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    sort_by = request.args.get('sort_by', 'date')
    order = request.args.get('order', 'desc')
    period = request.args.get('period', '')
    
    page, per_page = get_pagination_params()
    
    appointments = AppointmentService.get_filtered(
        search=search, status=status,
        from_date=from_date, to_date=to_date,
        sort_by=sort_by, order=order,
        page=page, per_page=per_page, period=period
    )
    summary = AppointmentService.get_appointment_summary(
        search=search, status=status,
        from_date=from_date, to_date=to_date, period=period
    )
    return render_template(
        'appointment/index.html',
        appointments=appointments, summary=summary,
        per_page=per_page, sort_by=sort_by, order=order
    )

@appointment_bp.route('/appointments/create', methods=['GET', 'POST'])
def create():
    if request.method == 'GET':
        customers = CustomerService.get_all()
        services = ServiceService.get_all_services()
        current_date = datetime.now().strftime('%Y-%m-%d')
        return render_template('appointment/create.html', customers=customers, services=services, current_date=current_date)

    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        service_id = request.form.get('service_id')
        appointment_date = request.form.get('appointment_date')
        appointment_time = request.form.get('appointment_time')
        status = request.form.get('status')
        notes = request.form.get('notes')

        try:
            AppointmentService.create_appointment(
                customer_id=customer_id,
                service_id=service_id,
                appointment_date=appointment_date,
                appointment_time=appointment_time,
                notes=notes,
                status=status
            )
            NotificationService.flash_success('Đã tạo lịch hẹn thành công.')
            return redirect(url_for('appointment.index'))
        except BusinessException as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                raise e
            NotificationService.flash_error(e.message)
            customers = CustomerService.get_all()
            services = ServiceService.get_all_services()
            current_date = datetime.now().strftime('%Y-%m-%d')
            form_data = {
                'customer_id': customer_id,
                'service_id': service_id,
                'appointment_date': appointment_date,
                'appointment_time': appointment_time,
                'status': status,
                'notes': notes
            }
            return render_template('appointment/create.html', customers=customers, services=services, current_date=current_date, form_data=form_data)

@appointment_bp.route('/appointments/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    if request.method == 'GET':
        appointment = AppointmentService.get_by_id(id)
        if not appointment:
            flash('Không tìm thấy lịch hẹn.', 'danger')
            return redirect(url_for('appointment.index'))
        
        customers = CustomerService.get_all()
        services = ServiceService.get_all_services()
        current_datetime = datetime.now().strftime('%Y-%m-%dT%H:%M')
        return render_template('appointment/edit.html', appointment=appointment, customers=customers, services=services, current_datetime=current_datetime)

    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        service_id = request.form.get('service_id')
        appointment_datetime_str = request.form.get('appointment_time', '')
        status = request.form.get('status')
        notes = request.form.get('notes')

        appointment_date = ""
        appointment_time = ""
        if 'T' in appointment_datetime_str:
            appointment_date, appointment_time = appointment_datetime_str.split('T')
        elif ' ' in appointment_datetime_str:
            appointment_date, appointment_time = appointment_datetime_str.split(' ')

        try:
            AppointmentService.update(
                id,
                customer_id=customer_id,
                service_id=service_id,
                appointment_date=appointment_date,
                appointment_time=appointment_time,
                status=status,
                notes=notes
            )
            NotificationService.flash_success('Cập nhật lịch hẹn thành công.')
            return redirect(url_for('appointment.index'))
        except BusinessException as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                raise e
            NotificationService.flash_error(e.message)
            appointment = AppointmentService.get_by_id(id)
            if appointment:
                if customer_id:
                    from models.customer import Customer
                    appointment.customer = Customer.query.get(int(customer_id))
                    appointment.customer_id = int(customer_id)
                if service_id:
                    appointment.service_id = int(service_id)
                if appointment_datetime_str:
                    try:
                        appointment.appointment_time = datetime.strptime(appointment_datetime_str, '%Y-%m-%dT%H:%M')
                    except ValueError:
                        try:
                            appointment.appointment_time = datetime.strptime(appointment_datetime_str, '%Y-%m-%d %H:%M')
                        except ValueError:
                            pass
                appointment.status = status
                appointment.notes = notes
                
            customers = CustomerService.get_all()
            services = ServiceService.get_all_services()
            current_datetime = datetime.now().strftime('%Y-%m-%dT%H:%M')
            return render_template('appointment/edit.html', appointment=appointment, customers=customers, services=services, current_datetime=current_datetime)

@appointment_bp.route('/appointments/detail/<int:id>')
def detail(id):
    appointment = AppointmentService.get_by_id(id)
    if not appointment:
        flash('Không tìm thấy lịch hẹn.', 'danger')
        return redirect(url_for('appointment.index'))
    
    return render_template('appointment/detail.html', appointment=appointment)

@appointment_bp.route('/appointments/update_status', methods=['POST'])
def update_status():
    data = request.get_json() or {}
    appointment_id = data.get('id')
    status = data.get('status')
    
    if not appointment_id or not status:
        return jsonify({'error': 'Missing id or status'}), 400
    
    appointment = AppointmentService.update_status(appointment_id, status)
    
    return jsonify({
        'message': 'Status updated successfully', 
        'appointment': {'id': appointment.id, 'status': appointment.status}
    })

@appointment_bp.route('/appointments/delete/<int:id>', methods=['POST'])
def delete(id):
    success, error = AppointmentService.delete(id)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        if success:
            return jsonify({'success': True, 'message': 'Đã xóa lịch hẹn thành công.'})
        else:
            return jsonify({'success': False, 'message': error or 'Không thể xóa lịch hẹn.'})
            
    if success:
        flash('Đã xóa lịch hẹn thành công.', 'success')
    else:
        flash(error or 'Không thể xóa lịch hẹn.', 'danger')
    return redirect(url_for('appointment.index'))

@appointment_bp.route('/appointments/search')
def search():
    query = request.args.get('q', '')
    results = AppointmentService.search(query)
    return jsonify([{
        'id': a.id,
        'customer_id': a.customer_id,
        'service_id': a.service_id,
        'appointment_time': a.appointment_time.isoformat() if a.appointment_time else None,
        'status': a.status,
        'notes': a.notes,
        'customer_name': a.customer.name if a.customer else None,
        'service_name': a.service.name if a.service else None
    } for a in results])

@appointment_bp.route('/appointments/events')
def get_events():
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    period = request.args.get('period', '')
    
    # We query all matching appointments WITHOUT pagination for FullCalendar.
    query = AppointmentService._build_filtered_query(
        search=search,
        status=status,
        from_date=from_date,
        to_date=to_date,
        period=period
    )
    
    # We order by appointment_time asc for calendar rendering
    appointments = query.order_by(Appointment.appointment_time.asc()).all()
    
    events = []
    for a in appointments:
        # Calculate end time based on service duration or default to 30 mins
        duration = a.service.duration if (a.service and a.service.duration) else 30
        from datetime import timedelta
        end_time = a.appointment_time + timedelta(minutes=duration) if a.appointment_time else None
        
        events.append({
            'id': a.id,
            'title': a.customer.name if a.customer else 'N/A',
            'start': a.appointment_time.isoformat() if a.appointment_time else None,
            'end': end_time.isoformat() if end_time else None,
            'status': a.status,
            'customer_name': a.customer.name if a.customer else 'N/A',
            'customer_phone': a.customer.phone if a.customer else '',
            'service_name': a.service.name if a.service else 'N/A',
            'service_price': a.service.price if (a.service and a.service.price is not None) else 0.0,
            'service_duration': duration,
            'notes': a.notes or '',
            'detail_url': url_for('appointment.detail', id=a.id),
            'edit_url': url_for('appointment.edit', id=a.id),
            'delete_url': url_for('appointment.delete', id=a.id)
        })
        
    return jsonify(events)
