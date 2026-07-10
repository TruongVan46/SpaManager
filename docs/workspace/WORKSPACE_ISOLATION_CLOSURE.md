# SpaManager Version 6.5 — Workspace Tenant Isolation Closure

---

## 1. Quyết định Đóng (Final Decision)
* **Trạng thái Version 6.5:** **ĐÃ HOÀN THÀNH / ĐÓNG** (CLOSED / DONE).
* Cơ chế cô lập tenant (Workspace Tenant Isolation) đã được xác minh toàn diện cả ở môi trường kiểm thử cô lập lẫn môi trường production thực tế.
* Việc xóa vĩnh viễn (permanent purge) dữ liệu nghiệp vụ và tài khoản hoàn toàn bị vô hiệu hóa (disabled) và chặn (blocked) theo chính sách bảo toàn an toàn dữ liệu và lịch sử tài chính.

---

## 2. Các Hạng mục đã Hoàn thành (Scope Completed)
* **Workspace Schema:** Schema cơ sở dữ liệu nền tảng gồm các bảng `workspaces` và `workspace_members`.
* **Workspace Provisioning:** Tự động tạo workspace và gán membership khi duyệt chủ tài khoản Google (`Google OWNER`).
* **Seeded OWNER Onboarding:** Tự động khởi tạo workspace cho chủ tài khoản mặc định (`owner`) khi đăng nhập lần đầu.
* **Current Workspace Session Context:** Trích xuất và xác thực workspace hoạt động hiện hành của phiên đăng nhập thông qua session và đối soát membership.
* **Cô lập Dữ liệu Nghiệp vụ:** Lọc dữ liệu Khách hàng (Customer), Dịch vụ (Service), Lịch hẹn (Appointment), Hóa đơn (Invoice/InvoiceDetail) theo `workspace_id` ở tầng truy vấn cơ sở dữ liệu (`scoped_query`).
* **Quy trình Liên kết và Bảo vệ Khóa ngoại:** Chặn liên kết chéo (cross-linkage) lịch hẹn và hóa đơn với khách hàng hoặc dịch vụ thuộc workspace khác.
* **Cô lập Giao diện & Thống kê:** Phân tách dữ liệu trên Dashboard, Báo cáo Thống kê (Statistics), Nhật ký Hoạt động (Activity Log), và Thùng rác (Recycle Bin).
* **Quản trị Nhân viên:** Chủ sở hữu (`OWNER`/`ADMIN`) chỉ có quyền quản trị, thêm mới, sửa đổi hoặc xóa mềm nhân viên thuộc workspace của mình.
* **Cổng Phê duyệt (Approval Portal):** Cô lập luồng phê duyệt và quản lý tài khoản của `APPROVAL_OWNER` ở cấp độ hệ thống.
* **Vòng đời Xóa mềm (Soft-delete Lifecycle):** Cung cấp các tuyến khôi phục (restore) an toàn và ẩn dữ liệu đã xóa mềm khỏi các danh sách hoạt động.
* **Phòng vệ Database Kiểm thử (Test DB Guard):** Cơ chế bảo vệ ngăn chặn việc vô tình ghi đè hoặc chạy kiểm thử trên cơ sở dữ liệu PostgreSQL production.
* **Railway Production Smoke Test:** Thực hiện smoke test khép kín trên môi trường Railway thực tế với 2 workspace độc lập thành công.

---

## 3. Trạng thái Migration và Cơ sở Dữ liệu (Database & Migration State)
* **Database chạy Production:** **PostgreSQL** là cơ sở dữ liệu nghiệp vụ duy nhất.
* **SQLite:** Chỉ sử dụng làm môi trường chạy kiểm thử tự động in-memory (`sqlite:///:memory:`).
* **Bản cập nhật Alembic hiện tại (Migration Head):** `0006_user_ws_soft_delete`.
* **Trạng thái cột log:** Cột `activity_logs.workspace_id` đã được bổ sung vật lý từ migration `0003_workspace_foundation.py` và đang được sử dụng trực tiếp để lọc log. Không cần tạo thêm migration mới.

---

## 4. Hành vi Workspace hiện hành (Current Workspace Session)
* **Hiển thị trên Sidebar:** Tên của workspace đang hoạt động được hiển thị dưới dạng văn bản tĩnh thuần túy (`current_workspace.name`), không phải là một dropdown hay form chọn để chuyển đổi.
* **Không có UI Switcher:** Người dùng không thể tự chọn hoặc chuyển đổi workspace động thông qua giao diện hoặc route công khai nào trong phiên làm việc.
* **Tự động chọn Session:** Session đăng nhập tự động lấy membership active đầu tiên của user để gán làm context hoạt động.
* **Phòng vệ an toàn (Fail-Closed):** Mọi hành động truyền giá trị `current_workspace_id` giả mạo hoặc không hợp lệ vào session đều bị phát hiện, xóa bỏ session và chặn truy cập.

---

## 5. Phân tách Nhật ký Hoạt động (Activity Log Isolation)
* Mọi hành động nghiệp vụ ghi nhận log mới đều tự động gán `workspace_id` tin cậy dựa trên context hiện hành.
* Trang xem Nhật ký hoạt động chỉ hiển thị các dòng log khớp chính xác: `ActivityLog.workspace_id == current_workspace_id`.
* Các log hệ thống, log bootstrap và log của Approval Portal (có `workspace_id IS NULL`) được ẩn hoàn toàn khỏi view nghiệp vụ của Spa OWNER.
* Không sử dụng cơ chế so khớp gián tiếp dựa trên danh sách user ID thành viên (`user_id IN workspace_user_ids`) để làm ranh giới bảo mật.
* Không cung cấp giao diện quản trị log hệ thống toàn cục trên UI của tenant.

---

## 6. Minh chứng Thực tế trên Production (Production Evidence)
Kết quả smoke test khép kín trên PostgreSQL production thu được:
* **Quy mô hệ thống:** `2` workspaces nghiệp vụ độc lập, `2` active owner memberships, và `1` tài khoản `APPROVAL_OWNER`.
* **Quy trình Onboarding:** Seeded OWNER và Google OWNER đăng nhập và kích hoạt workspace thành công.
* **Kiểm tra Cô lập nghiệp vụ:**
  * Dữ liệu tạo bởi Workspace A hoàn toàn ẩn khỏi các trang danh sách, dashboard, báo cáo và nhật ký của Workspace B (và ngoại lại).
  * Kiểm tra 6 đường dẫn GET chéo IDOR (Khách hàng detail/edit, Dịch vụ edit) từ hai phía đều trả về **`404 Not Found`** và không rò rỉ bất kỳ trường dữ liệu nhạy cảm nào.
* **Mã kiểm thử ổn định (Baseline Commit):** `3d7994e4aa2caeda6bb349239f56d49c181077b4`.
* **Health endpoint:** Trả về mã trạng thái `200 OK`.

---

## 7. Các Bản ghi Thử nghiệm được Giữ lại (Retained Production Smoke Artifacts)
* Số lượng Khách hàng và Dịch vụ đang hoạt động (Active) hiển thị trên UI = `0`.
* Để phục vụ đối soát bảo mật và chứng minh phân tách dữ liệu, hệ thống giữ lại vĩnh viễn trên database:
  * **2 bản ghi Customer vật lý** ở trạng thái xóa mềm (mỗi workspace 1 bản ghi).
  * **2 bản ghi Service vật lý** ở trạng thái xóa mềm (mỗi workspace 1 bản ghi).
  * **2 đối tượng nằm trong Thùng rác** của mỗi workspace.
  * **8 dòng Activity Log** nghiệp vụ phân tách theo workspace.
* Việc lưu giữ này đã được người dùng phê duyệt rõ ràng. Tuyệt đối không khôi phục hoặc xóa cứng các bản ghi này.

---

## 8. Chính sách Xóa vĩnh viễn và Dọn dẹp (Permanent Delete & Purge Policy)
* **Xóa vĩnh viễn dữ liệu nghiệp vụ:** Đã bị vô hiệu hóa hoàn toàn. Nút "Xóa vĩnh viễn" trong Recycle Bin bị đổi trạng thái thành `disabled` trên giao diện và các endpoint API liên quan sẽ ném ra lỗi `ValidationException`.
* **Dọn dẹp tự động:** Hàm dọn dẹp theo thời gian `RecycleBinService.cleanup_old_records()` bị vô hiệu hóa và trả về lỗi `ValidationException` để tránh rủi ro mất dữ liệu tài chính.
* **Xóa cứng tài khoản/workspace:** Không được triển khai. Mọi thao tác dọn dẹp vật lý chỉ được thực hiện khi đáp ứng đầy đủ các quy trình đối soát thủ công và có sự phê duyệt trực tiếp.

---

## 9. Các Giới hạn được Chấp nhận (Accepted Limitations)
* **Không hỗ trợ chuyển đổi workspace trên UI:** User có nhiều workspace chỉ làm việc trên workspace active đầu tiên.
* **Ràng buộc membership của database:** Schema DB cho phép user tham gia nhiều workspace khác nhau dù luồng nghiệp vụ hiện hành định hướng đơn workspace.
* **Giữ lại log cũ:** Các log hệ thống cũ có `workspace_id` là NULL được lưu trữ vĩnh viễn trong database để đối soát bảo mật nhưng ẩn khỏi giao diện nghiệp vụ.
* **Chặn xóa mềm do liên kết:** Customer hoặc Service có lịch hẹn/hóa đơn liên kết (kể cả khi lịch hẹn/hóa đơn đó đã bị xóa mềm) sẽ không thể bị xóa mềm để bảo vệ tính toàn vẹn dữ liệu.

---

## 10. Các Hạng mục Trì hoãn (Deferred Work)
* Thiết lập giao diện chuyển đổi workspace linh hoạt (Multi-workspace switcher UI).
* Giao diện quản trị log hệ thống tập trung cho platform admins.
* Triển khai công cụ dọn dẹp vật lý (purge engine) chạy nền an toàn.
* **Phiên bản 6.4 Backup Center:** Các tác vụ `6.4.4-6.4.6` liên quan đến quản lý sao lưu PostgreSQL trên UI tiếp tục được trì hoãn và sẽ được thực hiện trong sprint tiếp theo.

---

## 11. Ma trận Phòng vệ Bảo mật (Security Invariant Matrix)
Tất cả các cơ chế bảo mật đều được bảo vệ bằng các lớp unit test tự động tương ứng:

| Cơ chế bảo vệ | Tệp kiểm thử tự động (Module / Class / Method) |
|---|---|
| **Chặn truy cập khi thiếu Workspace** | `tests/test_workspace_isolation.py` $\rightarrow$ `WorkspaceIsolationTestCase.test_no_current_workspace_fail_closed` |
| **Cô lập dữ liệu Khách hàng** | `tests/test_workspace_isolation.py` $\rightarrow$ `WorkspaceIsolationTestCase.test_customer_isolation` |
| **Cô lập dữ liệu Dịch vụ** | `tests/test_workspace_isolation.py` $\rightarrow$ `WorkspaceIsolationTestCase.test_service_isolation` |
| **Chặn liên kết lịch hẹn chéo** | `tests/test_workspace_isolation.py` $\rightarrow$ `WorkspaceIsolationTestCase.test_appointment_isolation_and_cross_linkage` |
| **Cô lập Hóa đơn & Chi tiết** | `tests/test_workspace_isolation.py` $\rightarrow$ `WorkspaceIsolationTestCase.test_invoice_isolation_and_cross_linkage` |
| **Cô lập Dashboard** | `tests/test_workspace_readiness_smoke.py` $\rightarrow$ `TestWorkspaceReadinessSmoke.test_workspace_a_cannot_see_workspace_b_business_data` |
| **Cô lập Báo cáo Thống kê** | `tests/test_workspace_settings_exports.py` $\rightarrow$ `TestWorkspaceSettingsExports.test_statistics_page_is_workspace_scoped` |
| **Cô lập Thùng rác** | `tests/test_workspace_production_smoke_blockers.py` $\rightarrow$ `TestWorkspaceProductionSmokeBlockers.test_trash_scoped_to_workspace` |
| **Gán trực tiếp log theo workspace** | `tests/test_activity_log_workspace_attribution.py` $\rightarrow$ `ActivityLogWorkspaceAttributionTestCase.test_activity_log_scope_uses_workspace_id_not_membership_inference` |
| **Chặn IDOR trên các URL đọc (GET)** | `tests/test_activity_log_workspace_attribution.py` $\rightarrow$ `ActivityLogWorkspaceAttributionTestCase.test_read_only_foreign_workspace_routes_fail_closed` |
| **Xác thực phiên Workspace giả** | `tests/test_workspace_deleted_guard.py` $\rightarrow$ `TestWorkspaceDeletedGuard.test_scoped_query_fail_closed_with_deleted_workspace` |
| **Cô lập Cổng phê duyệt** | `tests/test_workspace_context_regression.py` $\rightarrow$ `TestWorkspaceContextRegression.test_approval_portal_grouping_does_not_change_memberships` |
| **Chặn trùng lặp email Google** | `tests/test_basic.py` $\rightarrow$ `BasicTestCase.test_google_callback_existing_local_email_is_not_auto_linked` |
| **Phân tách hiển thị xóa mềm** | `tests/test_workspace_staff_soft_delete.py` $\rightarrow$ `TestWorkspaceStaffSoftDelete.test_soft_delete_and_restore_workflow` |
| **Chặn xóa vĩnh viễn nghiệp vụ** | `tests/test_business_permanent_delete_disabled.py` $\rightarrow$ `BusinessPermanentDeleteDisabledTestCase.test_legacy_route_is_unavailable_for_every_entity_and_role` |
| **Chặn dọn dẹp tự động** | `tests/test_business_permanent_delete_disabled.py` $\rightarrow$ `BusinessPermanentDeleteDisabledTestCase.test_registry_and_cleanup_fail_closed_without_mutation` |
| **Bảo vệ DB test PostgreSQL** | `tests/test_test_database_isolation_guard.py` $\rightarrow$ `TestDatabaseIsolationGuardTestCase.test_postgresql_test_database_requires_opt_in_and_test_name` |
| **Ẩn Activity Log NULL** | `tests/test_activity_log_workspace_attribution.py` $\rightarrow$ `ActivityLogWorkspaceAttributionTestCase.test_activity_log_http_route_excludes_foreign_and_null_logs` |


---

## 12. Kết quả Chạy Thử nghiệm (Validation Baseline)
* Bộ kiểm thử chạy tự động trên môi trường cô lập SQLite:
  * **Tổng số test cases:** **`374`**
  * **Kết quả:** **`374/374 PASSED`** (Thành công 100%).
  * **Kiểm tra biên dịch nguồn:** **`compileall PASS`**.

---

## 13. Cảnh báo Vận hành (Operational Cautions)
* Tuyệt đối không chạy lệnh xóa cứng (hard-delete) hay TRUNCATE/reset dữ liệu thủ công bằng SQL trên cơ sở dữ liệu production.
* Không chạy bộ kiểm thử unittest/pytest trực tiếp hướng vào database production để tránh xung đột dữ liệu.
* Lệnh nâng cấp cơ sở dữ liệu trên Railway được chạy tự động trước khi deploy:
  `python -m flask --app app db upgrade`
* Không tự ý tạo thêm migration mới khi chưa có kế hoạch nghiệp vụ cụ thể.

---

## 14. Chuyển giao Phiên bản (Version Transition)
* Phiên bản 6.5 chính thức được đóng lại.
* Lộ trình tiếp theo sẽ quay trở lại hoàn thành các công việc còn dang dở của **Version 6.4 Backup Center**.
