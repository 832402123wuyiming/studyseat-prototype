# StudySeat Alpha 首阶段

对应八天实施安排第一个日期段 **2026 年 11 月 21—22 日**：规范与接口、数据库、登录和权限基础。实际开发与验证日期为 11 月 22 日。参考原型的蓝白视觉、四间自习室、三个公开测试账号和六状态命名，新增独立的 Flask 工程；`deploy/`、`prototype/` 和 `modao/` 保留原状。

已实现：同源首页与 API、SQLite 文件存储、幂等初始化、密码 scrypt 哈希、服务端会话、登录/退出、CSRF、角色和记录归属校验、共享资源目录与规则读取、管理审计读取。页面提供专用持久化验证文本，可刷新、退出重登或重启服务检查；它不创建预约，也不占座。

## Windows 启动

需要 Python 3.10 或更新版本。打开 PowerShell，进入本文件所在的 `alpha` 目录：

```powershell
./start.ps1 -Python 'C:/你的Python目录/python.exe'
```

如果 Python 已正确配置在 PATH 中，可直接执行 `./start.ps1`。脚本创建 `.venv`、安装运行依赖、初始化数据库并启动 [本机首页](http://127.0.0.1:5000)。如果执行策略阻止脚本，可以在当前进程运行 `Set-ExecutionPolicy -Scope Process Bypass` 后重试，或使用下面的手动方式。

首次安装需要网络。如果默认 PyPI 无法访问，可先创建虚拟环境并执行 `./.venv/Scripts/python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`，再运行启动脚本。

脚本在 `instance/.secret-key` 保存随机本机密钥并通过环境变量注入服务。保留该文件和数据库，重启后会话可继续使用；若已经设置 `STUDYSEAT_SECRET_KEY`，优先使用环境配置。运行数据、密钥和虚拟环境均被 Git 忽略。初始化命令不会清空或重置已有用户、规则和验证记录。

## 手动启动与 Linux macOS

PowerShell 手动方式：

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
$env:STUDYSEAT_SECRET_KEY = '替换为至少32字符的随机密钥并在重启时使用相同值'
./.venv/Scripts/python.exe -m flask --app studyseat init-db --demo
./.venv/Scripts/python.exe -m flask --app studyseat run --host 127.0.0.1 --port 5000
```

Linux/macOS：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export STUDYSEAT_SECRET_KEY='replace-with-a-stable-random-secret-of-32-or-more-characters'
.venv/bin/python -m flask --app studyseat init-db --demo
.venv/bin/python -m flask --app studyseat run --host 127.0.0.1 --port 5000
```

默认数据库为 `alpha/instance/studyseat.sqlite3`。可用 `STUDYSEAT_DATABASE` 指定绝对路径；修改路径前需重新初始化对应文件。`.env.example` 列出环境配置，应用不自动读取 `.env`。HTTPS 环境设 `STUDYSEAT_HTTPS=1`，本地 HTTP 保持为 0。无密钥或密钥少于 32 个字符时服务拒绝启动。

## 公开测试账号

| 身份 | 账号 | 密码 |
| --- | --- | --- |
| 学生 A | 832402116 | 123456 |
| 学生 B | student02 | Study1234 |
| 管理员 | admin01 | Admin1234 |

身份由数据库决定，登录表单不接受角色参数。`--demo` 才会安装公开账号和 4 间房、312 个座位、规则 v1；不带该选项只创建结构。本阶段不提供注册、重置密码或校园认证。

## 验收步骤

1. 访问首页及 `/api/v1/health`，应返回正常服务状态和 UTC 服务时间。
2. 输入错误密码，检查错误提示；用学生 A 登录，查看四间资源和规则 v1。
3. 保存一条验证文本，刷新后仍存在；退出后用学生 B 登录，不应看见 A 的记录。
4. 用学生 A 再登录，停止服务并用同样配置重启，重新加载后文本仍存在。
5. 管理员登录后查看同一数据库的登录和文本写入审计。学生访问管理 API 返回 403，未登录业务请求返回 401。

显示座位数量仅表示初始化资源目录，不表示任意时段的可预约余量。所有页面时间按北京时间显示，接口与数据库统一为带 `Z` 的 UTC 时间。

## 自动化验证

在 `alpha/` 运行：

```powershell
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -m pytest -q --junitxml=evidence/pytest.xml
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m ruff format --check .
./.venv/Scripts/python.exe scripts/process_smoke.py
```

`process_smoke.py` 使用临时文件数据库、随机端口和两个真实子进程，不修改日常数据库；验证退出首个进程后，第二个进程仍能读取记录与会话，管理员能读取关联审计。

浏览器用例使用仓库根目录的 Playwright 开发依赖和本机 Edge。在根目录安装依赖后，启动一个使用**独立空数据库**的测试服务（5057 端口），执行 `node alpha/tests/browser.cjs`。可用 `STUDYSEAT_TEST_URL` 更改地址。浏览器测试会写入公开测试账号的验证记录，仅用于测试数据库。截图及结果位于 [evidence/](evidence/)。

## 代码与交接

`studyseat/api.py` 处理 HTTP；`auth.py` 处理认证、会话和权限；`db.py` 管理每请求独立连接与统一写事务；`schema.sql` 定义 v1 数据结构；`seed.py` 管理公开初始化数据。所有写入口使用 `BEGIN IMMEDIATE`，失败回滚，锁等待上限 5 秒，锁忙返回 503 和重试提示。数据库新增版本需新迁移，不能仅修改旧表声明。

接口与后续预约契约见 [docs/API-v1.md](docs/API-v1.md)，规则口径见 [docs/RULES.md](docs/RULES.md)，阶段任务、实测和限制见 [docs/DAY1.md](docs/DAY1.md)。

当前为本地开发与课程验收服务。预约事务、签到、超时任务、管理员规则写入和资源关闭尚未实现；预约相关表只有结构，不代表业务通过。公开部署前还需完成登录限速、生产 WSGI/HTTPS 配置和剩余业务验证。

任务和代码已发布至 GitHub：[D1-001 Issue #1](https://github.com/hoangthithang880-dotcom/studyseat-prototype/issues/1)、[功能提交 fd335ba](https://github.com/832402123wuyiming/studyseat-prototype/commit/fd335bafa329659a2b9cd91e1f048b75910e2677)、[PR #2](https://github.com/hoangthithang880-dotcom/studyseat-prototype/pull/2)。当前账号对原仓库只有读取权限，因此推送至个人 Fork 后提交 PR。AI 技术复核已修复 4 类问题，34 项后端测试和浏览器、重启回归通过，详情见 [技术复核报告](docs/REVIEW-D1-001.md)。非作者批准与团队正式验收待完成；未合并或公开部署。
