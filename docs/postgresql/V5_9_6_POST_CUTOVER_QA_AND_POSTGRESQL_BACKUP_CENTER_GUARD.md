# v5.9.6 Post-cutover QA and PostgreSQL Backup Center Guard

## Mục tiêu

- Xác nhận sau cutover PostgreSQL, Backup Center không còn cố dùng flow sao lưu/khôi phục SQLite.
- Giữ nguyên behavior SQLite khi hệ thống chạy SQLite.
- Khi chạy PostgreSQL, chặn rõ ràng các thao tác không an toàn trong Backup Center và trả thông báo dễ hiểu cho admin.

## Hành vi hiện tại sau hotfix

- SQLite mode:
  - Tạo backup SQLite vẫn hoạt động như cũ.
  - Danh sách backup cũ vẫn hiển thị.
  - Restore SQLite vẫn dùng flow hiện có.
- PostgreSQL mode:
  - Nút tạo backup và nhập backup bị khóa.
  - Restore từ backup SQLite bị chặn.
  - Restore Wizard trả trạng thái bị khóa thay vì đi tiếp flow SQLite.
  - Backup cũ vẫn có thể hiển thị trong danh sách để tham khảo, nhưng không được dùng như DB restore cho PostgreSQL.

## Thông báo cho admin

- Backup Center sẽ hiển thị cảnh báo rõ ràng rằng hệ thống đang chạy PostgreSQL.
- Người vận hành cần theo runbook PostgreSQL thay vì Backup Center SQLite.

## Kiểm tra cần có

- Backup Center trên PostgreSQL không tạo file `.db` mới.
- Restore từ backup SQLite không thay đổi dữ liệu PostgreSQL.
- Upload backup SQLite cho DB restore bị chặn.
- UI không ném lỗi kỹ thuật khó hiểu.
- Backup list cũ vẫn có thể xem nếu còn metadata hợp lệ.

## Ghi chú vận hành

- Đây là guard cho giai đoạn sau cutover.
- Không đổi production `DATABASE_URL`.
- Không đổi schema, migration hoặc APP_VERSION.
