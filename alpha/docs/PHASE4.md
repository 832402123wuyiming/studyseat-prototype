# StudySeat Alpha 第四阶段开发与交付

第四阶段已通过 GitHub CLI 上传至 [832402123wuyiming/studyseat-prototype](https://github.com/832402123wuyiming/studyseat-prototype/tree/alpha-phase4-20261127) 的 `alpha-phase4-20261127` 分支，关联 [Issue #7](https://github.com/hoangthithang880-dotcom/studyseat-prototype/issues/7) 与 [PR #8](https://github.com/hoangthithang880-dotcom/studyseat-prototype/pull/8)。代码与实测证据提交为 [`9e5233d87df9`](https://github.com/832402123wuyiming/studyseat-prototype/commit/9e5233d87df975f36c9c029a818ec0b9f27ef4a5)。当前 PR 待审查，未合并或部署。

## 基线和审查顺序

本分支继承第三阶段 PR #4 的 60f40e1089d6fd1da6125c19d897331019c9b775，保留完整上游 Git 历史与原型目录。第三阶段 PR 仍打开，相对 main 的 PR 差异包含其内容；应先审查第三阶段，再核对本阶段增量。[第四阶段增量](https://github.com/832402123wuyiming/studyseat-prototype/compare/60f40e1089d6fd1da6125c19d897331019c9b775...9e5233d87df975f36c9c029a818ec0b9f27ef4a5)。

## 实测与交付

- 后端与交付检查共 114 个唯一用例通过：初次全量113项，修正UTF-8收集器后补验4项，汇总JUnit按唯一用例去重，原始报告保留。
- 六套浏览器49项、双进程重启12项通过，Ruff、格式和JS语法通过。
- 每档100次查询，使用1、10、20个并发线程；20名独立学生竞争同座位仅1个201和19个409，库内一条预约，完整性检查通过。
- 备份使用SQLite backup API，覆盖WAL已提交数据，拒绝覆盖既有目标或创建缺失源库。

证据位于 [evidence/phase4](../evidence/phase4)，复跑入口为 `python scripts/verify_phase4.py`，启动与恢复见 [DELIVERY.md](DELIVERY.md)。

## 博客与验收

完整中文博客见 [Word 文档](StudySeat-Alpha-Phase4-Blog.docx)，包含实际运行截图、测试数据、问题处理、代码提交与PR链接。源码上传不代表正式验收完成；非作者审查、团队签收、干净机器首次安装和正式性能目标仍需后续确认。未公开部署，不声称达到百人并发指标。
