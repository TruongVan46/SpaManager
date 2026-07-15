"""User-facing Vietnamese labels for internal roles and statuses."""

ROLE_LABELS = {
    "APPROVAL_OWNER": "Quản trị duyệt tài khoản",
    "OWNER": "Chủ cơ sở",
    "ADMIN": "Quản trị viên",
    "STAFF": "Nhân viên",
}

STATUS_LABELS = {
    "PENDING": "Chờ xử lý",
    "PENDING_RETENTION": "Đang chờ hết thời hạn lưu giữ",
    "PENDING_APPROVAL": "Chờ phê duyệt",
    "ACTIVE": "Đang hoạt động",
    "APPROVED": "Đã phê duyệt",
    "REJECTED": "Đã từ chối",
    "CANCELLED": "Đã hủy",
    "COMPLETED": "Hoàn tất",
    "FAILED": "Thất bại",
    "DISABLED": "Đã vô hiệu hóa",
    "INACTIVE": "Không hoạt động",
    "DELETED": "Đã xóa",
    "EXPIRED": "Đã hết hạn",
    "CLAIMED": "Đã tiếp nhận",
    "EXECUTING": "Đang thực hiện",
    "RETRY_PENDING": "Chờ đối soát",
    "RELEASED": "Đã gỡ bỏ",
    "CLEAR": "Không có lệnh giữ",
    "BLOCKED": "Bị chặn",
    "CONFIRMED": "Đã xác nhận",
    "NO_SHOW": "Không đến",
    "Valid": "Hợp lệ",
    "Invalid": "Không hợp lệ",
    "File Missing": "Thiếu tệp",
    "Unknown": "Không xác định",
    "OK": "Bình thường",
}


def display_role(value):
    """Return a translated role label without changing the stored value."""
    if value is None:
        return "Không xác định"
    return ROLE_LABELS.get(str(value).strip().upper(), str(value))


def display_status(value):
    """Return a translated status label without changing the stored value."""
    if value is None:
        return "Không xác định"
    raw = str(value).strip()
    return STATUS_LABELS.get(raw, STATUS_LABELS.get(raw.upper(), raw))
