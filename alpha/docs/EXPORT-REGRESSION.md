# 导出断链回归修复

2026-11-23，在干净的 f0fd0fc 基线复现：`node --test tests/submission.test.cjs` 为 1 passed / 1 failed，失败为导出 README 指向缺失的 alpha/README.md。

保留原型构建与精简资料导出，使用明确根文件、目录和文件类型白名单补齐 README 已链接的 Alpha 交付，不复制整个工作区。新增测试验证 Alpha 入口与后端源存在、Alpha 文档链接可解析，以及 instance、虚拟环境、缓存、.env、无关文件不入选。导出后原型仍可独立重新构建，覆盖保护和哈希校验仍通过。

修复后 `node --test tests/submission.test.cjs`：3 passed；`node --test tests/*.test.cjs`：70 passed，0 failed，0 skipped。原始输出：../evidence/phase2/export-regression.txt。此提交仅修复导出并创建项目约定，阶段二功能另行提交。
