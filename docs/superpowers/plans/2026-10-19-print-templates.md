# 族谱付印三种模板 Implementation Plan

**Goal:** 保留原模板，新增传统竖排分栏式、横行体、汇编体和真实PDF预览；不部署。

**Architecture:** 沿用现有付印权限、脱敏、内容筛选和纸张。传统竖排与欧式横行使用独立PDF排版模块；汇编体复用现有文字排版基础并改为单栏条目。预览生成的PDF在参数变化前直接用于PDF下载，保证所见文件一致。

**Tech Stack:** React/Ant Design、Flask、ReportLab、python-docx；为实际PDF预览新增并锁定pdfjs-dist 6.4.299。旧CSP会拦截Blob iframe；采用PDF.js画布和本站Worker/字体资源，保留原安全策略，不使用外部CDN。

## Global Constraints

- 原模板及未传template的请求保持现有行为。
- 新模板键为traditional、european、compilation；默认original。
- 三种模板支持PDF；compilation支持Word，另外两种Word请求明确拒绝，禁止静默导出旧模板。
- 不修改数据库，不把婚姻记录推断为亲子，不部署。
- 保留此前尚未部署的字号输入框、世系树位置及隐藏环状/扇形入口修改。

### Task 1：模板排版及接口

Files：新增server/service/print_templates.py，修改server/service/printutil.py、server/blueprint/print_bp.py，新增scripts/test_print_templates.py。

- [x] 校验template枚举；旧请求默认original。
- [x] 新样式正文补入真实已登记父母文字，以免同代人物只有姓名而无法判断归属；继续使用脱敏后的资料。
- [x] 将现有h/p/s内容按世代和人物转换为竖排列。传统式五个横栏；欧式五个世代纵格、从右至左。正文长文逐列续页，不省略；续页标记世代和人物以便追读。
- [x] 汇编PDF为单栏人物条目；Word为人物标题与正文段落。原版双栏PDF及表格Word保留。
- [x] 隔离库检查四纸张、封面开关、长文、空谱、非法模板、权限与脱敏；预估页数等于实际PDF。

### Task 2：前端模板与实际预览

Files：web/src/pages/PrintBook.tsx。

- [x] 增加四个模板选项，默认原版；随模板更新页数估算。
- [x] 传统与欧式强制PDF，汇编和原版可选Word。
- [x] 增加PDF.js逐页预览弹窗，采用实际导出PDF，不另画HTML模拟分页。
- [x] 参数/家谱变化废弃旧预览，回收Blob；异步请求失效后不能回填旧家谱。当前参数未变化时，PDF导出复用预览Blob。

### Task 3：验收

- [x] 相关后端回归与新模板检查通过。
- [x] TypeScript与生产构建通过。
- [x] 渲染三种实际PDF并检查中文、换列、续页、边框和文字边界；检查Word条目结构。
- [x] 隔离库实际浏览器检查模板、预估、预览、下载、参数变化和手机端。
- [x] 保存合成示例与验收记录。保持未部署。
