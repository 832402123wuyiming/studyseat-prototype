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

在 alpha 下安装 requirements-dev.txt；Node 安装根 package.json 的 Playwright 依赖。选择实际安装的浏览器：Windows 默认 msedge，macOS 可设 STUDYSEAT_BROWSER_CHANNEL=chrome。运行 `python scripts/verify_phase2.py`。支持 STUDYSEAT_NODE、NODE_PATH 和 STUDYSEAT_EVIDENCE_DIR。此脚本执行 pytest、Ruff、JS 语法、原型单测、真实进程重启、三组 Alpha 浏览器和临时导出副本中的原型浏览器。所有服务仅绑定 127.0.0.1；结束清理临时服务及数据库，不启动长期服务。

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
