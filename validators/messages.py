# validators/messages.py

class ValidationMessages:
    REQUIRED = "Trường này không được để trống."
    INVALID_PHONE = "Số điện thoại phải gồm đúng 10 chữ số và bắt đầu bằng số 0."
    INVALID_EMAIL = "Email không đúng định dạng."
    INVALID_NUMBER = "Giá trị phải là số."
    INVALID_DATE = "Ngày không hợp lệ."
    INVALID_TIME = "Giờ không hợp lệ."
    PAST_DATE = "Không được đặt lịch trong quá khứ."
    MIN_VALUE = "Giá trị không được nhỏ hơn {min}."
    MAX_VALUE = "Giá trị không được lớn hơn {max}."
    LENGTH = "Độ dài phải từ {min} đến {max} ký tự."
    PASSWORD_LENGTH = "Mật khẩu mới phải có ít nhất 8 ký tự."
    PASSWORD_MATCH = "Xác nhận mật khẩu mới không khớp."
    PASSWORD_SAME = "Mật khẩu mới không được giống mật khẩu cũ."
    CUSTOMER_REQUIRED = "Thông tin khách hàng là bắt buộc."
    SERVICE_REQUIRED = "Thông tin dịch vụ là bắt buộc."
