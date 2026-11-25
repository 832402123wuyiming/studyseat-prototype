# 11 月 25—26 日阶段三记录

实际开发与验证日期：2026-11-25。目标：在阶段二预约主流程之上打通签到、暂离、返回、结束、超时释放、管理员规则版本与资源关闭。实际工作为本次 AI 辅助开发，不将工作量追溯归属到附件计划中的成员；非作者审查和团队正式验收仍待执行。

## 工作环境与基线

- 基线：GitHub `main` 的 `07e6d64`（阶段二 PR #3 已合并）。
- 本地 Git 根目录：`studyseat/`，导入基线提交 `f36736d`。
- 运行环境：Windows 11（10.0.26300）、Python 3.13.3、SQLite 3.49.1、Flask 3.1.3、Werkzeug 3.1.9、pytest 8.3.5、Ruff 0.17.6、Node.js 24.19.0、Playwright 1.62.1、Microsoft Edge 158.0.4370.33。
- 依赖从 `requirements-dev.txt` 安装；本轮使用清华镜像完成安装。演示与测试数据库均为独立文件，未改动 `alpha/instance` 日常数据。

## 已实现内容

新增 `studyseat/attendance.py` 与 `studyseat/admin.py`，沿用现有 `BEGIN IMMEDIATE` 写事务、`ApiError` 和审计模式；`api.py` 增加学生状态操作与管理接口，前端接入对应按钮、规则表单和关闭预览/确认/重开。

### 签到、暂离、返回与结束

- 签到仅接受 PENDING_CHECKIN，窗口为开始前 10 分钟至开始后 15 分钟的闭区间；恰好到截止时刻仍允许签到，严格超过才超时。
- 暂离仅接受 IN_USE，`leave_deadline` 为当前服务端时间加规则快照中的暂离上限；返回恰好到截止时刻仍允许。
- 结束接受 IN_USE 或 ON_LEAVE，首次 `ended_at` 不被重复请求覆盖。
- 每个操作先校验归属，他人或不存在均返回 404；学生与管理员角色互斥；所有 POST 校验 CSRF。
- 重复签到、暂离、返回、结束返回当前记录，不重复写审计；终态不能复活。

### 超时释放

`attendance.expire_due` 在列表、详情、余量查询、创建、取消和状态操作前统一执行：

| 当前状态 | 触发条件 | 迁移 | 审计 |
| --- | --- | --- | --- |
| PENDING_CHECKIN | 严格超过签到截止 | EXPIRED | RESERVATION_EXPIRED |
| ON_LEAVE | 严格超过暂离截止，且未到结束时刻 | EXPIRED | RESERVATION_EXPIRED |
| IN_USE / ON_LEAVE | 到达预约结束时刻 | COMPLETED，`ended_at` 取结束时刻 | RESERVATION_AUTO_COMPLETED |

每次迁移带状态条件更新，只有实际更新成功才写一条审计；释放后占用立即从余量查询中消失。该实现不依赖后台常驻任务，代价是读路径也进入写事务，课程演示规模可接受。

### 管理员规则版本

- `POST /admin/rules` 只接受完整五项整数设置，范围：单次最长 15—1440、提前 0—30 天、签到提前 0—120 分钟、签到延后 0—120 分钟、暂离 1—240 分钟。
- 新设置插入新的 `rule_versions` 行并写 RULES_UPDATED 审计；已有预约保留原版本和完整快照，新预约使用最新版本。
- 布尔、小数、字符串、缺失键和越界值均返回 400，不产生新版本。

### 资源关闭与重开

- 预览按服务端当前时间计算生效状态，但不写业务数据；返回影响清单、`cancellable_count`、`blocking_count`、`can_apply` 和 5 分钟 HMAC 签名 `token`。
- 存在 IN_USE 或 ON_LEAVE 预约时 `can_apply=false`，确认关闭返回 409 CLOSURE_BLOCKED，要求结束后重新预览。该口径与旧 SRS TR-10 不同，**待团队确认**。
- 确认关闭在事务内重新执行超时释放、复核资源和未重开关闭，再按范围、原因、预约 ID/状态/时段重算影响；与 `token` 不一致返回 409 PREVIEW_STALE。篡改或过期分别返回 PREVIEW_INVALID / PREVIEW_EXPIRED。
- 关闭只取消 PENDING_CHECKIN 预约，每条写 RESERVATION_CLOSED 审计，并写 RESOURCE_CLOSED；房间关闭阻止该房间新预约，座位关闭只影响该座位。
- 重开只设置 `reopened_at` 并写 RESOURCE_REOPENED，不恢复已取消预约；重复重开保持首次时间，不重复审计。

### 页面

学生端预约条目按状态显示取消/签到/暂离/返回/结束按钮，操作后刷新本人列表并释放对应余量查询；管理员端增加规则表单、关闭范围/目标/原因、预览影响、确认关闭、关闭记录与重开按钮，并保留审计列表。页面没有新增前端时间判断，签到窗口、暂离截止和关闭阻断均由服务端决定。

## 验收步骤

1. 学生 A 创建一条数分钟后开始的预约，在签到窗口内点击“签到”，状态变为使用中；点击“暂离”后显示暂离截止，再点击“返回”恢复使用中。
2. 点击“结束”，状态变为已结束；重复点击不改变首次结束时间。
3. 创建一条不签到预约，超过签到截止后刷新列表，状态变为已超时，该座位此时段重新出现在余量查询中。
4. 管理员保存新规则版本，学生端规则提示更新；既有预约仍显示原规则版本和快照。
5. 管理员预览关闭一个含待签到预约的座位，确认后该预约变为已取消；重开后该记录仍为已取消，其他学生可重新预约。
6. 对含使用中预约的房间预览关闭，应显示阻止关闭且确认按钮不可用；结束该预约后重新预览方可关闭。

## 自动化验证

| 检查及命令 | 实际结果 | 证据 |
| --- | --- | --- |
| `python -m pytest -q --junitxml=evidence/phase3/pytest.xml` | 110 passed，0 failed，0 skipped；含阶段一、二既有 89 项与本轮新增 21 项 | [输出](../evidence/phase3/pytest.txt)、[JUnit](../evidence/phase3/pytest.xml) |
| `python -m ruff check .` | All checks passed | [lint](../evidence/phase3/ruff-check.txt) |
| `python -m ruff format --check .` | 26 files already formatted | [format](../evidence/phase3/ruff-format.txt) |
| `node --check studyseat/static/app.js`、`node --check tests/phase3-browser.cjs` | exit 0 | [syntax](../evidence/phase3/js-syntax.txt) |
| Playwright + Edge 页面冒烟（根目录 `node alpha/tests/phase3-browser.cjs`，独立测试库） | 13 项检查通过，0 page errors；含学生暂离/返回、管理员阻止关闭、座位关闭、重开 | [结果](../evidence/phase3/browser/results.json)、[截图](../evidence/phase3/browser/screenshots/) |

后端新增用例覆盖：签到窗口两端与超窗、重复签到、签到超时释放、暂离/返回截止、结束与自动完成、错误归属/角色/CSRF、规则版本与快照、规则校验、关闭预览只读、确认取消、阻断、过期/篡改/失效预览、座位范围、重开不恢复和重复重开。

阶段二原有的“开始两天后仍可取消待签到预约”预期已随超时释放改为 409 + EXPIRED；这是阶段三状态机的有意变更，用例已同步更新并保留其余阶段二断言。

页面冒烟使用独立演示数据库和在本机启动的临时服务（127.0.0.1:5058），未指向日常数据库；截图保留真实中文界面，仅用于本轮验收说明。

## 范围、差异与剩余事项

- 本轮只做本地提交，未推送、未合并、未部署。基线来自上游 `07e6d64`；工作副本包含多次本地提交（服务与测试、页面、文档与证据、悬停修复、浏览器用例），哈希取决于应用到的仓库。推送后需在 GitHub 上补 PR 和非作者审查记录，并以实际提交链接为准。
- 关闭时存在使用中/暂离中预约即拒绝，是 RULES.md 中待团队确认的口径；若团队决定允许强制关闭，需要新增对使用中预约的处理规则、原因记录和测试。
- 超时释放为请求触发的惰性迁移，不是定时任务；长时间无请求时，记录会在下一次读取或写入时才落为终态，但占用判断同样使用该迁移，不会把过期记录当作有效占用。
- 未实现校园统一认证、真实通知、物理门禁、管理统计图表和公网部署；这些不在本轮 Alpha 范围。
- 本轮只在 Windows + Edge 验证，未复跑 macOS/Chrome；历史阶段二证据保持原样。
- 非作者审查、团队正式验收和答辩材料仍待完成。
