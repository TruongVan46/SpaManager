# validators/appointment_validator.py
from datetime import datetime, date as datetime_date
from validators.base_validator import BaseValidator
from validators.messages import ValidationMessages
from validators.rules import validate_required, validate_date, validate_regex
from models.customer import Customer
from models.service import Service


class AppointmentValidator(BaseValidator):
    def validate(self, data):
        self.result.field_errors.clear()
        self.result.success = True
        
        customer_id = data.get('customer_id')
        service_id = data.get('service_id')
        date_str = data.get('date', '')
        time_str = data.get('time', '')
        
        # 1. Customer is required and must exist
        if not validate_required(customer_id):
            self.add_error('customer_id', ValidationMessages.CUSTOMER_REQUIRED)
        else:
            cust = Customer.query.filter(Customer.id == customer_id, Customer.deleted_at.is_(None)).first()
            if not cust:
                self.add_error('customer_id', "Khách hàng không tồn tại hoặc đã bị xóa.")
                
        # 2. Service is required and must exist
        if not validate_required(service_id):
            self.add_error('service_id', ValidationMessages.SERVICE_REQUIRED)
        else:
            srv = Service.query.filter(Service.id == service_id, Service.deleted_at.is_(None)).first()
            if not srv:
                self.add_error('service_id', "Dịch vụ không tồn tại hoặc đã bị xóa.")
                
        # 3. Date validation
        if not validate_required(date_str):
            self.add_error('date', ValidationMessages.REQUIRED)
        elif not validate_date(date_str, "%Y-%m-%d"):
            self.add_error('date', ValidationMessages.INVALID_DATE)
        else:
            # Check if in past
            try:
                appt_date = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
                if appt_date < datetime_date.today():
                    self.add_error('date', ValidationMessages.PAST_DATE)
            except Exception:
                pass
                
        # 4. Time validation
        if not validate_required(time_str):
            self.add_error('time', ValidationMessages.REQUIRED)
        elif not validate_regex(time_str, r'^([01]\d|2[0-3]):[0-5]\d$'):
            self.add_error('time', ValidationMessages.INVALID_TIME)
            
        return self.result
