# validators/invoice_validator.py
from validators.base_validator import BaseValidator
from validators.messages import ValidationMessages
from validators.rules import validate_required, validate_number
from models.customer import Customer


class InvoiceValidator(BaseValidator):
    def validate(self, data):
        self.result.field_errors.clear()
        self.result.success = True
        
        customer_id = data.get('customer_id')
        services = data.get('services', [])
        total_amount = data.get('total_amount', 0)
        
        # 1. Customer is required and must exist
        if not validate_required(customer_id):
            self.add_error('customer_id', ValidationMessages.CUSTOMER_REQUIRED)
        else:
            cust = Customer.query.filter(Customer.id == customer_id, Customer.deleted_at.is_(None)).first()
            if not cust:
                self.add_error('customer_id', "Khách hàng không tồn tại hoặc đã bị xóa.")
                
        # 2. At least one service is required
        if not services or len(services) == 0:
            self.add_error('services', "Hóa đơn phải chứa ít nhất một dịch vụ.")
            
        # 3. Total amount >= 0
        if total_amount is not None and not validate_number(total_amount, min_val=0):
            self.add_error('total_amount', "Tổng tiền không được âm.")
            
        return self.result
