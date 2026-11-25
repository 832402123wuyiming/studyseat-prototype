# 第三阶段 使用与管理联动

依据《StudySeat_代码规范与冲刺计划》的 11 月 25—26 日安排，实现学生使用状态、超时释放与管理端共享数据。开发基线是已合并阶段二 PR #3 的 main：`07e6d64df6b6a3d668147b7b625d05836f351f22`。独立目录 `studyseat-phase3`，分支 `codex/phase3-attendance-admin`；原型和阶段二目录的既有文件不改动。

## 已实现行为

学生页面通过真实 API 完成签到、暂离、返回、结束；保留原查询、预约、取消。所有状态判断在服务端，角色、本人归属、Cookie 会话和 CSRF 校验继续有效。六状态模型、不可复活终态、旧规则快照、UTC 持久化及北京时间显示沿用既有约定。

签到窗口包含前后两个端点；暂离截止严格超时才过期。自然结束、未签到过期、暂离过期按先发生的有效边界处理，补处理晚到不改变归因。超时的 ended_at 为应生效时间，审计为实际处理时间。预约剩余占用由状态与区间直接计算，无额外需要同步的库存。

独立 `expire-reservations` CLI 支持单次及轮询工作进程，服务停止时仍可执行；两进程重复处理只产生一次状态变化和审计。相关读取与创建也执行补处理。请求等待数据库写锁后才取服务端时间，签到或取消等待期间越过截止则拒绝请求，并保留超时结果。

所有新写接口使用持久化操作键，绑定执行者、操作与载荷。旧暂离或返回请求晚到，不改变新轮次状态；重放保留首次时间和单条审计。预约变化、操作键和审计共同提交，审计失败则回滚。

管理端读取与学生端同一份预约、规则与资源，可保存完整规则新版本、调整每日开放分钟，预览并确认立即关闭资源、重新开放和查看关联日志。规则保存使用版本前提，开放时间修改拒绝覆盖不了有效预约的配置；已有预约规则快照保持不变。管理日志展示中文操作与原因，开放时间使用北京时间时分输入。前端保留未保存规则退出提醒，验证工具重新加载也须先确认放弃草稿；保存期间新编辑的草稿不会被迟到回执清除。

关闭预览显示受影响学生、座位、时段和预约编号，并明确列出阻断记录；预览为纯读，无预约、审计或预览行写入。签名摘要绑定管理员、范围、原因和影响状态，300 秒有效。确认在写锁内重新读取，变化要求重新预览；使用中或暂离中的预约阻断关闭。关闭仅取消受影响的待签到预约，整间与单座均可操作；关闭、取消和审计失败整体回滚。重新开放只修改关闭记录，绝不恢复已取消预约。

前端继续保留身份、座位查询和预约列表版本保护；新增管理读取版本及预览版本，旧管理结果或旧错误不能覆盖关闭后的新状态与反馈。退出清空管理列表、规则表单和预览。

## 数据升级与启动

数据库从 v1 原子升级到 v2，保留 v1 表声明和原始记录；新增操作回执表及审计详情字段。请先停止服务并备份原数据库，再按 [运行说明](../README.md) 使用原数据库路径和稳定密钥执行 `flask --app studyseat init-db`，不要删库。升级失败回滚，重复执行不重复迁移。部署回退必须恢复旧库备份，不能让旧代码直接连接 v2。

服务与独立任务分别启动，后者使用相同配置执行 `flask --app studyseat expire-reservations --watch --interval 30`。读取补处理作为恢复措施，独立任务才承担无人访问时的周期处理。没有把页面倒计时当作后台任务。

## 验收主线

1. 学生 A 创建开始在未来 10 分钟内的预约，页面签到、暂离；刷新与使用原库原密钥重启后仍为暂离中，返回再结束。重复请求不更改首次有效时间。
2. 学生 B 无法看到 A 的预约；四种状态操作他人记录均 404，管理接口为 403。退出清空私有页面数据。
3. 验证签到前 10 分钟、开始后 15 分钟及后一微秒；暂离截止等于当前时刻与后一微秒；预约结束、暂离与结束同刻及延迟补处理。
4. 管理员看到 A 的同一预约，保存规则 v2；新预约读取新规则，旧预约继续按旧快照签到与暂离。未保存退出有确认，陈旧版本提交拒绝。
5. B 创建未来预约，管理员预览不写库，确认关闭后 B 刷新见取消；再次预约该座位失败。重新开放后可创建新预约，旧预约仍取消。
6. 预览后新增预约、取消、签到或资源状态改变，确认均拒绝旧预览。使用中或暂离中预约即使重新预览也阻断关闭。
7. 服务停止后执行超时 CLI，包括两独立进程竞争同一到期记录；只记一条超时审计，剩余时段可再次预约。

## 实测结果和证据

完整自动化命令：项目根目录设置 Node/Playwright 路径和 `STUDYSEAT_BROWSER_CHANNEL=chrome` 后运行 `python alpha/scripts/verify_phase3.py`。使用独立数据库和临时服务，不指向日常实例；每组浏览器使用新数据库，原型回归在临时导出副本运行。

最终结果以 [verification.json](../evidence/phase3/verification.json) 为准。后端涵盖旧阶段与新增状态、管理、迁移及真实独立连接竞争；浏览器涵盖原有五组及阶段三跨端操作、迟到管理列表、迟到错误、保存中的新草稿与移动端布局；独立进程检查覆盖真实 v1 数据升级、会话与暂离恢复及两超时进程。最终完整运行于北京时间 2026-11-25 21:02 结束，验证器 exit 0，无失败或跳过。执行文件 35 项 SHA-256 已逐一核对，与交付源码一致。

| 本轮实际验证 | 结果 | 证据 |
| --- | --- | --- |
| pytest 完整后端 | 149 passed，含原阶段 89 项与新增 60 项 | [输出](../evidence/phase3/pytest.txt)、[JUnit](../evidence/phase3/pytest.xml) |
| Ruff 检查及格式 | 全部通过，28 个 Python 文件格式合规 | [检查](../evidence/phase3/ruff-check.txt)、[格式](../evidence/phase3/ruff-format.txt) |
| JavaScript 语法与原型单测 | 语法通过，原型 70 passed | [单测](../evidence/phase3/prototype-tests.txt) |
| 原五组 Alpha 浏览器 | 基础 11 检查点、账号 6 场景、预约 6 组、初始化 6 场景、列表 7 场景均通过 | [基础](../evidence/phase3/browser/browser.json)、[账号](../evidence/phase3/account-switch/results.json)、[预约](../evidence/phase3/reservations-browser/results.json)、[初始化](../evidence/phase3/initialization-browser/results.json)、[列表](../evidence/phase3/reservation-list-browser/results.json) |
| 阶段三浏览器 | 12 项跨端与延迟响应检查通过，无 page errors | [结果](../evidence/phase3/phase3-browser/results.json) |
| 真实进程与迁移 | v1 真实预约及审计升级保留，双服务进程重启后会话及暂离恢复，两独立超时进程只处理一次 | [阶段三进程](../evidence/phase3/restart/phase3-process-smoke.json)、[既有持久化](../evidence/phase3/restart/process-smoke.json) |
| 临时导出原型浏览器 | 六流程全部通过 | [原型结果](../evidence/phase3/prototype-browser/results.json) |

11 组可输出的独立连接竞争结果另存 [并发明细](../evidence/phase3/concurrency.json)，其原始记录与 SHA-256 来自本轮 pytest 输出。包含既有 5 组、重复签到/结束/关闭、签到争抢关闭、预约争抢关闭及重复超时处理 6 组；其他时间边界、锁等待与迁移竞争仍由后端断言覆盖，没有将线程模拟当成前端点击证明。

本机环境为 macOS 27.2.1 arm64、Python 3.13.15、SQLite 3.50.4、Flask 3.1.3、Werkzeug 3.1.9、pytest 8.3.5、Ruff 0.17.6、Chrome 156.0.8078.48；浏览器通过 Playwright 运行，Windows/Edge 未执行。

已人工查看 [学生暂离桌面](../evidence/phase3/phase3-browser/student-leave-desktop.png)、[管理员影响预览](../evidence/phase3/phase3-browser/admin-preview-desktop.png)、[关闭后管理页面](../evidence/phase3/phase3-browser/admin-closed-desktop.png)、[学生移动端](../evidence/phase3/phase3-browser/student-mobile.png)、[管理员移动端](../evidence/phase3/phase3-browser/admin-mobile.png)。没有横向溢出、遮挡或缺字；学生最终截图先刷新并与服务端状态对照，不以管理操作前的旧页面充当最终证据。

开发过程曾补齐旧测试直接造出的不完整暂离记录，并按新增超时语义调整“过期后仍能取消”的阶段二断言；不通过删除旧覆盖来迁就实现。首次完整验证发现报告生成顺序导致文档导出检查 69 通过 / 1 失败，修正为运行中、失败、通过状态并保留失败证据。展示检查后将日志改为中文、开放时间改为时分输入，并补充预览清单、草稿保护和刷新后截图；相应浏览器断言同步使用实际中文文案。调整期间旧账号切换断言仍等待英文 LOGIN 导致超时，已记录失败并修正。第二次完整验证的旧预约浏览器用例用泛化按钮选择器遇到新增签到按钮，改为明确选择“取消预约”，保留原流程断言；该失败未计为通过。首次受限环境启动本机监听被拒，获工具许可后使用仅 127.0.0.1 的独立测试服务执行。早期失败不计为最终通过。

## 任务与验证对应

| 验收任务 | 主要自动化覆盖 |
| --- | --- |
| 签到窗口与服务端时钟 | checkin_both_endpoints、waiting_student_writer、checkin_and_timeout_race |
| 暂离返回与多轮幂等 | leave_return_multiple_cycles、leave_deadline_equality、operation_keys |
| 超时与占用释放 | timeout_cli_repetition、timeout_releases_remaining_seat、timeout_audit_failure |
| 共享规则与旧快照 | rules_shared_snapshots、corrupt_current_rules |
| 关闭预览、复核与重新开放 | preview_read_only、stale_closure_preview、active_use_blocks_close、room_closure |
| 事务及真实并发 | lifecycle_audit_failure、closure_failure、independent_phase3_writers |
| 身份与归属权限 | transition_access_csrf、admin_writes_require_role；既有账号切换浏览器继续运行 |
| 旧库升级及持久化 | migration_v1、migration_error、concurrent_initializers；真实进程升级/重启脚本 |
| 两端页面与延迟响应 | 阶段三浏览器 12 项检查；原五组 Alpha 浏览器与原型六流程 |

测试函数名为 [test_phase3.py](../tests/test_phase3.py) 中对应名称的识别片段，完整函数名均以 `test_` 开头。需求对应依据附件的阶段任务和六状态约定，不编造缺少原文的 SRS 验收编号。

## 范围与团队待办

本轮实际开发为 AI 辅助，不追溯归属给计划中的具体同学。功能和自动化证据完成后，仍需非作者审查和团队正式验收才能按原计划标记已验收；未自动建立远程 Issue、推送、创建 PR、合并或发布。

规则值为项目演示参数，学校制度仍待确认。关闭遇到使用中/暂离中时阻断并要求现场处理，沿用当前原型，与旧 SRS 差异仍需团队确认。关闭仅支持立即生效直到重新开放，不提供未来定时关闭。页面签到只记录用户操作，不能证明实际到场。没有真实消息推送、门禁或校园统一认证；审计是站内记录，不能写成通知已送达。

本机验证为 macOS/Chrome；Windows/Edge 尚未执行。生产 HTTPS/WSGI、登录限速及生产部署仍不在此次课程本地验收范围。下一阶段集中进行团队复核、跨平台回归、缺陷修复和交付整理。
