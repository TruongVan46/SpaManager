# Hướng dẫn Kiểm thử thủ công (Smoke Checklist) - Workspace Staff Soft Delete

Tài liệu này hướng dẫn cách kiểm thử thủ công và kiểm tra độ ổn định (smoke test) tính năng xóa mềm nhân viên khỏi workspace và bảng danh sách người dùng đã xóa mềm, áp dụng cho môi trường phát triển cục bộ (Local) và môi trường thực tế (Production).

---

## 1. Mục tiêu kiểm thử (Smoke Goals)
* Xác nhận chức năng xóa mềm và khôi phục hoạt động chính xác theo phân quyền (chỉ OWNER trong workspace hiện tại được thực hiện).
* Đảm bảo không xảy ra hiện tượng xóa cứng (hard-delete) dữ liệu người dùng khỏi database.
* Đảm bảo tính năng khôi phục thành viên không tự ý kích hoạt lại tài khoản đã bị vô hiệu hóa/tạm khóa hệ thống trái thẩm quyền.
* Giao diện người dùng hiển thị đúng trạng thái của tài khoản hoạt động và tài khoản đã xóa mềm.

---

## 2. Điều kiện tiền đề (Preconditions)
1. Đã đăng nhập bằng tài khoản vai trò `OWNER` của một workspace hợp lệ.
2. Có ít nhất một tài khoản nhân viên vai trò `STAFF` hoặc `ADMIN` thuộc cùng workspace đó.
3. Phiên bản cơ sở dữ liệu đã được cập nhật thành công lên migration `0005_member_soft_delete`.

---

## 3. Quy trình Kiểm thử cục bộ (Local Smoke Checklist)

| STT | Luồng kiểm thử thủ công | Kết quả mong đợi (Expected Results) | Kết quả thực tế | Trạng thái |
| :--- | :--- | :--- | :--- | :--- |
| 1 | **Đăng nhập với tư cách OWNER** | Đăng nhập thành công và truy cập được vào workspace hiện tại. | Đúng | Đạt |
| 2 | **Truy cập trang Quản lý người dùng** | Thấy danh sách người dùng đang hoạt động và bảng "Người dùng đã xóa mềm" ở phía dưới. | Đúng | Đạt |
| 3 | **Kiểm tra hiển thị nút hành động** | Không thấy nút thùng rác ("Xóa mềm") bên cạnh tài khoản OWNER hoặc tài khoản chính mình đang đăng nhập. Có nút thùng rác bên cạnh tài khoản STAFF/ADMIN khác. | Đúng | Đạt |
| 4 | **Thực hiện Xóa mềm STAFF** | Click nút thùng rác đỏ của một STAFF và chọn OK trên hộp thoại xác nhận. | Đúng | Đạt |
| 5 | **Kiểm tra danh sách Active** | Nhân viên vừa bị xóa biến mất khỏi bảng danh sách người dùng đang hoạt động. | Đúng | Đạt |
| 6 | **Kiểm tra danh sách Xóa mềm** | Nhân viên vừa bị xóa xuất hiện ở bảng "Người dùng đã xóa mềm", hiển thị đúng thông tin: thời gian xóa, người xóa và lý do xóa. | Đúng | Đạt |
| 7 | **Kiểm tra quyền truy cập của STAFF** | Thử dùng tài khoản STAFF bị xóa mềm để truy cập. Tài khoản không thể truy cập vào dữ liệu của workspace cũ. | Đúng | Đạt |
| 8 | **Thực hiện Khôi phục STAFF** | OWNER click vào nút "Khôi phục" (màu xanh lá) bên cạnh STAFF trong bảng đã xóa mềm. | Đúng | Đạt |
| 9 | **Kiểm tra phục hồi trạng thái** | Nhân viên biến mất khỏi bảng xóa mềm và quay lại bảng đang hoạt động bình thường. | Đúng | Đạt |
| 10 | **Kiểm tra an toàn Khóa tài khoản** | Nếu tài khoản STAFF bị khóa hệ thống trước đó (`is_active = False` hoặc bị từ chối phê duyệt), việc khôi phục thành viên chỉ khôi phục liên kết workspace nhưng vẫn giữ nguyên trạng thái khóa của tài khoản (`is_active = False`). | Đúng | Đạt |
| 11 | **Kiểm tra nút Xóa vĩnh viễn** | Nút "Xóa vĩnh viễn" hiển thị màu xám, bị vô hiệu hóa (`disabled`) và có thông báo tooltip rõ ràng. | Đúng | Đạt |

---

## 4. Hướng dẫn Kiểm thử an toàn trên Production (Production Smoke Checklist)

> **LƯU Ý QUAN TRỌNG:**
> Khi thực hiện kiểm thử trên môi trường Production, tuyệt đối tuân thủ quy tắc không chỉnh sửa trực tiếp dữ liệu thật của khách hàng. Hãy sử dụng tài khoản/dữ liệu test được tạo riêng cho mục đích này.

### Các bước thực hiện:
1. Đăng nhập vào Production Portal bằng tài khoản OWNER thử nghiệm.
2. Tạo mới một tài khoản STAFF test (ví dụ: `test_staff_delete`).
3. Truy cập danh sách người dùng, bấm nút **Xóa mềm** cho tài khoản `test_staff_delete` vừa tạo.
4. Xác nhận tài khoản chuyển sang bảng **Người dùng đã xóa mềm**.
5. Bấm nút **Khôi phục** để đưa tài khoản trở lại bảng active.
6. Sau khi hoàn thành smoke test, vô hiệu hóa tài khoản test này thông qua nút toggle active thông thường (hoặc giữ nguyên trạng thái vô hiệu hóa).

---

## 5. Hướng dẫn khi có sự cố & Phục hồi (Rollback Note)

* **Không tự ý thực hiện rollback migration trên Production** trừ khi có chỉ đạo trực tiếp từ Tech Lead/Reviewer.
* Nếu phát hiện lỗi nghiêm trọng liên quan đến tính năng xóa mềm trên Production:
  1. Ưu tiên tắt/ẩn nút thao tác xóa mềm trên giao diện (UI) bằng một bản vá hotfix nhẹ thay vì can thiệp cơ sở dữ liệu.
  2. Báo cáo ngay cho đội ngũ kỹ thuật kèm log hoạt động để phân tích nguyên nhân.
