# StudySeat Alpha 第四阶段交付

本候选版本基于第三阶段 PR #4 的提交 `60f40e1089d6fd1da6125c19d897331019c9b775`，实际验证日期为 2026 年 11 月 27 日。它是独立的 Alpha 应用源码快照，不包含 deploy、prototype、modao 等历史原型目录。第三阶段 PR 仍打开；本地候选版本不代表团队已审查、主分支已合并或已公开部署。

## 启动和复跑

在 alpha 目录执行 README 的 Windows 启动步骤。首次安装需要网络；运行依赖和开发依赖分别锁定在 requirements.txt 与 requirements-dev.txt。完整验证需要 Node、Playwright 和本机 Edge，其他平台通过 STUDYSEAT_BROWSER_CHANNEL 选择已安装浏览器。

```powershell
./start.ps1 -Python 'C:/你的Python目录/python.exe'
# 在同一环境安装开发依赖后
python -m pip install -r requirements-dev.txt
python scripts/verify_phase4.py
```

六套浏览器用例各自建立空数据库并启动临时本机服务。进程重启用例使用两个真实进程；性能脚本使用临时 SQLite 文件、独立会话、线程 WSGI 服务和真实 HTTP。测试不会读取日常数据库。原型测试不属于本次验证范围。

浏览器脚本依赖 Playwright 1.62.1，可在可写工具目录用 `npm install --prefix ./ui-tools playwright@1.62.1` 安装，再将其 node_modules 的绝对路径设为 NODE_PATH。仓库目录若已有依赖，沿用原配置即可。不要把 node_modules 打包交付。

Windows 临时目录过长时，在当前 PowerShell 中把 TEMP 和 TMP 设置为短的可写目录后重试。自动化需要访问 127.0.0.1；受限沙箱中的连接拒绝属于运行环境限制，不应计作业务失败。

## 备份和恢复

```powershell
python scripts/backup_db.py instance/studyseat.sqlite3 backups/before-demo.sqlite3
```

备份通过 SQLite backup API 读取一致快照，包含已提交的 WAL 数据；目标已存在时拒绝覆盖，源不存在时拒绝创建空库。备份包含账号、会话与业务记录，应与正式数据库按相同权限保管。不要把日常数据库或密钥提交到 Git。

恢复时先停止服务，保留当前数据库及其同名 -wal、-shm 文件到另一个归档目录；不要将旧的 WAL 与备份混用。将备份复制到一个全新的目录，设置 STUDYSEAT_DATABASE 指向该文件，沿用原密钥后启动服务，检查健康接口、预约列表和审计。确认恢复成功后再处理旧目录。回滚源码不等于回滚数据库；规则和预约不得因恢复演示而悄悄丢失。

## 演示顺序

1. 初始化公开演示账号，学生 A 创建明日预约，刷新后记录仍在。
2. 退出并以学生 B 登录，同座位同时间预约被拒绝；不能读写 A 的记录。
3. 运行 phase3-browser.cjs 的独立演示，使用真实 API 创建开始于两分钟后的预约，页面签到、暂离、返回；不修改生产时钟。
4. 管理员对使用中的房间预览关闭，看到阻断；对含待签到预约的座位预览、确认关闭。
5. 重新开放，确认已经取消的预约不复活；学生刷新显示一致结果。
6. 展示 process_smoke.py 结果，证明重启、重登、幂等和审计恢复。

## 版本与放行

性能结果在 evidence/phase4/performance.json，回归摘要在 verification.json，后端 JUnit 在 pytest.xml，六套页面结果与截图位于对应子目录。版本的源文件 SHA256 在 evidence/phase4/source-manifest.json。仅在 verification.json 为 passed 且源文件摘要一致时，将对应测试结果用于本候选版本。

目前交付为本机课程验收候选版。非作者审查、团队正式验收、干净机器首次安装、公开部署和百人并发指标均需另行验证。登录限速、生产 WSGI/HTTPS、校园认证、通知送达和物理到场验证未在本阶段实现。11 月 28 日为计划中的补验窗口；不得提前写成已发生。
