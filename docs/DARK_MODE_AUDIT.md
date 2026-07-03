# Báo cáo Kiểm tra Dark Mode (Dark Mode Audit) – SpaManager v3.9

Tài liệu này đánh giá mức độ sẵn sàng, cấu trúc hiện tại và kế hoạch triển khai giao diện tối (Dark Mode) cho dự án SpaManager v3.9 trong tương lai.

---

## 1. Mức độ hoàn thiện hiện tại (Ước lượng chung: 40%)

Dưới đây là thống kê chi tiết mức độ sẵn sàng cho Dark Mode ở từng phân hệ/component:

| Thành phần | Trạng thái | Mức độ hoàn thiện | Ghi chú / Chi tiết |
| :--- | :---: | :---: | :--- |
| **Theme Variables** | ⚠️ Chuẩn bị một phần | 50% | Đã sử dụng CSS variables trong `theme.css` nhưng chưa định nghĩa Dark Palette. |
| **Notification (Toasts)** | ✅ Hỗ trợ Dark Mode | 100% | Đã khai báo đầy đủ CSS overrides cho selector `.dark-theme` / `.dark-mode`. |
| **Sidebar** | ⚠️ Chuẩn bị một phần | 60% | Sử dụng biến màu chủ đạo, chỉ cần chuyển đổi các biến nền. |
| **Topbar** | ⚠️ Chuẩn bị một phần | 60% | Sử dụng biến màu chủ đạo, chỉ cần chuyển đổi các biến nền. |
| **Command Palette** | ❌ Chưa hỗ trợ | 0% | Toàn bộ background, borders và văn bản đang dùng màu tĩnh (#fff, #888, #555). |
| **Dashboard (Widgets)** | ⚠️ Chuẩn bị một phần | 50% | Khung widget dùng biến CSS, tuy nhiên biểu đồ Chart.js chưa hỗ trợ đổi màu. |
| **Statistics & Report** | ⚠️ Chuẩn bị một phần | 40% | Tương tự Dashboard, biểu đồ Chart.js chưa hỗ trợ đổi màu. |
| **Customer & Service** | ⚠️ Chuẩn bị một phần | 50% | Dùng khung Shared Table (cần đổi màu border và nền của thẻ input/select). |
| **Appointment & Calendar** | ⚠️ Chuẩn bị một phần | 40% | FullCalendar và popover/offcanvas cần cập nhật biến màu và z-index. |
| **Invoice** | ⚠️ Chuẩn bị một phần | 50% | Bảng tạo hóa đơn dùng CSS variables, cần đổi màu input text. |
| **Settings** | ⚠️ Chuẩn bị một phần | 50% | Form cài đặt và Drag & Drop backup zone cần hỗ trợ nền tối. |
| **Backup Center** | ⚠️ Chuẩn bị một phần | 50% | Danh sách backup và các badge trạng thái cần đồng bộ màu nền tối. |
| **JS Theme Manager** | ❌ Chưa hỗ trợ | 0% | Chưa có script xử lý đổi theme, lưu trữ trạng thái và tự động nhận diện hệ điều hành. |

---

## 2. Chi tiết các phần kiểm tra (Audit Details)

### a. Theme Audit (`theme.css`)
*   **CSS Variables**: Hệ thống đã có bộ biến CSS Token rất hoàn chỉnh (`--spa-bg`, `--spa-white`, `--spa-card-bg`, `--spa-text-primary`...).
*   **Palette Separation**: Chưa được tách. Để hỗ trợ Dark Mode, chỉ cần khai báo lại các biến này dưới selector `body.dark-theme` hoặc truy vấn media query `@media (prefers-color-scheme: dark)`.

### b. Dark Class Audit
*   **Phát hiện**: Trong `notification.css` đã chuẩn bị sẵn các lớp `body.dark-theme .spa-toast`, `body.dark-mode .spa-toast` để chuyển sang nền tối (`#1e1e1e`) và đổi màu chữ.
*   **Trạng thái**: Đã khai báo cấu trúc CSS nhưng chưa được kích hoạt vì chưa có cơ chế toggle lớp này trên thẻ `<body>`.

### c. CSS Color Variables vs Hardcoded (Thống kê mã nguồn)
*   **Số lần sử dụng CSS variables (var(--...))**: **477 lần** (Cho thấy việc chuyển dịch sang dùng Token đạt tỷ lệ rất cao).
*   **Số mã màu hardcoded HEX (ngoài theme.css)**: **240 lần**.
*   **Số mã màu hardcoded RGB/A (ngoài theme.css)**: **102 lần**.
*   *Ghi chú*: Các mã màu hardcoded chủ yếu nằm ở các thành phần kế thừa Bootstrap cũ và shadow. Nếu triển khai Dark Mode, các màu hardcoded này cần được chuyển đổi hoàn toàn sang biến.

### d. JS Theme Management
*   **Trạng thái**: Không tồn tại bất kỳ biến, hàm hay logic nào liên quan đến theme (như `toggleTheme`, `setTheme` hay lưu trữ `localStorage` của theme).
*   **localStorage**: Hiện tại chỉ dùng để lưu trạng thái hiển thị của bảng dữ liệu trong `shared-table.js`.

### e. Assets & Charts Audit
*   **Logo/Icon**: Hệ thống không dùng logo ảnh mà dùng icon vector (Bootstrap Icons). Do đó, icon sẽ tự động chuyển màu theo biến chữ `--spa-text-primary`.
*   **Biểu đồ (Chart.js)**: Gridlines (`rgba(0, 0, 0, 0.05)`) và màu text nhãn tọa độ đang được khai báo tĩnh trong `dashboard.js` và `statistics.js`. Khi bật Dark Mode, biểu đồ sẽ bị tối mờ, chữ đè khó đọc do nền tối của card. Cần đọc màu động từ CSS variables trong JS khi render chart.

---

## 3. Khối nợ kỹ thuật (Technical Debt) cần xử lý nếu triển khai
1.  **Định nghĩa Dark Palette**: Bổ sung bộ giá trị biến CSS cho nền tối trong `theme.css`.
2.  **Chuẩn hóa shadow**: Đổi các bóng đổ `--spa-shadow-md` sang màu tối hơn với độ mờ đục thấp hơn để trông tự nhiên trên nền tối.
3.  **Refactor mã màu Chart**: Chuyển các khai báo grid line và tick label màu xám tĩnh trong Chart.js sang dạng tham chiếu biến CSS.
4.  **Cập nhật các thành phần Form & Select2**: Đảm bảo các hộp chọn Select2 và các ô input đổi màu viền và nền hợp lý.

---

## 4. Đánh giá Khả năng & Lộ trình Triển khai

*   **Đánh giá mức độ khó**: 🟢 **Dễ (chỉ cần 1 Sprint)**.
*   **Lý do**:
    1.  Hệ thống CSS Variables đã được phủ rộng khắp 11 tệp tin CSS trong Sprint dọn dẹp trước (477 vị trí).
    2.  Hệ thống Icon là SVG vector tự động đổi màu theo CSS.
    3.  Chỉ cần thêm bộ biến màu tối trong `theme.css`, tạo nút bấm Toggle trên Topbar và viết khoảng 15 dòng code JS để lưu trạng thái vào `localStorage`.
*   **Ước lượng**: **1 Sprint duy nhất (Sprint 3.1 - Dark Mode Integration)** là đủ để hoàn thiện 100% tính năng này.
