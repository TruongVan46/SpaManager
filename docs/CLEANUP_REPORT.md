# Báo Cáo Dọn Dẹp Mã Nguồn (Code Cleanup Report)

Ngày lập báo cáo: 2026-06-29 16:30:09

## 1. Unused Python Imports
| Tệp tin | Dòng | Thư viện không dùng |
| --- | --- | --- |
| [app.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/app.py) | 84 | `models` |
| [models\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/models/__init__.py) | 1 | `Customer` |
| [models\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/models/__init__.py) | 2 | `Service` |
| [models\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/models/__init__.py) | 3 | `Appointment` |
| [models\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/models/__init__.py) | 4 | `Invoice` |
| [models\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/models/__init__.py) | 5 | `InvoiceDetail` |
| [models\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/models/__init__.py) | 6 | `Setting` |
| [models\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/models/__init__.py) | 7 | `ActivityLog` |
| [models\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/models/__init__.py) | 8 | `User` |
| [routes\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/__init__.py) | 16 | `dashboard` |
| [routes\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/__init__.py) | 16 | `customer` |
| [routes\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/__init__.py) | 16 | `service` |
| [routes\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/__init__.py) | 16 | `appointment` |
| [routes\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/__init__.py) | 16 | `invoice` |
| [routes\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/__init__.py) | 16 | `report` |
| [routes\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/__init__.py) | 16 | `statistics` |
| [routes\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/__init__.py) | 16 | `setting` |
| [routes\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/__init__.py) | 16 | `activity_log` |
| [routes\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/__init__.py) | 16 | `recycle_bin` |
| [routes\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/__init__.py) | 16 | `auth` |
| [scripts\project_audit.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/scripts/project_audit.py) | 5 | `sys` |
| [services\restore_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/restore_service.py) | 2 | `shutil` |
| [services\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/__init__.py) | 2 | `ActivityLogService` |
| [validators\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/__init__.py) | 2 | `BaseValidator` |
| [validators\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/__init__.py) | 3 | `ValidationResult` |
| [validators\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/__init__.py) | 4 | `ValidationMessages` |
| [validators\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/__init__.py) | 5 | `CustomerValidator` |
| [validators\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/__init__.py) | 6 | `ServiceValidator` |
| [validators\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/__init__.py) | 7 | `AppointmentValidator` |
| [validators\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/__init__.py) | 8 | `InvoiceValidator` |
| [validators\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/__init__.py) | 9 | `BackupValidator` |
| [validators\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/__init__.py) | 10 | `ImportValidator` |
| [validators\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/__init__.py) | 11 | `ProfileValidator` |
| [validators\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/__init__.py) | 12 | `AuthValidator` |
| [validators\rules\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/rules/__init__.py) | 2 | `validate_required` |
| [validators\rules\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/rules/__init__.py) | 3 | `validate_email` |
| [validators\rules\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/rules/__init__.py) | 4 | `validate_phone` |
| [validators\rules\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/rules/__init__.py) | 5 | `validate_number` |
| [validators\rules\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/rules/__init__.py) | 6 | `validate_length` |
| [validators\rules\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/rules/__init__.py) | 7 | `validate_regex` |
| [validators\rules\__init__.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/validators/rules/__init__.py) | 8 | `validate_date` |

## 2. Duplicate Python Imports
| Tệp tin | Dòng | Dòng import bị trùng | Dòng xuất hiện đầu tiên |
| --- | --- | --- | --- |
| [app.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/app.py) | 66 | `from services.auth_service import AuthService` | 53 |
| [app.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/app.py) | 120 | `from services.auth_service import AuthService` | 53 |
| [routes\setting.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/setting.py) | 100 | `from repositories.backup_repository import BackupRepository` | 15 |
| [routes\setting.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/setting.py) | 323 | `from services.activity_log_service import ActivityLogService` | 200 |
| [routes\setting.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/routes/setting.py) | 456 | `import uuid` | 2 |
| [services\appointment_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/appointment_service.py) | 305 | `from validators.appointment_validator import AppointmentValidator` | 65 |
| [services\appointment_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/appointment_service.py) | 306 | `from core.exceptions import ConflictException` | 66 |
| [services\appointment_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/appointment_service.py) | 323 | `from core.exceptions import ValidationException` | 83 |
| [services\appointment_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/appointment_service.py) | 341 | `from services.activity_log_service import ActivityLogService` | 102 |
| [services\appointment_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/appointment_service.py) | 369 | `from core.cache import dashboard_cache` | 109 |
| [services\appointment_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/appointment_service.py) | 384 | `from datetime import datetime` | 6 |
| [services\appointment_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/appointment_service.py) | 389 | `from services.activity_log_service import ActivityLogService` | 102 |
| [services\appointment_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/appointment_service.py) | 396 | `from core.cache import dashboard_cache` | 109 |
| [services\appointment_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/appointment_service.py) | 419 | `from services.activity_log_service import ActivityLogService` | 102 |
| [services\appointment_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/appointment_service.py) | 427 | `from core.cache import dashboard_cache` | 109 |
| [services\appointment_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/appointment_service.py) | 441 | `from services.activity_log_service import ActivityLogService` | 102 |
| [services\appointment_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/appointment_service.py) | 449 | `from core.cache import dashboard_cache` | 109 |
| [services\auth_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/auth_service.py) | 73 | `from models.activity_log import ActivityLog` | 54 |
| [services\auth_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/auth_service.py) | 140 | `from validators.auth_validator import AuthValidator` | 17 |
| [services\auth_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/auth_service.py) | 157 | `from core.exceptions import ValidationException` | 137 |
| [services\auth_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/auth_service.py) | 172 | `from models.activity_log import ActivityLog` | 54 |
| [services\auth_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/auth_service.py) | 191 | `from models.activity_log import ActivityLog` | 54 |
| [services\auth_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/auth_service.py) | 214 | `from core.exceptions import ValidationException` | 137 |
| [services\auth_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/auth_service.py) | 276 | `from models.activity_log import ActivityLog` | 54 |
| [services\backup_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/backup_service.py) | 181 | `from services.activity_log_service import ActivityLogService` | 89 |
| [services\backup_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/backup_service.py) | 257 | `from services.activity_log_service import ActivityLogService` | 89 |
| [services\backup_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/backup_service.py) | 276 | `from services.activity_log_service import ActivityLogService` | 89 |
| [services\customer_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/customer_service.py) | 145 | `from validators.customer_validator import CustomerValidator` | 104 |
| [services\customer_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/customer_service.py) | 167 | `from services.activity_log_service import ActivityLogService` | 128 |
| [services\customer_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/customer_service.py) | 174 | `from core.cache import dashboard_cache` | 135 |
| [services\customer_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/customer_service.py) | 184 | `from models.appointment import Appointment` | 3 |
| [services\customer_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/customer_service.py) | 215 | `from services.activity_log_service import ActivityLogService` | 128 |
| [services\customer_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/customer_service.py) | 222 | `from core.cache import dashboard_cache` | 135 |
| [services\customer_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/customer_service.py) | 237 | `from services.activity_log_service import ActivityLogService` | 128 |
| [services\customer_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/customer_service.py) | 244 | `from core.cache import dashboard_cache` | 135 |
| [services\customer_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/customer_service.py) | 260 | `from services.activity_log_service import ActivityLogService` | 128 |
| [services\customer_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/customer_service.py) | 268 | `from core.cache import dashboard_cache` | 135 |
| [services\import_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/import_service.py) | 363 | `from validators.import_validator import ImportValidator` | 175 |
| [services\invoice_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/invoice_service.py) | 324 | `from datetime import datetime` | 6 |
| [services\invoice_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/invoice_service.py) | 329 | `from services.activity_log_service import ActivityLogService` | 301 |
| [services\invoice_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/invoice_service.py) | 335 | `from core.cache import dashboard_cache` | 308 |
| [services\invoice_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/invoice_service.py) | 362 | `from services.activity_log_service import ActivityLogService` | 301 |
| [services\invoice_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/invoice_service.py) | 370 | `from core.cache import dashboard_cache` | 308 |
| [services\invoice_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/invoice_service.py) | 390 | `from services.activity_log_service import ActivityLogService` | 301 |
| [services\invoice_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/invoice_service.py) | 396 | `from core.cache import dashboard_cache` | 308 |
| [services\restore_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/restore_service.py) | 131 | `from services.activity_log_service import ActivityLogService` | 113 |
| [services\service_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/service_service.py) | 75 | `from validators.service_validator import ServiceValidator` | 40 |
| [services\service_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/service_service.py) | 89 | `from services.activity_log_service import ActivityLogService` | 57 |
| [services\service_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/service_service.py) | 96 | `from core.cache import dashboard_cache` | 64 |
| [services\service_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/service_service.py) | 137 | `from services.activity_log_service import ActivityLogService` | 57 |
| [services\service_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/service_service.py) | 144 | `from core.cache import dashboard_cache` | 64 |
| [services\service_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/service_service.py) | 159 | `from services.activity_log_service import ActivityLogService` | 57 |
| [services\service_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/service_service.py) | 166 | `from core.cache import dashboard_cache` | 64 |
| [services\service_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/service_service.py) | 183 | `from services.activity_log_service import ActivityLogService` | 57 |
| [services\service_service.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/services/service_service.py) | 191 | `from core.cache import dashboard_cache` | 64 |

## 3. Wildcard Python Imports
Không phát hiện wildcard imports.

## 4. Duplicate CSS Selectors
| Tệp tin | Selector trùng | Số lần xuất hiện |
| --- | --- | --- |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `0` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `0` | 3 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `0` | 4 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `0` | 5 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `115` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `223` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `200` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `138` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `194` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `62` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `74` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `59` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `0` | 6 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `0.2` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `0` | 7 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `0` | 8 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `0` | 9 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `0` | 10 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `124` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `82` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `124` | 3 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `82` | 3 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `background-color: rgba(246` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `194` | 3 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `62` | 3 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `.app-select-group` | 2 |
| [static\css\base-page.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base-page.css) | `.app-date-group` | 2 |
| [static\css\layout.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/layout.css) | `0` | 2 |
| [static\css\layout.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/layout.css) | `0` | 3 |
| [static\css\layout.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/layout.css) | `0` | 4 |
| [static\css\layout.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/layout.css) | `.app-container` | 2 |
| [static\css\shared-table.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/shared-table.css) | `110` | 2 |
| [static\css\shared-table.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/shared-table.css) | `253` | 2 |
| [static\css\shared-table.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/shared-table.css) | `background-color: rgba(13` | 2 |
| [static\css\shared-table.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/shared-table.css) | `110` | 3 |
| [static\css\shared-table.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/shared-table.css) | `253` | 3 |
| [static\css\shared-table.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/shared-table.css) | `255` | 2 |
| [static\css\shared-table.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/shared-table.css) | `.stf-toolbar` | 2 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `0` | 2 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `0` | 3 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `0` | 4 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `from` | 2 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `255` | 2 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `transition: background-color var(--transition-fast) ease` | 2 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `border-color var(--transition-fast) ease` | 2 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `box-shadow var(--transition-fast) ease` | 2 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `filter: brightness(0.95);
    box-shadow: 0 4px 8px rgba(0` | 2 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `0` | 5 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `0` | 6 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `transition: transform var(--transition-normal) ease` | 2 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `0` | 7 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `0` | 8 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `transition: background-color var(--transition-fast) ease` | 3 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `transition: background-color var(--transition-fast) ease` | 4 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `border-color var(--transition-fast) ease` | 3 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `0` | 9 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `0` | 10 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `background-color: rgba(var(--primary-color-rgb)` | 2 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `transition: border-color var(--transition-fast) ease` | 2 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `border-color: rgba(var(--primary-color-rgb)` | 2 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `0.5) !important;
    box-shadow: 0 0 0 0.25rem rgba(var(--primary-color-rgb)` | 2 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `transition: transform var(--transition-normal) ease` | 3 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `background-color: rgba(var(--primary-color-rgb)` | 3 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `0` | 11 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `0` | 12 |
| [static\css\base\motion.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/base/motion.css) | `border-color: rgba(var(--primary-color-rgb)` | 3 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 2 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `255` | 2 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 3 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 4 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `124` | 2 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `82` | 2 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `124` | 3 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `82` | 3 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 5 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 6 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 7 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 8 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 9 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 10 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `124` | 4 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `82` | 4 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `background: rgba(166` | 2 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `124` | 5 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `82` | 5 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 11 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 12 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0.08);
    box-shadow: 0 1px 0 rgba(0` | 2 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 13 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 14 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `124` | 6 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `82` | 6 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `124` | 7 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `82` | 7 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 15 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 16 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 17 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 18 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 19 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `0` | 20 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `from` | 2 |
| [static\css\components\command-palette.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/command-palette.css) | `.command-palette-overlay` | 2 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `0` | 2 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `0` | 3 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `0` | 4 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `1.56` | 2 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `0.64` | 2 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `0` | 5 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `0` | 6 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `0` | 7 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `0` | 8 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `0 2px 6px rgba(0` | 2 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `0` | 9 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `0` | 10 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `40` | 2 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `0` | 11 |
| [static\css\components\notification.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/components/notification.css) | `.toast-container` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `background-color: rgba(166` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `124` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `82` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `200` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `138` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `185` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `204` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `194` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `62` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `74` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `59` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `background-color: rgba(28` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `200` | 3 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `138` | 3 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `0.08) !important;
    color: #1cc88a !important;
    border: 1px solid rgba(28` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `200` | 4 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `138` | 4 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `115` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `223` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `background-color: rgba(231` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `74` | 3 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `59` | 3 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `0.08) !important;
    color: #e74a3b !important;
    border: 1px solid rgba(231` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `74` | 4 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `59` | 4 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `135` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `150` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `.activity-log-page .activity-log-toolbar-row` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `.activity-log-page .activity-log-toolbar-row` | 3 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `.activity-log-page .filter-buttons a` | 2 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `.activity-log-page .activity-log-toolbar-row` | 4 |
| [static\css\pages\activity-log.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/activity-log.css) | `.activity-log-page .filter-buttons a` | 3 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 2 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 3 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 4 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 5 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 6 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 7 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 8 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 9 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 10 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 11 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 12 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `border-radius: 10px !important;
    box-shadow: 0 8px 24px rgba(0` | 2 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 13 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 14 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0.14) !important;
    border: 1px solid rgba(0` | 2 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 15 |
| [static\css\pages\appointment-calendar.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment-calendar.css) | `0` | 16 |
| [static\css\pages\appointment.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment.css) | `0` | 2 |
| [static\css\pages\appointment.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment.css) | `0` | 3 |
| [static\css\pages\appointment.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment.css) | `0` | 4 |
| [static\css\pages\appointment.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/appointment.css) | `from` | 2 |
| [static\css\pages\backup-center.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/backup-center.css) | `6px);
    border: 1px solid var(--spa-border-color` | 2 |
| [static\css\pages\backup-center.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/backup-center.css) | `6px);
    border: 1px solid var(--spa-border-color` | 3 |
| [static\css\pages\backup-center.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/backup-center.css) | `115` | 2 |
| [static\css\pages\backup-center.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/backup-center.css) | `223` | 2 |
| [static\css\pages\backup-center.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/backup-center.css) | `200` | 2 |
| [static\css\pages\backup-center.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/backup-center.css) | `138` | 2 |
| [static\css\pages\backup-center.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/backup-center.css) | `185` | 2 |
| [static\css\pages\backup-center.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/backup-center.css) | `204` | 2 |
| [static\css\pages\layout-spacing.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/layout-spacing.css) | `0` | 2 |
| [static\css\pages\layout-spacing.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/layout-spacing.css) | `.app-card-grid` | 2 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `185` | 2 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `204` | 2 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `194` | 2 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `62` | 2 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `115` | 2 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `223` | 2 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `200` | 2 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `138` | 2 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `74` | 2 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `59` | 2 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `.recycle-bin-page .recycle-bin-toolbar-row` | 2 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `.recycle-bin-page .recycle-bin-toolbar-row` | 3 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `.recycle-bin-page .filter-buttons a` | 2 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `.recycle-bin-page .recycle-bin-toolbar-row` | 4 |
| [static\css\pages\recycle-bin.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/recycle-bin.css) | `.recycle-bin-page .filter-buttons a` | 3 |
| [static\css\pages\setting.css](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/css/pages/setting.css) | `.data-stats-grid` | 2 |

## 5. Duplicate JavaScript Functions
| Tệp tin | Dòng trùng | Tên Function | Dòng xuất hiện đầu tiên |
| --- | --- | --- | --- |
| [static\js\libs\chart.js](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/js/libs/chart.js) | 13 | `f` | 7 |
| [static\js\libs\chart.js](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/js/libs/chart.js) | 13 | `s` | 7 |
| [static\js\libs\chart.js](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/js/libs/chart.js) | 13 | `g` | 7 |
| [static\js\libs\chart.js](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/static/js/libs/chart.js) | 13 | `l` | 7 |

## 6. Dead / Unused HTML Templates
| Tên Template | Đường dẫn tương đối |
| --- | --- |
| `404.html` | `templates/errors/404.html` |
| `500.html` | `templates/errors/500.html` |
| `table_macros.html` | `templates/layout/table_macros.html` |

## 7. Empty Directories
| Thư mục rỗng |
| --- |
| `static\uploads\avatars` |

## 8. TODO / FIXME / HACK / XXX Items
| Tệp tin | Dòng | Loại | Mô tả |
| --- | --- | --- | --- |
| [scripts\project_audit.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/scripts/project_audit.py) | 118 | **TODO** | , FIXME, HACK, XXX |
| [scripts\project_audit.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/scripts/project_audit.py) | 119 | **TODO** | |FIXME|HACK|XXX)\b:?\s*(.*)', re.IGNORECASE) |
| [scripts\project_audit.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/scripts/project_audit.py) | 362 | **TODO** | / FIXME / HACK List |
| [scripts\project_audit.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/scripts/project_audit.py) | 363 | **TODO** | / FIXME / HACK / XXX Items\n") |
| [scripts\project_audit.py](file:///C:\Users\ADMIN\VS CODE\Project\SpaManager/scripts/project_audit.py) | 371 | **TODO** | items.\n") |

