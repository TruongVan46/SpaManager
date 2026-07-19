import unittest
from pathlib import Path

class TestAppointmentKpiCopy(unittest.TestCase):
    def setUp(self):
        self.template_path = Path(__file__).parent.parent / "templates" / "appointment" / "index.html"
        self.content = self.template_path.read_text(encoding="utf-8")

    def test_no_stash_artifact_or_conflict_markers(self):
        self.assertNotIn("Stashed changes", self.content)
        self.assertNotIn("stashed changes", self.content.lower())
        self.assertNotIn("stash changes", self.content.lower())
        self.assertNotIn("<<<<<<<", self.content)
        self.assertNotIn(">>>>>>>", self.content)
        # Ensure no exact 7-equals line marker
        lines = self.content.splitlines()
        for line in lines:
            self.assertNotEqual(line.strip(), "=======")

    def test_kpi_headings_and_values_remain(self):
        # 1. Total KPI
        self.assertIn("Tổng lịch hẹn", self.content)
        self.assertIn("{{ summary.total }}", self.content)
        
        # 2. Pending KPI
        self.assertIn("Chờ xử lý", self.content)
        self.assertIn("{{ summary.pending }}", self.content)
        
        # 3. Confirmed KPI
        self.assertIn("Đã xác nhận", self.content)
        self.assertIn("{{ summary.confirmed }}", self.content)
        
        # 4. Completed KPI
        self.assertIn("Hoàn thành", self.content)
        self.assertIn("{{ summary.completed }}", self.content)
        
        # 5. Cancelled KPI
        self.assertIn("Đã hủy", self.content)
        self.assertIn("{{ summary.cancelled }}", self.content)

    def test_kpi_helper_texts_are_present(self):
        self.assertIn("Tất cả lịch hẹn", self.content)
        self.assertIn("Đang chờ xử lý", self.content)
        self.assertIn("Lịch đã xác nhận", self.content)
        self.assertIn("Lịch đã hoàn thành", self.content)
        self.assertIn("Lịch đã hủy", self.content)
