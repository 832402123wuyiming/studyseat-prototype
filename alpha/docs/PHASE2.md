# 11 月 23—24 日阶段二记录

实际开发与验证日期：2026-11-23。目标：学生查询、预约、取消贯通与可复现的并发冲突控制。实际工作为本次 AI 辅助开发，不将工作量追溯归属到附件计划中的成员；非作者审查和团队正式验收仍待执行。

## 工作环境与基线

目标 Git 根目录 `/Users/zhouyiheng/Desktop/软件工程/studyseat-phase2`，分支 `codex/phase2-reservations`，初始 HEAD `f0fd0fcde746292deeca804bef46fb67d1cda5e2`，包含 PR #2 合并基线且工作区干净。原先打开的原型目录 main 存在未跟踪文件，未改动、未纳入提交。根目录原无 AGENTS.md，按请求创建三项项目约定。

依据附件《StudySeat_代码规范与冲刺计划.docx》的第二阶段日期段及现有 README、API、RULES、DAY1、ACCOUNT-SWITCH-REVIEW。附件中关于远程 Issue、PR 和非作者审查的团队流程作为交接要求；本次仅授权本地开发与提交，不创建远程任务、不推送、不合并、不发布。

## 已实现内容

独立提交 c393265 修复原型导出 README 的 Alpha 断链，保留原型构建用途、哈希和覆盖保护，使用交付白名单并排除数据库、密钥和依赖。修复前链接测试 1 通过 / 1 失败，修复后原型 70 项通过，见 [导出回归记录](EXPORT-REGRESSION.md)。

新增 reservations.py 业务服务；查询、创建、本人列表与详情、取消均由 Flask 接口提供，学生页通过同源 Cookie 和 CSRF 访问。身份与角色取自服务端。复用现有 v1 表，不修改旧表声明、不需要结构迁移。预约与审计关联，规则版本和完整快照落库。UTC 六位微秒持久化、北京时间输入输出、左闭右开时段、规则和资源校验见 [接口契约](API-v1.md) 与 [规则](RULES.md)。

创建在 BEGIN IMMEDIATE 内完成资源/规则检查、同座位与同学生跨座位冲突检查、预约及审计；失败整体回滚。幂等键按学生隔离，同规范化载荷返回同一预约当前状态，异载荷 409。取消也采用单事务，重复取消保留首次 ended_at 和单条审计。占用由有效预约区间计算，无第二份需要同步的占座计数。

页面包含查询加载、空列表、失败反馈、创建重试、预约刷新和取消入口。身份切换清空预约与座位，延迟响应不能回写新身份或已修改的查询。回执丢失时，相同页面内原载荷重试沿用幂等键。

## 验收步骤

1. 按 [运行说明](../README.md) 初始化并启动，学生 A 登录，选择明日 09:00—10:00 查询，选择 A01 创建预约。本人列表应有一条待签到记录，规则 v1，北京时间正确。
2. 刷新页面、退出重登，再使用相同数据库和密钥重启服务，预约仍存在。
3. 学生 B 登录，列表无 A 的记录；访问或取消 A 的预约均 404。同一时段查不到 A01；用同座位创建会返回 409。
4. A 取消，显示已取消；重复请求取消不新增审计。B 重新查询并预约原座位原时段成功。
5. 使用自动化测试验证相邻区间、边界和两个独立连接同时争抢，不靠人工点击证明并发。

## 自动化验证

在 alpha 下安装 requirements-dev.txt；Node 安装根 package.json 的 Playwright 依赖。选择实际安装的浏览器：Windows 默认 msedge，macOS 可设 STUDYSEAT_BROWSER_CHANNEL=chrome。运行 `python scripts/verify_phase2.py`。支持 STUDYSEAT_NODE、NODE_PATH 和 STUDYSEAT_EVIDENCE_DIR。此脚本执行 pytest、Ruff、JS 语法、原型单测、真实进程重启、五组 Alpha 浏览器（含初始化与列表乱序回归）和临时导出副本中的原型浏览器。所有服务仅绑定 127.0.0.1；结束清理临时服务及数据库，不启动长期服务。

独立运行：`python -m pytest -q --junitxml=evidence/phase2/pytest.xml`、`python -m ruff check .`、`python -m ruff format --check .`、`STUDYSEAT_EVIDENCE_DIR=evidence/phase2/restart python scripts/process_smoke.py`。根目录可运行 `node --test tests/*.test.cjs`。浏览器可针对独立测试库服务分别执行 alpha/tests/browser.cjs、account-switch.cjs、reservations-browser.cjs；不要指向日常数据库。

并发复现：`python -m pytest -q tests/test_reservations.py -k independent_connections`。每个用例使用文件数据库、两个独立请求连接和 Barrier 同时进入 BEGIN IMMEDIATE：同座位异学生、同学生异座位、同键同载荷、同键异载荷、重复取消。断言事务数、不同连接、响应状态、唯一预约和唯一审计。另验证持锁期间禁用资源后，等待写入者取得锁时重新校验并拒绝。

## 最终实测结果

2026-11-23 北京时间 20:27 完成最终整套复跑，验证器成功结束。完整结果和执行文件 SHA-256 见 [verification.json](../evidence/phase2/verification.json)。全部测试使用独立数据库；没有跳过项，也没有将失败尝试计为通过。

| 检查及命令 | 实际结果 | 证据 |
| --- | --- | --- |
| alpha：python -m pytest -q -rP --junitxml=evidence/phase2/pytest.xml | 89 passed，0 failed，0 skipped；含阶段一 34 项与本轮 55 项 | [输出及并发响应](../evidence/phase2/pytest.txt)、[JUnit](../evidence/phase2/pytest.xml) |
| alpha：python -m ruff check . | All checks passed | [lint](../evidence/phase2/ruff-check.txt) |
| alpha：python -m ruff format --check . | 20 files already formatted | [format](../evidence/phase2/ruff-format.txt) |
| 根目录：node --check alpha/studyseat/static/app.js | exit 0 | [syntax](../evidence/phase2/js-syntax.txt) |
| 根目录：node --test tests/*.test.cjs | 70 passed，0 failed，0 skipped | [原型单测](../evidence/phase2/prototype-tests.txt) |
| alpha：python scripts/process_smoke.py | 两个不同 PID、同库重启恢复预约与会话、重登恢复、重放、取消释放和唯一审计均通过 | [重启报告](../evidence/phase2/restart/process-smoke.json) |
| 根目录：node alpha/tests/browser.cjs | Chrome，11 检查点通过 | [基础浏览器](../evidence/phase2/browser/browser.json) |
| 根目录：node alpha/tests/account-switch.cjs | Chrome，6 个失败/延迟/CSRF 场景通过 | [账号切换](../evidence/phase2/account-switch/results.json) |
| 根目录：node alpha/tests/reservations-browser.cjs | Chrome，6 组预约、隔离、回执丢失重试及旧响应场景通过 | [预约浏览器](../evidence/phase2/reservations-browser/results.json) |
| 临时导出副本：node tests/browser.cjs | 原型六个流程通过，0 page errors；仅验证既有模拟原型 | [原型浏览器](../evidence/phase2/prototype-browser/results.json) |

浏览器命令由验证器注入每次独立服务的 STUDYSEAT_TEST_URL、独立证据目录和 STUDYSEAT_BROWSER_CHANNEL=chrome。完整执行命令为 `NODE_PATH=<bundled node_modules> STUDYSEAT_NODE=<bundled node> STUDYSEAT_BROWSER_CHANNEL=chrome /tmp/studyseat-phase2-venv/bin/python alpha/scripts/verify_phase2.py`（根目录）。bundled 路径从本机依赖加载器获取；一般安装使用系统 Node 与根 Playwright 依赖即可。

五类真实连接竞争结果：同座位 [201,409]、同学生跨座位 [201,409]、同键同载荷 [200,201]、同键异载荷 [201,409]、重复取消 [200,200]。每类均观察到两个不同 SQLite 连接和两个 BEGIN IMMEDIATE；仅一条预约、一条创建审计，重复取消仅一条取消审计。详见 [并发明细](../evidence/phase2/concurrency.json)。

浏览器预约用例使用 America/Los_Angeles 设备时区，确认提交时间仍明确带 +08:00；模拟真实提交成功后丢弃回执，使用相同幂等键重试返回原预约；A 取消后 B 可预约原座位原时段。另覆盖 A 列表延迟后切 B、查询条件改变后旧余量延迟、列表 503 后刷新恢复与管理员隐藏学生入口。桌面和 390px 移动端截图已人工检查，无横向溢出：[桌面](../evidence/phase2/reservations-browser/reservation-desktop.png)、[移动端](../evidence/phase2/reservations-browser/reservation-mobile.png)。

实际环境：macOS 27.0.1 arm64、Python 3.13.15、SQLite 3.50.4、Flask 3.1.3、Werkzeug 3.1.9、pytest 8.3.5、Ruff 0.17.6、Node 24.22.3、Playwright 1.62.1、Chrome 156.0.8078.48、tzdata 2025.2。本轮没有执行 Windows/Edge 验证，不将历史 Edge 结果冒充本轮结果。

开发中曾出现三项失败：重新登录测试误复用失效 Cookie（修正测试使用新会话）；浏览器误以默认房间为 A101（改为显式选房，初次失败归档在 [attempts](../evidence/phase2/attempts/)）；极端 9999 年时区转换溢出（修复为 400，并加入回归）。最终结果来自上述修正后重新完整执行的测试。取消契约复核遵循原型仅 PENDING_CHECKIN 的状态约束，没有额外增加开始前截止限制。

证据位于 [阶段二证据目录](../evidence/phase2/)。源码哈希已核对到最终提交内容；所有本轮测试服务均在结束后关闭。

## 范围与剩余事项

没有实现签到、暂离、超时任务、管理规则写入或资源关闭接口。遗留未签到记录不自动迁移状态，其原始区间结束后不阻塞未来时段。原型既有模拟状态操作仍仅供原型演示，不等于 Alpha 实现。

提前 7 天采用北京时间日历日期边界，取消采用待签到状态口径，均已写明并测试；正式制度仍需团队确认。非作者审查、团队验收及后续阶段开发待执行。当前为本地课程验收版本，生产部署工作不在此次范围。

## P2 独立审查前端初始化修复

审查基线 fd6027e44e7587d7564245e26c4bd0b17b7e6114，修复前检查分支 codex/phase2-reservations，工作区干净，没有后续修复。新增浏览器用例先在原 app.js 上复现：登录时暂停 GET /rooms 的真实 200 响应，在已显示表单中修改开始和结束时间，释放后房间选项为 0，状态提示为空。断言期望 4 实得 0；[修复前结果](../evidence/initialization-review/pre-fix/initialization-browser/failure.json) 与截图保留，未计为通过。

原因是时间/房间 input 和初始化共用全局 generation。修复将全局代次限定为身份切换，新增座位查询代次，条件编辑只使旧余量响应失效。API 在处理错误、CSRF 和返回数据之前同时检查身份与查询有效性。旧账号记录、审计、预约和会话响应继续由身份代次隔离。按钮使用每次操作独立标识，避免旧查询 finally 启用新查询占用的按钮；保留同载荷幂等重试、查询加载与错误反馈。

查询控件置于初始 disabled 的 fieldset 中，房间、规则和用户数据成功加载后才启用。初始化失败显示服务端错误与“重新加载工作台”入口，重试完整初始化；“刷新预约”仍只刷新本人列表。未更改接口、规则或数据库。

新增 alpha/tests/initialization-browser.cjs 并接入完整验证器：A 暂缓真实房间响应，尝试编辑时间（禁用时检查控件并注入 input 验证独立失效范围），释放后初始化、查询、真实创建与取消通过；B 两种新旧响应交付顺序，旧余量不覆盖新条件，旧操作清理不启用仍在加载的新按钮，旧查询读取失败也不覆盖新提示；C 预约列表加载期间编辑查询条件，列表仍完成；E 房间 503 的明确错误与重新加载恢复。所有延迟使用受控 Promise、真实 route.fetch/fulfill 和 JSON 消费后的下一任务完成信号，不用固定 sleep。既有账号切换、旧响应、CSRF、预约及原型回归纳入完整验证。

本轮证据单独存放于 [initialization-review](../evidence/initialization-review/)，历史 phase2 报告保持原样。最终验证于 2026-11-23 北京时间 21:18 完成，完整验证器 exit 0。实际执行命令（仓库根目录）：

```bash
NODE_PATH=/Users/zhouyiheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
STUDYSEAT_NODE=/Users/zhouyiheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
STUDYSEAT_BROWSER_CHANNEL=chrome \
STUDYSEAT_EVIDENCE_DIR=alpha/evidence/initialization-review/final \
/tmp/studyseat-phase2-venv/bin/python alpha/scripts/verify_phase2.py
```

| 本轮检查 | 实际结果 | 证据 |
| --- | --- | --- |
| pytest（完整后端） | 89 passed，0 failed/errors/skipped；本次新增覆盖位于浏览器，不虚增后端数量 | [pytest](../evidence/initialization-review/final/pytest.txt)、[JUnit](../evidence/initialization-review/final/pytest.xml) |
| Ruff lint、format | 通过；20 files already formatted | [lint](../evidence/initialization-review/final/ruff-check.txt)、[format](../evidence/initialization-review/final/ruff-format.txt) |
| JS 语法、原型单测 | 通过；原型 70 passed、0 failed/skipped | [syntax](../evidence/initialization-review/final/js-syntax.txt)、[单测](../evidence/initialization-review/final/prototype-tests.txt) |
| 真实服务双进程重启 | 预约、会话、幂等、重复取消与释放恢复通过 | [重启](../evidence/initialization-review/final/restart/process-smoke.json) |
| 既有 Alpha 浏览器 | 正常流程 11 检查点、账号切换 6 场景、预约 6 组检查均通过 | [基础](../evidence/initialization-review/final/browser/browser.json)、[账号与 CSRF](../evidence/initialization-review/final/account-switch/results.json)、[预约](../evidence/initialization-review/final/reservations-browser/results.json) |
| 新增初始化浏览器 | 6 场景通过：A、两种 B 顺序、旧读取错误、C、失败重试；0 page errors | [新增回归](../evidence/initialization-review/final/initialization-browser/results.json) |
| 临时导出原型浏览器 | 六个原型流程通过，0 page errors | [原型](../evidence/initialization-review/final/prototype-browser/results.json) |

[完整报告与 25 个执行文件 SHA-256](../evidence/initialization-review/final/verification.json) 已核对最终源码。截图已检查，查询表单初始化完成后正常布局。此前增加双查询交付检查时，测试自身动态注册/清理路由产生 Route is already handled，未计为通过；改用每页固定路由队列后重新完整执行通过。[失败尝试日志](../evidence/initialization-review/attempts/route-conflict.txt) 与 [失败状态](../evidence/initialization-review/attempts/route-conflict.json) 另行保留。

本轮实际环境为 macOS 27.0.1 arm64、Python 3.13.15、SQLite 3.50.4、Flask 3.1.3、pytest 8.3.5、Ruff 0.17.6、Node 24.22.3、Playwright 1.62.1、Chrome 156.0.8078.48。Windows/Edge 本轮未执行；团队复核修复及正式验收仍待完成。范围限制仍为本地课程验收：未增加签到、超时或管理写操作，未推送、合并或发布。

## P2 预约列表乱序修复

2026-11-24，基于独立复查基线 80690699eabf2b75fe087fd6a72e309236dc5dea。开始时分支 codex/phase2-reservations、HEAD 与基线一致，工作区干净，无后续修复。首先新增真实浏览器回归，在未修改的 app.js 上复现：暂停创建前的真实空列表，创建后已显示新预约，释放旧列表后页面变为“还没有预约”，状态仍为“预约已保存”，服务端仍有一条 PENDING_CHECKIN。断言期望 1 项实得 0；[修复前失败及服务端记录](../evidence/reservation-list-review/pre-fix/reservation-list-browser/failure.json) 和截图保留，不计入通过。

原因为预约列表只有身份代次，没有同一身份内的读取顺序保护。app.js 新增独立 reservationListGeneration；初始化清理、新读取、创建或取消成功均使之前列表读取失效。读取在渲染、错误和反馈之前复核身份与列表版本，网络或 JSON 读取异常也经过相同校验。创建/取消后的完成提示与列表版本绑定；各列表读取独立持有刷新按钮，旧 finally 不能启用新读取占用的按钮。手动刷新保留已确认记录与取消入口，在状态区显示加载反馈。

原有身份与座位查询代次保留，时间/房间 input 不改变列表版本。初始化的 Promise.all 仅忽略明确被更新读取取代的 StaleResponse，仍传播真实错误，且整体继续校验身份；避免旧列表读取失效时再次中断房间和规则初始化。没有修改后端权限、事务、幂等或接口契约。

新增 alpha/tests/reservation-list-browser.cjs 并接入完整验证器。7 个场景对应：A 创建前旧空列表晚到；B/D 取消前后真实列表按新先到、旧先到两种顺序交付；C 旧 503、旧网络拒绝晚于最新结果，且最新读取仍在进行时不能误启用按钮；当前读取失败明确报错且可重试；旧初始化列表被新工作台读取取代，仍可继续查询。仅指定 GET /reservations 被暂缓或模拟交付失败；写入、列表快照、状态和会话均使用真实服务。使用每页固定路由队列、受控 Promise 与 JSON 消费/网络拒绝后下一任务的完成信号，不靠固定 sleep。通过独立 HTTP 读取对照服务端状态，避免只检查 DOM。

本轮证据写入 [reservation-list-review](../evidence/reservation-list-review/)，历史 phase2 与 initialization-review 均保持不变。最终完整验证于北京时间 2026-11-24 08:53 完成，验证器 exit 0。修复前 A 用例失败、修复后定向及完整验证中的新增 7 场景均通过。实际命令（项目根目录）：

```bash
NODE_PATH=/Users/zhouyiheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
STUDYSEAT_NODE=/Users/zhouyiheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
STUDYSEAT_BROWSER_CHANNEL=chrome \
STUDYSEAT_EVIDENCE_DIR=alpha/evidence/reservation-list-review/final \
/tmp/studyseat-phase2-venv/bin/python alpha/scripts/verify_phase2.py
```

| 本轮验证 | 实际结果 | 证据 |
| --- | --- | --- |
| pytest 完整后端 | 89 passed、0 failures/errors/skipped；本次新增覆盖为浏览器用例 | [输出](../evidence/reservation-list-review/final/pytest.txt)、[JUnit](../evidence/reservation-list-review/final/pytest.xml) |
| Ruff lint、格式、JS 语法 | 全部通过；20 files already formatted | [lint](../evidence/reservation-list-review/final/ruff-check.txt)、[format](../evidence/reservation-list-review/final/ruff-format.txt)、[syntax](../evidence/reservation-list-review/final/js-syntax.txt) |
| 原型单测 | 70 passed、0 failures/skipped | [原型单测](../evidence/reservation-list-review/final/prototype-tests.txt) |
| 真实双进程重启 | 会话、预约、幂等、取消与释放恢复通过 | [重启](../evidence/reservation-list-review/final/restart/process-smoke.json) |
| 既有 Alpha 浏览器 | 正常流程 11 检查点、账号切换 6、预约 6、初始化 6 场景均通过 | [基础](../evidence/reservation-list-review/final/browser/browser.json)、[账号与 CSRF](../evidence/reservation-list-review/final/account-switch/results.json)、[预约](../evidence/reservation-list-review/final/reservations-browser/results.json)、[初始化](../evidence/reservation-list-review/final/initialization-browser/results.json) |
| 新增列表乱序浏览器 | 7 场景通过，含真实服务端状态对照；0 page errors | [列表结果及证明](../evidence/reservation-list-review/final/reservation-list-browser/results.json) |
| 临时导出原型浏览器 | 六个流程通过，0 page errors | [原型浏览器](../evidence/reservation-list-review/final/prototype-browser/results.json) |

[完整验证及 26 个执行文件 SHA-256](../evidence/reservation-list-review/final/verification.json) 已与最终源码核对。新增场景 A 截图已检查：旧空列表交付后，新预约和“预约已保存”提示一致存在。修复前失败没有计为通过，未覆盖任何历史报告。

实际环境：macOS 27.0.1 arm64、Python 3.13.15、SQLite 3.50.4、Flask 3.1.3、pytest 8.3.5、Ruff 0.17.6、Node 24.22.3、Playwright 1.62.1、Chrome 156.0.8078.48。本次仅本地修复和提交，不推送、不合并、不发布。Windows/Edge 本轮未验证；团队复核及正式验收仍待完成。
