# 部署与运维说明

## 一、目录结构

```
家谱管理系统/
├─ server/            后端（Flask + SQLite）
│  ├─ app.py          应用工厂：鉴权中间件、安全头、限流、SPA 回退
│  ├─ run.py          启动入口（Windows: Waitress / Linux: Gunicorn）
│  ├─ config.yaml     部署配置（端口、路径）
│  ├─ requirements.txt
│  ├─ db/schema.sql   数据库结构（含外键约束）
│  ├─ db/migrate.py   旧库结构迁移（自动补外键 + 清理脏数据，幂等）
│  ├─ blueprint/      auth / admin / family / data / pedigree / io / print
│  ├─ service/        auth / permission / settings / privacy / valid / audit / backup / printutil / netutil
│  └─ webroot/        前端构建产物（由 web/ 构建生成）
├─ web/               前端（Vite + React + TS + antd）
├─ deploy/            Docker 与 Nginx 配置、启动脚本
├─ scripts/           自测与冒烟脚本（均使用独立临时库）
├─ data/              运行时数据（app.db、uploads、backups）
├─ log/               运行日志（server.log，按 5MB × 3 轮转）
└─ docs/              方案、接口文档与修复说明
```

## 二、本地启动（Windows）

前置：Python 3.13、Node 22。

```bash
# 1. 安装后端依赖
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r server\requirements.txt

# 2. 构建前端（含类型检查，产物输出到 server/webroot）
cd web && npm install && npm run build && cd ..

# 3. 启动（默认 http://127.0.0.1:8100）
.venv\Scripts\python.exe server\run.py
# 或双击 deploy\start.bat
```

**初始账号**：首次启动自动创建超管 `admin`，初始口令默认**随机生成**，仅在控制台打印一次：

```
==============================================================
已创建超级管理员账号 admin
  初始密码：xxxxxxxxxxxx
  该密码仅显示一次，首次登录后必须修改。
==============================================================
```

如需指定初始口令（例如自动化部署），在首次启动前设置环境变量：

```bash
set FTS_ADMIN_PASSWORD=YourInitPass123
```

首次登录后后端会强制要求改密（未改密前除 `/api/auth/me`、`/api/auth/password`、
`/api/auth/logout` 外的接口一律返回 403/4031）。

## 三、Linux 部署

```bash
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt
cd web && npm install && npm run build && cd ..
.venv/bin/python server/run.py     # 自动使用 Gunicorn（2 worker × 4 线程）
```

中文字体（PDF 导出需要）：`apt install fonts-noto-cjk`，ReportLab 会自动探测；
未安装时 PDF 中文将退化为方块，请检查 `log/server.log`。

## 四、Docker 部署（推荐）

```bash
# 构建并启动（应用 + Nginx）
docker compose -f deploy/docker-compose.yml up -d --build

# 查看日志（初始口令也在这里）
docker compose -f deploy/docker-compose.yml logs -f app
```

要点：

- 镜像内配置位于 `/app/config.yaml`（由 `server/config.yaml` 复制而来），
  `FTS_CONFIG` 指向它；需要改参数时把自定义配置文件挂载到该路径覆盖，不要依赖 `/app/data/config.yaml`。
- 数据卷 `appdata` 挂载到 `/app/data`，含 SQLite 主库、上传资源、备份。
  容器重建不会丢数据，但**必须保留该卷**。
- 不要把数据卷放在 NFS 等网络文件系统上，SQLite 文件锁不可靠。
- 反向代理链路上的真实 IP：`compose` 已注入
  `FTS_TRUSTED_PROXIES=127.0.0.1,::1,172.16.0.0/12`，只有来自该网段的
  `X-Forwarded-For` 才会被采信，公网直连伪造的 XFF 一律忽略。
  裸机部署时保持默认 `127.0.0.1,::1` 即可（Nginx 与本机同址）。
- 公网部署请在 `deploy/nginx.conf` 中启用 443 与 TLS 证书，并在「系统设置」中打开
  `security.force_https`（应用将下发 HSTS）。
- Nginx 已设置 `client_max_body_size 256m`，如需更大上传同步调整与
  `storage.upload_max_mb`。

## 五、公网安全清单

| 项目 | 处置 |
|---|---|
| 首次口令 | 随机生成、仅打印一次、后端强制首登改密 |
| 传输 | Nginx 终止 TLS，强制 HTTPS |
| 会话 | 访问 JWT 8h + 刷新 JWT 7d，均存 httpOnly + Secure + SameSite=Strict Cookie；改密/重置/登出即失效旧令牌 |
| CSRF | SameSite=Strict + 写接口校验 Origin 白名单 |
| 暴破 | 登录失败 5 次锁定 10 分钟；登录接口限流 20 次/分钟（IP 取受信代理后的真实来源） |
| 上传 | 类型白名单 + 大小上限 + 随机文件名 + 非 Web 根目录 |
| 下载 | 全部走 `/api/families/<fid>/files/<rid>` 鉴权代理，无静态直链 |
| 越权 | 接口按 family_id 作用域校验，写操作二次校验记录归属；授家谱管理员仅限超管 |
| 响应头 | CSP、X-Content-Type-Options、X-Frame-Options、Referrer-Policy |
| 缓存 | 接口与 HTML 不缓存；`/assets/*` 长缓存（文件名带内容哈希） |
| 审计 | 写操作全量入 operation_log，写入失败记录 warning |
| 备份 | 自动备份（默认 60 分钟一次，保留 5 份），多进程下单实例调度 |

## 六、运维

- 配置：`server/config.yaml`（端口、路径）。支持环境变量 `FTS_HOST` / `FTS_PORT` /
  `FTS_CONFIG` / `FTS_TRUSTED_PROXIES` / `FTS_ADMIN_PASSWORD`（仅首次启动生效）。
- 日志：`log/server.log`（5MB 轮转，保留 3 份），同时输出到控制台。
- 备份：`data/backups/backup_*.zip`（含数据库 + 资源目录）。恢复推荐停服后执行：
  `python scripts/restore_backup.py data/backups/backup_xxx.zip --yes`
  （脚本会做完整性检查、保留旧库、清理 WAL）。也可手工解压后把 `data/db_*.db`
  重命名为 `app.db` 覆盖 `data/app.db`，资源放回 `data/uploads/`。
  家谱管理员可在页面“备份与恢复”做本谱级备份/恢复；备份失败会写 error 日志。
- **结构迁移**：升级到本版本后首次启动，会自动把旧库补齐外键（`person.branch_id`、
  `marriage.spouse*`、`parentchild.*`、`eventperson.*`、`resource_relation.*` 等），
  并清理迁移前已存在的悬空引用（孤儿 `eventperson`、指向不存在人物的婚姻等）。
  全程在一个事务内完成，失败自动回滚并写 error 日志。
  建议升级前先备份 `data/app.db`（直接复制文件即可，或先跑一次手动备份）。
- 数据导入：支持 JSON / GEDCOM / ZIP / ZUP，导入时按「旧 ID → 新 ID」重映射，
  ZIP/ZUP 内 `resources/` 原件会解出并写回上传目录。

## 七、自测

```bash
# 单元级（自动使用独立临时库，不会写入 data/app.db）
.venv/Scripts/python.exe scripts/test_m1.py     # 认证与三级鉴权（24 项）
.venv/Scripts/python.exe scripts/test_m2.py     # 成员/婚姻/亲子/分支（23 项）
.venv/Scripts/python.exe scripts/test_m3.py     # 事件/资源/鉴权下载（18 项）
.venv/Scripts/python.exe scripts/test_m4.py     # 世系树/导入导出/付印（22 项）
.venv/Scripts/python.exe scripts/test_fixes.py  # 本次修复的回归用例（52 项）
.venv/Scripts/python.exe scripts/test_review2.py  # 复审专项用例（33 项）
.venv/Scripts/python.exe scripts/test_product.py   # 产品功能补齐用例（40 项）

# 合计 212 项

# 端到端（需服务已启动）
.venv/Scripts/python.exe scripts/smoke.py http://127.0.0.1:8100
# 管理员已改过密码时：
SMOKE_PASSWORD=新密码 .venv/Scripts/python.exe scripts/smoke.py http://127.0.0.1:8100
```

如果确实需要在生产库上跑自测（不推荐），必须显式设置 `FTS_ALLOW_PROD_DB=1`，
否则 `_testenv.assert_isolated()` 会直接终止脚本。
