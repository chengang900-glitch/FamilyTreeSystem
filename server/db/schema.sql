-- 家谱管理系统 Web 版 · 数据库结构
-- 业务表沿用原型 FamilyTreeSystem v0.0.4 字段，仅增加 family_id 实现多谱隔离
-- 外键约定：
--   * family_id → family(id) ON DELETE CASCADE：删谱即清空该谱数据
--   * 从属记录（eventperson / resource_relation）→ 随主体级联删除
--   * 核心关系（marriage / parentchild）→ ON DELETE RESTRICT：由应用先给出可读提示
--   * 可选归属（person.branch_id / event.branch_id / branch.parent_id）→ ON DELETE SET NULL

PRAGMA foreign_keys = ON;

-- ============ 账号与权限 ============
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  real_name TEXT,
  phone TEXT,
  email TEXT,
  status INTEGER NOT NULL DEFAULT 1,
  is_superuser INTEGER NOT NULL DEFAULT 0,
  must_change_pwd INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT,
  token_version INTEGER NOT NULL DEFAULT 1,
  last_login_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS family (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  surname TEXT,
  hall_name TEXT,
  generation_chars TEXT,
  generation_frozen INTEGER NOT NULL DEFAULT 0,
  origin_place TEXT,
  compiler TEXT,
  description TEXT,
  visibility INTEGER NOT NULL DEFAULT 0,
  status INTEGER NOT NULL DEFAULT 1,
  created_by INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS family_members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
  granted_by INTEGER,
  granted_at TEXT NOT NULL,
  UNIQUE (family_id, user_id),
  FOREIGN KEY (family_id) REFERENCES family(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_family_members_user ON family_members(user_id);

CREATE TABLE IF NOT EXISTS operation_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  family_id INTEGER,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id INTEGER,
  detail TEXT,
  ip TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_operation_log_family ON operation_log(family_id, created_at);

CREATE TABLE IF NOT EXISTS system_settings (
  key TEXT PRIMARY KEY,
  value TEXT,
  type TEXT NOT NULL DEFAULT 'str',
  group_name TEXT NOT NULL DEFAULT 'general',
  label TEXT,
  description TEXT,
  updated_at TEXT NOT NULL
);

-- ============ 业务表（原型结构 + family_id） ============
CREATE TABLE IF NOT EXISTS person (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id INTEGER NOT NULL,
  generation INTEGER NOT NULL CHECK (generation > 0),
  name TEXT NOT NULL,
  courtesy_name TEXT,
  art_name TEXT,
  type INTEGER NOT NULL DEFAULT 1 CHECK (type BETWEEN 1 AND 6),
  birth_date TEXT,
  birth_date_iso TEXT,
  birth_date_precision TEXT,
  birth_place TEXT,
  death_date TEXT,
  death_date_iso TEXT,
  death_date_precision TEXT,
  address TEXT,
  phone TEXT,
  company TEXT,
  position TEXT,
  bury_address TEXT,
  record TEXT,
  notes TEXT,
  branch_id INTEGER,
  is_private INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (family_id) REFERENCES family(id) ON DELETE CASCADE,
  FOREIGN KEY (branch_id) REFERENCES branch(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_person_family ON person(family_id);
CREATE INDEX IF NOT EXISTS idx_person_branch ON person(branch_id);

CREATE TABLE IF NOT EXISTS marriage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id INTEGER NOT NULL,
  spouse1_id INTEGER NOT NULL,
  spouse2_id INTEGER NOT NULL,
  marriage_order INTEGER NOT NULL DEFAULT 1 CHECK (marriage_order > 0),
  marriage_date TEXT,
  marriage_date_iso TEXT,
  marriage_date_precision TEXT,
  divorce_date TEXT,
  divorce_date_iso TEXT,
  divorce_date_precision TEXT,
  marriage_place TEXT,
  description TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (spouse1_id != spouse2_id),
  FOREIGN KEY (family_id) REFERENCES family(id) ON DELETE CASCADE,
  FOREIGN KEY (spouse1_id) REFERENCES person(id) ON DELETE RESTRICT,
  FOREIGN KEY (spouse2_id) REFERENCES person(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_marriage_family ON marriage(family_id);

CREATE TABLE IF NOT EXISTS parentchild (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id INTEGER NOT NULL,
  parent_id INTEGER NOT NULL,
  child_id INTEGER NOT NULL,
  type INTEGER NOT NULL DEFAULT 1 CHECK (type BETWEEN 1 AND 7),
  child_order INTEGER CHECK (child_order IS NULL OR child_order > 0),
  description TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (parent_id != child_id),
  FOREIGN KEY (family_id) REFERENCES family(id) ON DELETE CASCADE,
  FOREIGN KEY (parent_id) REFERENCES person(id) ON DELETE RESTRICT,
  FOREIGN KEY (child_id) REFERENCES person(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_parentchild_family ON parentchild(family_id);

CREATE TABLE IF NOT EXISTS event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  time TEXT NOT NULL,
  time_iso TEXT,
  time_precision TEXT,
  place TEXT,
  type INTEGER NOT NULL DEFAULT 1 CHECK (type BETWEEN 1 AND 2),
  description TEXT,
  notes TEXT,
  branch_id INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (family_id) REFERENCES family(id) ON DELETE CASCADE,
  FOREIGN KEY (branch_id) REFERENCES branch(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_event_family ON event(family_id);

CREATE TABLE IF NOT EXISTS eventperson (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id INTEGER NOT NULL,
  event_id INTEGER NOT NULL,
  person_id INTEGER NOT NULL,
  role TEXT,
  description TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (event_id, person_id),
  FOREIGN KEY (family_id) REFERENCES family(id) ON DELETE CASCADE,
  FOREIGN KEY (event_id) REFERENCES event(id) ON DELETE CASCADE,
  FOREIGN KEY (person_id) REFERENCES person(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_eventperson_family ON eventperson(family_id);

CREATE TABLE IF NOT EXISTS branch (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id INTEGER NOT NULL,
  parent_id INTEGER,
  name TEXT NOT NULL,
  origin_place TEXT,
  establish_time TEXT,
  description TEXT,
  hall_name TEXT,
  generation_chars TEXT,
  direction TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (family_id) REFERENCES family(id) ON DELETE CASCADE,
  FOREIGN KEY (parent_id) REFERENCES branch(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_branch_family ON branch(family_id);

CREATE TABLE IF NOT EXISTS resource (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  fid TEXT NOT NULL UNIQUE,
  type INTEGER NOT NULL DEFAULT 1 CHECK (type BETWEEN 1 AND 7),
  storage_path TEXT NOT NULL,
  file_size INTEGER,
  mime_type TEXT,
  description TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (family_id) REFERENCES family(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_resource_family ON resource(family_id);

CREATE TABLE IF NOT EXISTS resource_relation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id INTEGER NOT NULL,
  resource_id INTEGER NOT NULL,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('branch', 'person', 'marriage', 'parentchild', 'event')),
  entity_id INTEGER NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (resource_id, entity_type, entity_id),
  FOREIGN KEY (family_id) REFERENCES family(id) ON DELETE CASCADE,
  FOREIGN KEY (resource_id) REFERENCES resource(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_resource_relation_family ON resource_relation(family_id);
