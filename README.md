# 家谱管理系统（FamilyTreeSystem）

一套轻量、可私有部署的家谱管理系统。后端 Flask + SQLite，前端 Vite + React + TypeScript + Ant Design，
支持多人协作维护世系、婚姻、事件与附件资源，并可导出 GEDCOM / JSON / PDF / Word。

## 功能

| 模块 | 说明 |
|---|---|
| 认证 | scrypt 口令散列、JWT 访问令牌 + 刷新令牌存 httpOnly Cookie、登录失败锁定、首登强制改密 |
| 权限 | 三级角色（超管 / 家谱管理员 / 普通成员），接口按家谱作用域校验，写操作二次校验记录归属 |
| 人员 | 世系代数、字辈配置与冻结沿用、在世者隐私脱敏、CSV 导出 |
| 关系 | 婚姻（多配偶）、亲子（支持收养 / 继嗣 / 寄养）、成环检测 |
| 分支 | 房系支派管理，支持批量挂载成员 |
| 事件 | 生卒、婚娶、迁徙、科举等事件与人物关联 |
| 世系图 | 树形 / 层状 / 谱系图，支持缩放拖拽、直接高亮 |
| 资源 | 图片 / PDF / 视频 / 文档上传，鉴权代理下载，无静态直链 |
| 导入导出 | JSON / GEDCOM / ZUP（导入按旧 ID→新 ID 重映射）、PDF / Word 付印 |
| 备份 | 定时自动备份（SQLite 官方备份 API + 资源打包 ZIP），超管全库备份、家谱级备份/恢复，多进程下单实例调度 |
| 审计 | 写操作全量入 `operation_log`，支持结构化变更摘要、本谱/全站日志与 CSV 导出 |

## 技术栈

- **后端**：Python 3.13、Flask 3、waitress（Windows）/ gunicorn（Linux）、SQLite（外键约束）
- **前端**：Node 22、Vite、React 19、TypeScript、Ant Design 6
- **部署**：Docker Compose（应用 + Nginx）或本机脚本

## 快速开始（Windows）

```bash
# 1. 后端依赖
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r server\requirements.txt

# 2. 构建前端（产物输出到 server/webroot）
cd web && npm install && npm run build && cd ..

# 3. 启动
.venv\Scripts\python.exe server\run.py
# 或直接双击 deploy\start.bat
```

访问 <http://127.0.0.1:8100/>。首次启动会自动创建超管 `admin`，
**初始口令随机生成、仅在控制台打印一次**，首次登录后强制改密。
自动化部署可预设 `FTS_ADMIN_PASSWORD` 环境变量。

Linux 与 Docker 部署方式见 [DEPLOY.md](DEPLOY.md)。

## 自测

所有单元级脚本强制使用独立临时库，不会写入 `data/app.db`。

```bash
.venv\Scripts\python.exe scripts/test_m1.py      # 认证与三级鉴权（24 项）
.venv\Scripts\python.exe scripts/test_m2.py      # 成员/婚姻/亲子/分支（23 项）
.venv\Scripts\python.exe scripts/test_m3.py      # 事件/资源/鉴权下载（18 项）
.venv\Scripts\python.exe scripts/test_m4.py      # 世系树/导入导出/付印（22 项）
.venv\Scripts\python.exe scripts/test_fixes.py  # 安全与数据正确性回归（52 项）
.venv\Scripts\python.exe scripts/test_review2.py  # 复审专项：路径/脱敏/GEDCOM/多段婚姻（33 项）
.venv\Scripts\python.exe scripts/test_product.py   # 产品补齐：刷新/日志/备份/ZUP（40 项）

# 新增专项（test_reference 解析 PDF 页数，需额外安装 pypdf）
.venv\Scripts\python.exe -m pip install pypdf
.venv\Scripts\python.exe scripts/test_reference.py # 参考功能补齐（44 项）
.venv\Scripts\python.exe scripts/test_profile.py   # 日期/联系字段/婚姻次序/再婚亲子（26 项）
node scripts/test_layout.mjs                       # 五种布局节点覆盖（Node 22.18+）

# 后端合计 282 项，全部使用独立临时库；布局另外执行五种模式检查

# 端到端（需服务已启动）
.venv\Scripts\python.exe scripts/smoke.py http://127.0.0.1:8100
```

## 目录结构

```
├─ server/     后端：app.py 应用工厂、blueprint/ 路由、service/ 业务、db/ 结构与迁移
├─ web/        前端源码
├─ deploy/     Dockerfile、docker-compose.yml、nginx.conf、启动脚本
├─ scripts/    自测与冒烟脚本
├─ data/       运行时数据（app.db、uploads、backups），不入库
└─ docs/       产品方案、代码审查报告、修复说明、复审修复说明
```

## 文档

- [参考功能完善说明（日期、成员资料、婚姻次序与亲子录入）](docs/参考功能完善说明-2026-10-19.md)

- [产品开发方案](docs/产品开发方案.md)
- [部署与运维说明](DEPLOY.md)
- [代码审查报告](docs/代码审查报告.md)
- [修复说明](docs/修复说明.md)
- [复审修复说明](docs/复审修复说明.md)
- [产品功能缺口清单](docs/产品功能缺口清单.md)
- [产品功能补齐说明](docs/产品功能补齐说明.md)

## 安全说明

默认配置面向**私有化内网/局域网部署**。若需公网暴露，请按
[DEPLOY.md 公网安全清单](DEPLOY.md) 配置 TLS、强制 HTTPS、可信代理网段，并及时修改初始口令。

运行时数据、密钥、依赖目录与前端构建产物均已通过 `.gitignore` 排除，切勿将
`data/`（含 `app.db` 与 `secret.key`）提交到公开仓库。
