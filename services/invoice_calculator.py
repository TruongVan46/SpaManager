class InvoiceCalculator:
    """
    Lớp tiện ích để tính toán các giá trị cho Hóa đơn (Invoice) và Chi tiết hóa đơn (InvoiceDetail).
    """

    @staticmethod
    def calculate_line_total(detail):
        """
        Tính thành tiền cho một dòng chi tiết hóa đơn.
        Thành tiền = Đơn giá * Số lượng
        """
        if not detail:
            return 0.0
        return detail.price * detail.quantity

    @staticmethod
    def calculate_total_amount(invoice):
        """
        Tính tổng tiền cho toàn bộ hóa đơn.
        Tổng tiền = Tổng của tất cả các thành tiền của chi tiết hóa đơn.
        """
        if not invoice or not invoice.details:
            return 0.0
        return sum(InvoiceCalculator.calculate_line_total(detail) for detail in invoice.details)

    @staticmethod
    def calculate_total_quantity(invoice):
        """
        Tính tổng số lượng dịch vụ trong hóa đơn.
        Số lượng = Tổng số lượng của tất cả các chi tiết hóa đơn.
        """
        if not invoice or not invoice.details:
            return 0
        return sum(detail.quantity for detail in invoice.details)