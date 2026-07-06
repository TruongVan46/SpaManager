# Google Auth UI Manual QA

## Scope
- Task 6.3.1.
- UI polish/manual QA only.
- No production enablement.
- No Railway env changes.
- No production migration.

## Pages checked
- **Login page**: Localized to Vietnamese ("Tiếp tục với Google" instead of English, fixed typo "Hoặc" from "Hoạc"). Properly integrates with existing form layout.
- **Pending approval page**: Displays a clear warning card that the account is waiting for owner approval, has log out button, and go back to login page.
- **OWNER pending users page**: Accessible only to the OWNER role. Displays usernames, names, email, role, oauth provider badge, email verification badge, registration time, and Approve/Reject buttons. Displays an empty state message when no pending users exist.
- **Flash messages**: Safe and clear Vietnamese feedback messages for registration pending, rejection/disabled status, and local account email conflicts.
- **Logout flow**: Sessions are completely cleared on logout for both local and Google accounts.

## Manual QA checklist
- [x] Password login still works.
- [x] Google button hidden when disabled.
- [x] Google button visible only when enabled/config valid.
- [x] New Google user lands on pending page.
- [x] Pending page has clear message.
- [x] Pending user cannot access dashboard.
- [x] OWNER sees pending user in `/users/pending`.
- [x] OWNER can approve/reject.
- [x] Approved user can login.
- [x] Rejected/disabled user is blocked.
- [x] Same email local account is not auto-linked (prevents hijacking).
- [x] Mobile/small screen layout is responsive and does not break.

## Production note
- Google auth is still disabled on production.
- Railway env was not changed.
- Production migration was not run.
- Production enablement belongs to the next task.
