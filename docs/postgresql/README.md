# PostgreSQL Migration & Production Docs

Tài liệu tập trung cho quá trình chuyển SpaManager từ SQLite sang PostgreSQL.

## Current status

- Latest stable checkpoint: v5.9.0
- Production database: PostgreSQL
- SQLite data cũ chỉ là test data và không được migrate
- Backup Center đã được guard khi chạy PostgreSQL
- Database backup nên thực hiện bằng Railway/PostgreSQL provider
- SQLite references in this folder are legacy or cutover history, not the product path.

## Overview

- [Migration audit](POSTGRESQL_MIGRATION_AUDIT.md)
- [PostgreSQL-only product mode audit](POSTGRESQL_ONLY_PRODUCT_MODE_AUDIT.md)
- [Schema compatibility](POSTGRESQL_SCHEMA_COMPATIBILITY.md)
- [Backup/restore strategy](POSTGRESQL_BACKUP_RESTORE_STRATEGY.md)
- [Backup/restore policy](POSTGRESQL_BACKUP_RESTORE_POLICY.md)
- [Clean cutover plan](POSTGRESQL_CLEAN_CUTOVER_PLAN.md)
- [Test profile and CI plan](POSTGRESQL_TEST_CI_PLAN.md)
- [Rehearsal environment setup](POSTGRESQL_REHEARSAL_ENVIRONMENT_SETUP.md)
- [Workspace PostgreSQL rehearsal toolchain decision](../workspace/WORKSPACE_POSTGRESQL_REHEARSAL_TOOLCHAIN_DECISION.md)
- [Workspace executable migration approval package](../workspace/WORKSPACE_EXECUTABLE_MIGRATION_APPROVAL_PACKAGE.md)
- [PostgreSQL local dev smoke test](POSTGRESQL_LOCAL_DEV_SMOKE_TEST.md)

## Release checkpoints

- [v5.8.0 readiness checkpoint](V5_8_0_READINESS_CHECKPOINT.md)
- [v5.9.0 PostgreSQL production checkpoint](V5_9_0_POSTGRESQL_PRODUCTION_CHECKPOINT.md)

## v5.9 production migration tasks

- [v5.9.1 Railway PostgreSQL provisioning](V5_9_1_RAILWAY_POSTGRESQL_PROVISIONING.md)
- [v5.9.2 SQLite backup and freeze plan](V5_9_2_SQLITE_BACKUP_FREEZE_PLAN.md)
- [v5.9.3 Fresh PostgreSQL schema initialization plan](V5_9_3_FRESH_POSTGRESQL_SCHEMA_INIT_PLAN.md)
- [v5.9.4 Cutover rehearsal and validation plan](V5_9_4_POSTGRESQL_CUTOVER_REHEARSAL_VALIDATION_PLAN.md)
- [v5.9.5 Production DATABASE_URL cutover](V5_9_5_PRODUCTION_DATABASE_URL_CUTOVER.md)
- [v5.9.6 Post-cutover QA and Backup Center guard](V5_9_6_POST_CUTOVER_QA_AND_POSTGRESQL_BACKUP_CENTER_GUARD.md)

## Notes

- Không lưu secret hoặc raw DATABASE_URL trong repo.
- Không commit database dump/backup.
- Không restore SQLite backup vào PostgreSQL.
- Dùng Railway/PostgreSQL provider backup cho database-level backup.
- Mode A Docker Desktop local PostgreSQL rehearsal is the selected local toolchain path.
- In-app SQLite backup/restore is legacy/test-only in PostgreSQL product mode.
