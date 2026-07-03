# services/dashboard_service.py
from services.dashboard_statistics_service import DashboardStatisticsService

class DashboardService:
    @staticmethod
    def get_dashboard_data():
        """Get dashboard data by delegating to the unified DashboardStatisticsService."""
        return DashboardStatisticsService.get_dashboard_data()

    @staticmethod
    def get_revenue_chart_data():
        """Get revenue chart data by delegating to the unified DashboardStatisticsService."""
        return DashboardStatisticsService.get_revenue_chart_data()