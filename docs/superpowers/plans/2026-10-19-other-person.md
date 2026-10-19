# Other Member Type Implementation Plan

**Goal:** Add types 7 “其他（男）” and 8 “其他（女）” while preserving existing family data and existing type meanings.

**Architecture:** Extend the existing enumeration and validation ranges. Rebuild only the old SQLite person CHECK constraint, preserving its original DDL except for the upper bound 8 and preserving all dependent schema objects. Use the corresponding male/female rules for types 7/8.

**Constraints:** User explicitly selected the enum approach; no extra gender fields or configuration; explicitly exclude types 7/8 from every print path. Preserve prior r7 changes and uncommitted work. Deploy only familytree after source and migration verification.

1. Write isolated API and migration regressions covering valid7,8/invalid9, foreign-child relation, JSON/GEDCOM roundtrip, correct male/female print text, old-schema row/index/trigger/sequence preservation, rollback and idempotence. Confirm pre-change failures.
2. Extend `web/src/constants.ts`, `family_bp.py` person validation, JSON import range, `schema.sql`; add `ensure_person_types` to migrate.py and init_db. Use BEGIN IMMEDIATE, foreign_keys OFF only during the transaction, and foreign_key_check before COMMIT. Preserve original dependent index/trigger SQL and sqlite_sequence; restore PRAGMA settings in finally.
3. Handle type7/8 male/female SVG colors, parent pairing, GEDCOM sexes and print child/spouse labels. Update existing profile test so 9 is the invalid type.
4. Run focused API/migration/profile/reference/print/layout regressions; build and typecheck frontend. Browser-check real create/edit/filter/child-picker controls against an isolated database.
5. Build a new release from the current r7 runtime, replacing audited changed Python files and frontend assets. Check startup/migration against an isolated production snapshot. Stop familytree, create and validate a full data snapshot, migrate while offline, compare original business fields and file hashes, then switch the container. Restore old image on failure without replacing newer business data.
6. Verify public assets/health, retain data snapshot and old image, update release notes with exact acceptance boundaries.

付印共用_load只提供1至6类型的items及pmap，并拒绝其他类型主人物；界面限制主人物候选。世系图仍显示两类其他人员。

执行结果：r8/r9已发布，验证详情见 ../../发布-20261019-r8-r9.md；浏览器采用合成接口数据，真实后端及旧库迁移另在隔离库中验收。
