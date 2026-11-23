# PR 2 账号切换数据残留修复

执行日期：2026 年 11 月 22 日。执行前已读取仓库及父目录适用指令，未发现 AGENTS.md。Git 根目录为交付仓库 studyseat-alpha，应用位于根目录 alpha；初始工作区干净。已通过 GitHub CLI 核对 PR #2 最新 HEAD 为 `aea6b9d5d367304b01a22772696ea07f7e48f5cb`，与本地一致，PR 开放且非 Draft。本次从该提交建立隔离分支 `fix/pr2-account-switch`，未修改他人的文件、日常数据库或现有密钥。

## 缺陷与修复

当前 HEAD 中仍存在前端生命周期问题。修改前新增 T1 实际失败：退出后 welcome 节点仍保留上一个学生的身份。代码中 notes、events 未清理，管理区域显隐又晚于资源加载，因此接口失败会让上个账号的内容重新出现。服务端权限没有被绕过，本次未修改或放宽后端权限。

- 退出或开始身份切换时清空身份、验证文本列表、审计、资源与规则，以及密码和验证文本草稿；成功退出后也清空账号输入。
- 获取当前身份后先清理不同身份状态，并立即按当前角色设置管理区域显隐，再加载数据。
- 每次页面操作使用新的请求代次。API 在处理错误、更新 CSRF 和返回数据之前核对代次；旧响应、旧错误和旧操作成功提示都不能更新新页面。
- 刷新前清理已加载的数据，加载失败保留明确错误及未加载状态；按钮清理由操作归属控制，旧操作不能启用新操作占用的按钮。
- 登录与退出写请求期间暂时隐藏登录入口，避免认证写请求重叠造成浏览器 Set-Cookie 竞争；已完成登录后仍可在数据加载中退出。
- 所有私有文本继续通过 textContent 展示；服务端角色读取、CSRF、按本人过滤与退出后旧会话失效保持不变。

## 新增浏览器覆盖

脚本为 `alpha/tests/account-switch.cjs`。使用真实 Flask、真实 Cookie 与数据库，仅对指定读取响应模拟 503 或延迟交付。

| 要求 | 实际用例 | 结果 |
| --- | --- | --- |
| T1 | 学生记录和管理员审计加载后退出，检查 DOM、私有表单及管理区域清理 | 通过 |
| T2 | A 创建唯一文本后切换 B，B 的记录接口 503；解除拦截后确认 B 列表无 A 文本、A 详情 404 | 通过 |
| T3 | 管理员切换学生，规则接口 503；管理区域隐藏、审计清空，真实管理 API 403 | 通过 |
| T4 | 旧 A 记录已生成响应后暂停交付，切换 B 再释放，身份与记录不变 | 通过 |
| T4 | 旧管理员审计已生成响应后暂停交付，切换 B 再释放，管理区域和审计仍为空 | 通过 |
| T4 与 CSRF | 延迟旧 /auth/session 响应，切换 B 再释放；B 的身份不变且仍可真实保存记录，证明当前 CSRF 未被旧响应覆盖 | 通过 |
| T5 | 原 browser.cjs 的错误密码、正确登录、四间资源、保存刷新、退出、隔离、管理日志与页面异常检查 | 11 个检查点通过 |

延迟用例使用 route.fetch 先取得真实响应，随后通过可控 Promise 释放。测试在 JSON 消费后的下一任务发出完成信号，再检查 DOM，避免以固定 sleep 猜测旧响应是否处理完毕。测试允许独立测试数据库中已有合成记录，通过唯一标记和当前页面快照比较隔离结果；正常主流程另外使用干净数据库。

## 命令与实际验证

以下 Python 指当前工作区已安装依赖的虚拟环境解释器，命令在 alpha 下执行；Node 浏览器命令在仓库根目录执行。Playwright 来自本机 bundled runtime 的 NODE_PATH。

```text
python -m pytest -q --junitxml=evidence/pytest-account-switch.xml
python -m ruff check .
python -m ruff format --check .
STUDYSEAT_EVIDENCE_DIR=<独立证据目录> python scripts/process_smoke.py
STUDYSEAT_TEST_URL=http://127.0.0.1:5059 node alpha/tests/account-switch.cjs
STUDYSEAT_TEST_URL=http://127.0.0.1:5070 STUDYSEAT_EVIDENCE_DIR=<独立证据目录> node alpha/tests/browser.cjs
node --test tests/*.test.cjs
```

Windows 环境变量使用 PowerShell 的 `$env:变量名` 设置。正常浏览器流程使用全新隔离文件数据库，新增场景另在此干净环境复跑通过。5060 端口最初被 Chromium 的安全端口规则拒绝，改为 5070 后通过，不把被拒绝的尝试记为通过。

| 检查 | 实测结果 | 证据 |
| --- | --- | --- |
| 后端 pytest | 34 passed | evidence/pytest-account-switch.xml |
| 新增浏览器 | 6 个场景通过，干净环境复跑也通过 | evidence/account-switch/results.json 及对应 PNG |
| 原正常浏览器 | 11 个检查点通过 | evidence/account-switch/normal-browser/browser.json |
| 真实 HTTP 双进程重启 | passed | evidence/account-switch/restart/process-smoke.json |
| Ruff lint 与格式 | 通过 | 本次命令执行结果 |
| JS 语法 | node --check 通过 | app.js、account-switch.cjs |
| 原型当前 Windows 工作区 | 69 项中 67 通过，2 项失败 | evidence/account-switch/prototype-worktree.txt |
| 精确 HEAD 的原始 LF 副本 | 69 项中 68 通过，1 项失败 | evidence/account-switch/prototype-canonical-baseline.txt |

环境：Windows，Python 3.10.0、SQLite 3.35.5、Flask 3.1.3、pytest 8.3.5、Ruff 0.17.6、Node 24.22.3、Playwright 1.62.1、实际浏览器 Edge 158.0.4370.33。本次没有将其他浏览器结果记为 Edge，也没有跳过失败用例。

## 原型回归限制

当前工作区开启 core.autocrlf，CSS 文件原始 Git blob 的摘要前缀为 6d0b4bb021ee，工作区 CRLF 内容为 5bc14f69f7eb。使用 `git -c core.autocrlf=false archive` 导出精确 PR 基线后，资源哈希用例通过，证明其中一项失败与换行转换相关。普通 archive 也会应用换行转换，因此初次归档验证不能当作原始 LF 基线，报告另行保留在 prototype-baseline-lf.txt。

原始 LF 基线剩余失败为 Windows 导出后重新生成 prototype-release.json 的逐字节比较，失败位置为 tests/submission.test.cjs 第 21 行；修复前精确提交中同样存在。本次没有修改原型生成或导出工具，也未把此失败记为通过。初次原正常流程误用了 B 已写入合成数据的测试库，改为另一干净数据库后原有 11 项检查全部通过。

## 交付结论

本次 R1 前端跨账号残留及旧响应回写问题已修复，新增失败、延迟与 CSRF 场景通过，没有发现该缺陷仍阻碍第一阶段功能验收。原型 Windows 打包回归仍有上述既有环境限制，需要另行处理；因此不宣称全仓检查全绿。独立成员批准、规则确认和团队正式验收仍待团队执行，本次不合并或代为批准 PR。

本次仅处理持久化验证文本的前端生命周期，不实现预约、签到、超时或资源关闭。修复版本以包含本报告的 Git 提交为准；完整提交 SHA 同步到交付说明和 PR 的新增提交中。
