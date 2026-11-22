# StudySeat API v1 契约

基础路径 `/api/v1`，前端与 API 同源。JSON 字段使用 snake_case。成功为 `{"data": ...}`，失败为 `{"error":{"code":"...","message":"..."}}`。时间使用 UTC ISO 8601 `Z` 字符串，页面显示 Asia/Shanghai。

账号、密码和验证文本须为有效 UTF-8 文本，不接受 NUL 字符或孤立代理码点；无效输入返回 400。非 ASCII CSRF 值返回 403，不产生服务端异常。健康接口同时检查当前支持的数据库版本和初始化版本记录，异常时返回 503。会话 Cookie 只在数据库事务成功提交后轮换，失败时保留原有效会话。

## 已实现接口

| 方法与路径 | 权限 | 输入 | 成功输出 |
| --- | --- | --- | --- |
| GET /health | 公开 | 无 | status、schema_version、server_time |
| GET /auth/session | 公开 | 无 | user（匿名为 null）、csrf_token；首次创建匿名会话 |
| POST /auth/login | 匿名或已登录会话 + CSRF | username、password 字符串 | user、轮换后的 csrf_token |
| POST /auth/logout | 登录 + CSRF | 无 | user=null、新匿名 csrf_token |
| GET /me | 登录 | 无 | id、username、display_name、role |
| GET /rooms | 登录 | 无 | 房间数组，包括开放分钟数、enabled、seat_count；不是可用性查询 |
| GET /rules | 登录 | 无 | version、settings；仅当前最新版本 |
| GET /persistence-notes | 登录 | 无 | 当前用户验证记录数组 |
| POST /persistence-notes | 登录 + CSRF | content，去首尾空格后 1—200 字符 | 201，id、owner_id、content、created_at |
| GET /persistence-notes/{id} | 登录且记录归本人 | 无 | 验证记录；他人或不存在均 404 |
| GET /admin/audit-events | 管理员 | 无 | 最近 100 条事件，按 id 倒序 |

FR-02 对应登录基础与账号安全，FR-12 对应规则读取基础；本阶段验证文本不对应预约需求，只用于工程验收。

## 会话和错误

与旧 SRS 的登录 token 返回字段不同，当前采用 HttpOnly、SameSite=Lax Cookie `studyseat_alpha`，Cookie 中只携带签名的随机会话标识，数据库保存其 SHA-256 摘要、用户标识、CSRF 和到期时间。用户与角色从数据库逐请求读取，角色变更或禁用立即作用于后续请求。会话有效 8 小时，登录和退出轮换标识并使旧标识失效。HTTPS 模式启用 Secure。

先 GET `/auth/session` 获取 Cookie 和 csrf_token；所有 POST 需 `X-CSRF-Token`。登录前也必须获取 CSRF。浏览器 fetch 使用同源凭据，角色不接受客户端指定。持久化与审计在同一事务提交。禁止把密码、Cookie 或 CSRF 写入日志。

| HTTP | code | 含义 |
| --- | --- | --- |
| 400 | INVALID_INPUT | 参数类型、长度或 JSON 对象无效 |
| 401 | AUTH_REQUIRED | 未登录、失效、过期或账号禁用 |
| 401 | INVALID_CREDENTIALS | 账号或密码错误，统一提示 |
| 403 | FORBIDDEN | 角色无权限 |
| 403 | CSRF_INVALID | CSRF 缺失或不匹配 |
| 404 | NOT_FOUND | 记录不存在或不归本人；未知路径也返回 JSON 404 |
| 413 | REQUEST_ENTITY_TOO_LARGE | 请求体超过 8 KiB |
| 503 | DATABASE_BUSY | 锁等待超过 5 秒，Retry-After: 1；写入未成功 |
| 503 | DATABASE_UNAVAILABLE / NOT_INITIALIZED | 数据库未就绪或缺少初始化数据 |

## 后续接口草案 尚未实现

以下路径只用于后续联调设计，当前调用返回 404，不能用于首阶段业务验收。

| 方法与路径 | 请求与约束 | 计划输出 |
| --- | --- | --- |
| GET /seats?room_id=&start_at=&end_at= | 明确时区，start_at < end_at | 可用座位与服务时间 |
| POST /reservations | seat_id、start_at、end_at、idempotency_key | 201 预约；相同幂等键与相同载荷返回已有记录；异载荷 409 |
| GET /reservations | 服务端按本人过滤；管理员另用管理接口 | 本人预约数组 |
| POST /reservations/{id}/cancel | 本人 + CSRF | 取消回执，重复取消不新增审计 |
| POST /reservations/{id}/check-in | 本人 + CSRF、签到窗口 | 页面签到回执 |
| POST /reservations/{id}/leave 或 /return 或 /finish | 本人 + CSRF、状态和时间校验 | 状态回执 |
| POST /admin/rules | 管理员 + CSRF、完整设置 | 新版本；已有预约保留旧快照 |
| POST /admin/closures/preview | 管理员 + CSRF、范围与原因 | 影响清单和摘要，不写数据 |
| POST /admin/closures | 管理员 + CSRF、预览摘要 | 事务内复核后关闭；变化时 409 要求重新预览 |
| POST /admin/closures/{id}/reopen | 管理员 + CSRF | 重新开放，不恢复取消记录 |

后续业务错误预留 409 RESERVATION_CONFLICT、IDEMPOTENCY_CONFLICT、STATE_NOT_ALLOWED、PREVIEW_STALE 和 400 TIME_INVALID。创建、取消、状态迁移、超时和关闭操作均须使用统一事务策略；当前数据库索引和唯一幂等键不能单独防止时段重叠。预约创建需在 `BEGIN IMMEDIATE` 中完成超时补处理、规则/资源校验、座位与学生两类冲突校验、预约和审计写入；必须补充独立连接并发测试后才能标记完成。
