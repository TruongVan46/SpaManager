# Workspace Implementation Readiness Audit

## 1. Scope
- **Mục tiêu:** Rà soát và đánh giá toàn bộ hiện trạng của phần nền tảng Workspace/Tenant Isolation (cô lập dữ liệu giữa các cơ sở Spa) trước khi tiến hành viết code triển khai tính năng thực tế.
- **Hành động không thực hiện (Non-actions):**
  - Không tạo tệp migration executable mới trong `migrations/versions/`.
  - Không chạy bất kỳ lệnh migration nào trên production (Railway).
  - Không chỉnh sửa bất kỳ hành vi logic nghiệp vụ hay thay đổi dữ liệu nào của ứng dụng.
  - Không tạo tệp approval marker hay thay đổi cấu hình app.

---

## 2. Desired Product Model
Mô hình Multi-Tenancy mong muốn của SpaManager được xác định như sau:
- **Cơ sở dữ liệu vật lý chung:** Ứng dụng chỉ sử dụng duy nhất một PostgreSQL database chung trên production (Railway).
- **Phân tách bằng Workspace:** Mỗi tài khoản chủ Spa (`OWNER`) được duyệt sẽ được cấp phát 1 Workspace riêng biệt (đại diện cho một cơ sở Spa độc lập).
- **Phân quyền trong Workspace:** Chủ Spa có quyền tạo ra các tài khoản quản lý (`ADMIN`) và nhân viên (`STAFF`) thuộc cùng Workspace của mình. Các tài khoản này sẽ cùng làm việc và chia sẻ dữ liệu của Workspace đó.
- **Cô lập dữ liệu tuyệt đối:** Dữ liệu giữa các Workspace khác nhau (Khách hàng, Dịch vụ, Lịch hẹn, Hóa đơn, Cài đặt...) phải được tách biệt hoàn toàn thông qua bộ lọc cột `workspace_id`. Một tài khoản ở Workspace A không được phép đọc, ghi hoặc xóa dữ liệu thuộc Workspace B.

---

## 3. Existing Docs Found
Các tài liệu thiết kế và lập kế hoạch Workspace đã tồn tại trong thư mục `docs/workspace/`:
1. `docs/workspace/README.md` — Mục lục hướng dẫn và giới thiệu tổng quan các tài liệu Workspace.
2. `docs/workspace/WORKSPACE_ARCHITECTURE_AUDIT.md` — Rà soát kiến trúc, các rủi ro bảo mật và kế hoạch định hướng phân quyền.
3. `docs/workspace/WORKSPACE_SCHEMA_DESIGN.md` — Thiết kế chi tiết cấu trúc bảng `workspaces` và `workspace_members`.
4. `docs/workspace/WORKSPACE_MODELS_AND_MIGRATION_DRAFT.md` — Bản thảo mã nguồn các models SQLAlchemy và pseudo-code cho migration.
5. `docs/workspace/WORKSPACE_MIGRATION_REHEARSAL_PLAN.md` — Kế hoạch diễn tập nâng cấp/hạ cấp migration trên môi trường cục bộ.
6. `docs/workspace/WORKSPACE_MIGRATION_EXECUTION_GATE.md` — Cổng kiểm soát bảo mật ngăn chặn việc tự động chạy migration trên Railway khi chưa được phê duyệt.
7. `docs/workspace/WORKSPACE_MIGRATION_LOCAL_REHEARSAL_EVIDENCE.md` — Ghi nhận bằng chứng diễn tập thành công trên môi trường Docker PostgreSQL local.
8. `docs/workspace/WORKSPACE_EXECUTABLE_MIGRATION_APPROVAL_PACKAGE.md` — Định nghĩa gói phê duyệt và từ khóa kích hoạt migration an toàn.
9. `docs/workspace/WORKSPACE_POSTGRESQL_REHEARSAL_TOOLCHAIN_DECISION.md` — Quyết định lựa chọn công cụ Docker cho quá trình diễn tập.
10. `docs/workspace/migration_candidates/0002_workspace_foundation.py.txt` — File chứa pseudo-code mô tả cấu trúc của bản nháp nâng cấp schema.

---

## 4. Existing Code Found
- **Models (`models/workspace.py`):**
  - Đã định nghĩa đầy đủ hai lớp SQLAlchemy models: `Workspace` (bảng `workspaces`) và `WorkspaceMember` (bảng `workspace_members`).
  - Lớp `WorkspaceMember` định nghĩa sẵn các vai trò thành viên (`owner`, `admin`, `staff`) và trạng thái hoạt động (`active`, `invited`, `disabled`).
  - Các lớp model này đã được import ở `models/__init__.py`.
- **Services & Routes:** Chưa có bất kỳ code xử lý logic nghiệp vụ hay API route nào liên quan đến Workspace trong các thư mục `services/` và `routes/`.
- **Tests (`tests/test_basic.py`):**
  - Đã có một số unit tests cơ bản kiểm tra tính chính xác của metadata và mối quan hệ giữa `Workspace` và `WorkspaceMember`:
    - `test_workspace_models_expose_expected_metadata`
    - `test_workspace_models_expose_expected_status_and_role_constants`
    - `test_workspace_model_smoke_create_and_relationships`

---

## 5. Existing Migrations and Database State
- **Local DB Revision:** `0002_google_auth_approval` (đã chạy và khớp với Alembic version hiện tại).
- **Alembic History:** Chỉ có 2 phiên bản là `0001_baseline` và `0002_google_auth_approval`. Không có tệp migration nào dành cho Workspace trong `migrations/versions/`.
- **DB Local Schema State (Postgres):**
  - Thật bất ngờ, hai bảng `workspaces` và `workspace_members` **đã tồn tại vật lý** trong database Postgres local (nhưng chưa có trong migrations thực tế).
  - Cấu trúc cột của `workspaces` và `workspace_members` đã khớp với thiết kế.
  - Tuy nhiên, các bảng nghiệp vụ (`customers`, `services`, `appointments`, `invoices`, `users`, `settings`) **chưa** hề có cột `workspace_id`.
- **Production Schema State (Railway):** Hoàn toàn chưa có các bảng `workspaces`, `workspace_members` và chưa có các cột `workspace_id`.

---

## 6. Google Approval Connection
- **Hành vi tạo Google user mới:** Người dùng Google đăng nhập lần đầu sẽ được tạo bản ghi trong bảng `users` ở trạng thái chờ duyệt (`approval_status = "pending"`, `is_active = False`).
- **Hành vi phê duyệt:** Khi tài khoản `APPROVAL_OWNER` phê duyệt tài khoản pending tại trang duyệt `/approval/pending`, hàm `UserService.approve_pending_user` chỉ thiết lập `approval_status = "active"` và `is_active = True`.
- **Liên kết Workspace khi Approve:** **KHÔNG**. Hiện tại hoàn toàn chưa có logic tự động tạo Workspace riêng cho chủ Spa mới được duyệt và chưa gán họ làm `owner` của bất kỳ Workspace nào.

---

## 7. Data Isolation Status by Module

| Module / Bảng | `workspace_id` có tồn tại? | Logic tạo tự gán Workspace? | Logic truy vấn có lọc Workspace? | Logic sửa/xóa có bảo vệ? | Trạng thái hiện tại |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **users (Tài khoản)** | Không | Không | Không (truy vấn toàn cục) | Không | Chưa cô lập |
| **customers (Khách hàng)** | Không | Không | Không | Không | Chưa cô lập |
| **services (Dịch vụ)** | Không | Không | Không | Không | Chưa cô lập |
| **appointments (Lịch hẹn)** | Không | Không | Không | Không | Chưa cô lập |
| **invoices (Hóa đơn)** | Không | Không | Không | Không | Chưa cô lập |
| **dashboard (Trang chủ)** | Không | Không | Không (tính toán doanh thu toàn cục) | Không | Chưa cô lập |
| **settings (Cài đặt)** | Không | Không | Không | Không | Chưa cô lập |

---

## 8. Gap Analysis (Các phần còn thiếu để chạy Multi-Tenant)
Để có thể đưa tính năng Workspace vào sử dụng thực tế công cộng (Public Multi-Tenant), chúng ta cần phải giải quyết các lỗ hổng sau:
1. **Thiếu tệp migration executable thực tế:** Cần bổ sung file `.py` hợp lệ vào `migrations/versions/` để tạo các bảng Workspace và thêm cột `workspace_id` vào toàn bộ bảng nghiệp vụ.
2. **Thiếu logic gán Workspace tự động:** Cần viết thêm code tự động tạo 1 bản ghi `Workspace` mới và 1 bản ghi `WorkspaceMember` vai trò `owner` ngay khi phê duyệt chủ Spa.
3. **Thiếu Session Workspace Context:** Ứng dụng chưa có cơ chế lưu giữ `current_workspace_id` trong Flask session khi người dùng đăng nhập.
4. **Thiếu bộ lọc truy vấn (Query scoping):** Tất cả các câu lệnh SQL/SQLAlchemy trong router và service chưa lọc theo `workspace_id` của Workspace hiện tại.
5. **Chưa có logic phân tách tài khoản nhân viên:** Khi chủ Spa tạo tài khoản STAFF/ADMIN mới, hệ thống chưa tự động gán tài khoản đó vào cùng Workspace của chủ Spa.

---

## 9. Can Implementation Start Now?
**Trả lời:** **PARTIAL (Bắt đầu một phần)**.
- **Lý do:** 
  - Các tài liệu phân tích kiến trúc, thiết kế schema và mã nguồn models (`models/workspace.py`) đã được chuẩn bị sẵn sàng và kiểm tra bằng unit tests ổn định. Giai đoạn thiết kế cơ bản đã hoàn tất.
  - Tuy nhiên, chúng ta **chưa thể bắt đầu viết code logic nghiệp vụ cô lập** (scoping code) ngay lúc này vì cấu trúc schema thực tế trên DB chưa được nâng cấp (chưa có cột `workspace_id` trên các bảng nghiệp vụ).
  - Do đó, bước đi tiếp theo bắt buộc phải là xây dựng tệp migration executable và chạy diễn tập nâng cấp cơ sở dữ liệu thành công trước khi bắt tay viết logic nghiệp vụ.

---

## 10. Recommended Implementation Roadmap
Lộ trình triển khai khuyến nghị gồm các bước sau:
1. **Task 6.5.2 Workspace schema/migration creation:** Tạo tệp migration Alembic executable chính thức trong `migrations/versions/` (bổ sung cột `workspace_id` nullable, tạo bảng `workspaces`, `workspace_members`, tạo Default Workspace và thực hiện backfill dữ liệu lịch sử).
2. **Task 6.5.3 Auto-create workspace on approval:** Cập nhật hàm phê duyệt người dùng của `UserService` để tự động tạo Workspace và gán quyền chủ sở hữu (`owner`) cho tài khoản Google mới được phê duyệt.
3. **Task 6.5.4 Workspace membership and current workspace context:** Thiết lập helper lưu trữ và trích xuất `current_workspace_id` từ session Flask khi người dùng đăng nhập.
4. **Task 6.5.5 Data isolation implementation:** Bổ sung bộ lọc `workspace_id` vào tất cả các tác vụ CRUD (Customers, Services, Appointments, Invoices) và các báo cáo doanh thu trên Dashboard.
5. **Task 6.5.6 Staff/manager creation inside workspace:** Điều chỉnh logic tạo người dùng mới trong app để đảm bảo ADMIN/STAFF được tạo ra sẽ tự động thuộc về Workspace của người tạo.
6. **Task 6.5.7 Workspace isolation tests and production readiness:** Viết thêm các ca kiểm thử tích hợp kiểm tra rò rỉ dữ liệu chéo giữa các Workspace và kiểm thử độ ổn định.
7. **Task 6.5.8 Production migration execution:** Thực hiện quy trình deploy an toàn lên production (Railway) theo runbook phê duyệt.

---

## 11. Risks
- **Rò rỉ dữ liệu chéo (Cross-tenant Data Leakage):** Nếu mở rộng đăng ký tài khoản Google công khai trước khi hoàn thiện Data Isolation, bất kỳ chủ Spa mới nào cũng có thể đọc và sửa dữ liệu của chủ Spa ban đầu.
- **Rủi ro tự động chạy Migration:** Do Railway tự động thực thi `db upgrade` khi có tệp migration mới, bất kỳ lỗi cú pháp hoặc lỗi logic backfill nào trong tệp migration cũng sẽ làm ứng dụng trên production bị crash khi deploy.
- **Rủi ro Backfill dữ liệu cũ:** Phải đảm bảo tất cả các bản ghi lịch sử hiện tại trên production được gán chính xác vào Workspace mặc định (ID 1) trước khi đặt thuộc tính `NOT NULL` cho cột `workspace_id`.
