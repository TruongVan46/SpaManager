# Business Permanent Delete Disablement

## 1. Discovery background

Task 6.5.23a xác nhận Recycle Bin từng có luồng hard-delete hoạt động cho `Customer`, `Service`, `Appointment` và `Invoice`. Luồng này gồm route POST, JavaScript UI, callback registry, bốn public service methods và placeholder `cleanup_old_records()`.

## 2. Legacy runtime paths

Trước Task 6.5.23b, UI gọi `POST /recycle-bin/delete/<item_type>/<item_id>`, registry dispatch tới public permanent-delete method của từng entity và các method thực hiện `db.session.delete()` rồi commit. `cleanup_old_records(days=30)` cũng có thể dispatch các callback đó nếu được gọi.

## 3. Security findings

- Public service methods không bắt buộc entity phải ở trạng thái soft-delete, nên ID của entity active có thể bị hard-delete.
- Candidate cleanup có thể được chọn trước khi một restore đồng thời hoàn tất; service cũ vẫn có thể xóa record vừa được restore.
- Invoice hard-delete xóa cả `InvoiceDetail`, làm mất lịch sử tài chính không thể phục hồi.
- Activity Log không bảo đảm atomicity: lỗi ghi log có thể bị nuốt trong khi business deletion vẫn tiếp tục.
- Cleanup chỉ là placeholder, không có dry-run, batch limit, locking, retry, approval hoặc scheduler policy an toàn.

## 4. Decision

Business permanent-delete bị vô hiệu hóa hoàn toàn. Soft-delete, restore, Recycle Bin listing và workspace isolation tiếp tục được hỗ trợ. Task này không triển khai purge thay thế.

## 5. Runtime changes

- Route permanent-delete đã bị gỡ; URL cũ trả 404 và không mutation.
- Registry không còn callback `permanent_delete_func`.
- Bốn public permanent-delete methods giữ signature để tương thích nhưng raise `ValidationException` trước query, log, delete hoặc commit.

## 6. UI behavior

Recycle Bin vẫn hiển thị thao tác Restore. Nhãn “Xóa vĩnh viễn” chỉ còn là button disabled với thông báo chức năng chưa được hỗ trợ; không có URL, modal hoặc JavaScript mutation ẩn.

## 7. Automatic cleanup behavior

`RecycleBinService.cleanup_old_records()` fail-closed ngay lập tức bằng `ValidationException`. Method không query candidate, không iterate record, không dispatch callback và không commit.

## 8. Tests

Regression tests xác minh URL cũ 404 cho mọi entity/role, active và soft-deleted rows không đổi, cross-workspace rows không đổi, direct services và cleanup fail-closed, InvoiceDetail còn nguyên, không có Activity Log thành công giả, UI chỉ có placeholder disabled và restore vẫn hoạt động.

## 9. Explicit non-goals

- Không migration, schema/FK change hoặc backfill.
- Không purge Account, Workspace, WorkspaceMember hoặc business data.
- Không scheduler, CLI, feature flag hoặc retention runtime.
- Không thêm lifecycle event ID, purge job hay `ActivityLog.workspace_id`.

## 10. Requirements before future re-enable

Một thiết kế tương lai chỉ được xem xét sau khi có đầy đủ:

1. Retention policy được phê duyệt.
2. Lifecycle/purge job ID và provenance rõ ràng.
3. Dry-run manifest có thể review.
4. Second approval cho thao tác phá hủy.
5. Re-authentication trước purge.
6. PostgreSQL rehearsal trên môi trường local/staging riêng.
7. Backup và recovery evidence đã kiểm chứng.
8. Media cleanup strategy.
9. Audit logging atomic với mutation.

## 11. Conclusion

**PERMANENT DELETE DISABLED / FUTURE IMPLEMENTATION BLOCKED**

Account/Workspace purge vẫn chưa được triển khai. Business permanent-delete là legacy flow từng tồn tại thật và nay đã bị vô hiệu hóa vì không đáp ứng yêu cầu an toàn.
