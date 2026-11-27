# StudySeat Alpha 第四阶段交付

本版本基于已合并 PR #6 后的 main 328a3b3d9784d33832094610610498ae14d30935，保留 schema v3、状态版本校验、后台超时任务和管理幂等操作。不得使用旧 PR #4 的 schema v1 实现覆盖当前业务。

## 启动和验证

启动、v1 至 v3 升级和后台任务运行按 alpha/README.md 执行。升级前停止 HTTP 服务和超时进程，先备份数据库与稳定密钥。

第四阶段验证入口：`python scripts/verify_phase4.py`。需要 requirements-dev.txt、Node、Playwright 与本机 Edge；通过 STUDYSEAT_BROWSER_CHANNEL 选择其他已安装浏览器。全部测试使用独立临时库，覆盖后端、七套浏览器、真实进程重启、v1 升级至 v3、独立超时任务和 HTTP 查询及竞争。新结果位于 evidence/phase4-integration。历史 evidence/phase4 是旧候选版本记录，不作为当前版本的通过证据。

## 数据库备份和恢复

在 alpha 目录执行 `python scripts/backup_db.py instance/studyseat.sqlite3 backups/before-demo.sqlite3`。脚本使用 SQLite backup API，包含已提交 WAL 数据并检查完整性，拒绝覆盖目标或创建缺失源库。

恢复时停止 HTTP 和超时任务，归档旧数据库及 WAL、SHM 文件，将备份复制到全新目录，以 STUDYSEAT_DATABASE 指向它，沿用密钥后按 README 初始化升级并启动。不得将旧 WAL 与恢复文件混用。备份与数据库具有同样的数据保护要求，不能提交日常数据库或密钥。

## 发布状态

任务为 Issue #7，合并请求为 PR #8。当前技术审查、验证和合并权限状态见 PHASE4-MERGE-REVIEW.md。GitHub 上传、技术审查、合并和团队现场签收分别记录，不互相替代。原型测试未在本次 Alpha 集成验证中复跑。
