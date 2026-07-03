# services/statistics_service.py
from services.dashboard_statistics_service import DashboardStatisticsService

class StatisticsService:
    @staticmethod
    def get_statistics_data():
        return {
            "summary": {},
            "revenue": [],
            "appointments": [],
            "services": [],
            "customers": []
        }

    @staticmethod
    def get_summary(from_date=None, to_date=None):
        return DashboardStatisticsService.get_summary(from_date, to_date)

    @staticmethod
    def get_revenue_chart(from_date=None, to_date=None, group_by="day"):
        return DashboardStatisticsService.get_revenue_chart(from_date, to_date, group_by)

    @staticmethod
    def get_customer_statistics(from_date=None, to_date=None, keyword=None):
        return DashboardStatisticsService.get_customer_statistics(from_date, to_date, keyword)

    @staticmethod
    def get_service_statistics(from_date=None, to_date=None, keyword=None):
        return DashboardStatisticsService.get_service_statistics(from_date, to_date, keyword)

    @staticmethod
    def get_customer_statistics_paginated(from_date=None, to_date=None, page=1, per_page=25, sort_by='total_spent', order='desc', keyword=None):
        return DashboardStatisticsService.get_customer_statistics_paginated(from_date, to_date, page, per_page, sort_by, order, keyword)

    @staticmethod
    def get_service_statistics_paginated(from_date=None, to_date=None, page=1, per_page=25, sort_by='revenue', order='desc', keyword=None):
        return DashboardStatisticsService.get_service_statistics_paginated(from_date, to_date, page, per_page, sort_by, order, keyword)

    @staticmethod
    def get_service_invoice_details(service_id, from_date=None, to_date=None):
        return DashboardStatisticsService.get_service_invoice_details(service_id, from_date, to_date)

    @staticmethod
    def get_customer_invoice_statistics(customer_id, from_date=None, to_date=None):
        return DashboardStatisticsService.get_customer_invoice_statistics(customer_id, from_date, to_date)
