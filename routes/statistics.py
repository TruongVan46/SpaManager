from flask import render_template, request, jsonify, send_file, abort
from routes import statistics_bp
from services.statistics_service import StatisticsService
from services.auth_service import AuthService
from core.auth.permissions import can_manage_settings
from datetime import datetime, date
from utils.pagination import get_pagination_params
from utils.timezone_utils import local_now

def parse_date(date_val):
    if not date_val:
        return None
    if isinstance(date_val, (datetime, date)):
        return date_val
    if isinstance(date_val, str):
        date_val = date_val.strip()
        if not date_val or date_val.lower() in ('none', 'null', ''):
            return None
        try:
            return datetime.strptime(date_val, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _apply_pdf_download_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@statistics_bp.before_request
def _require_statistics_permission():
    current_user = AuthService.get_current_active_user()
    if not current_user:
        abort(401)
    if not can_manage_settings(current_user):
        abort(403)

@statistics_bp.route('/reports')
@statistics_bp.route('/statistics')
def index():
    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
    cust_q = request.args.get('cust_q', '').strip()
    svc_q = request.args.get('svc_q', '').strip()
    
    summary = StatisticsService.get_summary(from_date, to_date)
    revenue_chart = StatisticsService.get_revenue_chart(from_date, to_date)
    
    # 1. Customer statistics pagination & sorting
    cust_page, cust_per_page = get_pagination_params('cust_page', 'cust_per_page')
        
    cust_sort_by = request.args.get('cust_sort_by', 'total_spent').strip()
    cust_order = request.args.get('cust_order', 'desc').strip()
    if cust_sort_by not in ('name', 'phone', 'invoice_count', 'total_spent'):
        cust_sort_by = 'total_spent'
    if cust_order not in ('asc', 'desc'):
        cust_order = 'desc'
        
    customer_statistics = StatisticsService.get_customer_statistics_paginated(
        from_date=from_date,
        to_date=to_date,
        page=cust_page,
        per_page=cust_per_page,
        sort_by=cust_sort_by,
        order=cust_order,
        keyword=cust_q or None
    )

    # 2. Service statistics pagination & sorting
    svc_page, svc_per_page = get_pagination_params('svc_page', 'svc_per_page')
        
    svc_sort_by = request.args.get('svc_sort_by', 'revenue').strip()
    svc_order = request.args.get('svc_order', 'desc').strip()
    if svc_sort_by not in ('service_name', 'quantity_sold', 'revenue'):
        svc_sort_by = 'revenue'
    if svc_order not in ('asc', 'desc'):
        svc_order = 'desc'
        
    service_statistics = StatisticsService.get_service_statistics_paginated(
        from_date=from_date,
        to_date=to_date,
        page=svc_page,
        per_page=svc_per_page,
        sort_by=svc_sort_by,
        order=svc_order,
        keyword=svc_q or None
    )
    
    return render_template(
        "statistics/index.html",
        summary=summary,
        revenue_chart=revenue_chart,
        customer_statistics=customer_statistics,
        service_statistics=service_statistics,
        from_date=from_date,
        to_date=to_date,
        cust_q=cust_q,
        svc_q=svc_q
    )

@statistics_bp.route('/statistics/api/revenue_chart')
def api_revenue_chart():
    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
    group_by = request.args.get('group_by', 'day')
    
    chart_data = StatisticsService.get_revenue_chart(from_date, to_date, group_by)
    return jsonify(chart_data)

@statistics_bp.route('/statistics/customer/<int:customer_id>')
def customer_detail(customer_id):
    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
    
    stats = StatisticsService.get_customer_invoice_statistics(customer_id, from_date, to_date)
    
    return render_template(
        "statistics/customer_detail.html",
        customer=stats.get('customer'),
        invoices=stats.get('invoices'),
        summary=stats.get('summary'),
        from_date=from_date,
        to_date=to_date
    )

@statistics_bp.route('/statistics/service/<int:service_id>')
def service_detail(service_id):
    from models.service import Service
    
    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
        
    service = Service.query.get_or_404(service_id)
    
    service_invoices = StatisticsService.get_service_invoice_details(service_id, from_date, to_date)
    
    return render_template(
        "statistics/service_detail.html",
        service=service,
        service_invoices=service_invoices,
        from_date=from_date,
        to_date=to_date
    )

@statistics_bp.route('/statistics/export/excel')
def export_excel():
    from utils.export_excel import generate_statistics_excel
    
    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
    cust_q = request.args.get('cust_q', '').strip()
    svc_q = request.args.get('svc_q', '').strip()

    summary = StatisticsService.get_summary(from_date, to_date)
    customer_statistics = StatisticsService.get_customer_statistics(from_date, to_date, cust_q or None)
    service_statistics = StatisticsService.get_service_statistics(from_date, to_date, svc_q or None)
    
    excel_stream = generate_statistics_excel(summary, customer_statistics, service_statistics)
    
    filename = f"ThongKe_{local_now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return send_file(
        excel_stream,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename
    )

@statistics_bp.route('/statistics/export/pdf')
def export_pdf():
    from utils.export_pdf import generate_statistics_pdf
    
    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
    cust_q = request.args.get('cust_q', '').strip()
    svc_q = request.args.get('svc_q', '').strip()

    summary = StatisticsService.get_summary(from_date, to_date)
    customer_statistics = StatisticsService.get_customer_statistics(from_date, to_date, cust_q or None)
    service_statistics = StatisticsService.get_service_statistics(from_date, to_date, svc_q or None)
    
    pdf_stream = generate_statistics_pdf(summary, customer_statistics, service_statistics, from_date, to_date)
    
    filename = f"ThongKe_{local_now().strftime('%Y%m%d_%H%M%S_%f')}.pdf"
    
    response = send_file(
        pdf_stream,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
    )
    return _apply_pdf_download_headers(response)
