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

## 阶段二预约接口 已实现

关联学生查询、预约主流程、FR-09 取消，以及权限、持久化与并发验收。以下接口均要求 student 会话；所有 POST 还要求 CSRF。管理员访问返回 403。JSON 的 student_id、role 等额外身份字段不影响服务端身份。

| 方法与路径 | 请求与约束 | 成功输出 |
| --- | --- | --- |
| GET /seats?room_id=&start_at=&end_at= | 房间 ID、带时区时间 | 200，{seats:[{id,room_id,label}],start_at,end_at,server_time}；无可用座位为 [] |
| POST /reservations | seat_id、start_at、end_at、idempotency_key | 首次 201；同键同规范化载荷重放为 200，同一预约的当前状态 |
| GET /reservations | 无参数；强制按会话身份过滤 | 200，本人全部预约，start_at 倒序（含取消记录） |
| GET /reservations/{id} | 本人预约 | 200，单个预约；他人或不存在均 404 |
| POST /reservations/{id}/cancel | 无需请求体；本人、PENDING_CHECKIN | 200，CANCELLED 预约；重复取消仍 200，不改首次 ended_at 或审计 |

预约输出含 id、student_id、seat_id、room_id、room_name、seat_label、start_at、end_at、status、rule_version_id、rule_snapshot、created_at、checked_in_at、leave_started_at、leave_deadline、ended_at。不输出幂等键，也不输出其他学生身份或冲突记录。未实现的状态操作时间字段保持 null，取消时 ended_at 为首次取消时间。

时间输入严格为 `YYYY-MM-DDTHH:mm:ss[.ffffff]Z` 或相同格式加 `±HH:mm`；拒绝无时区、非法日期、倒置和零长度区间。URL 参数中的 `+` 应编码为 `%2B`（使用 URLSearchParams/urlencode）。先规范化为 UTC 六位微秒 `Z` 再比较和保存。区间 `[start,end)`，两端相邻允许。规则版本和完整 settings 快照保存于预约，不随新规则修改。

服务端当前时间判断：开始不能在过去，最长 240 分钟（含边界），开始日期至多为北京时间今天 +7 日（含第七日，按日历日而非 168 小时）；结束可跨日但整个区间须处于房间每日开放范围内，00:00—24:00 房间允许跨午夜。房间与座位均须启用，已有未重开关闭记录也阻止预约。规则参数从当前最新 rule_versions 集中读取；查询同样使用此校验。取消仅允许 PENDING_CHECKIN；沿用原型按状态判断，不额外设置开始前截止时间。已取消的重放始终返回原取消结果。

查询结果为即时参考，排除未启用座位、关闭座位、与有效预约重叠的座位；本人已有跨座位重叠预约时返回空列表。有效占用状态为 PENDING_CHECKIN、IN_USE、ON_LEAVE；终态不占用。

创建在同一个 BEGIN IMMEDIATE 中依次读取同人幂等键、读取规则与资源、校验时间与启用状态、检查座位及本人重叠、插入预约和关联审计；任一步失败整体回滚。幂等键为 1—100 个有效 UTF-8 字符，按学生隔离。语义载荷为 seat_id、规范化 start_at/end_at，同一时刻的不同偏移表示视为同载荷；异载荷返回 409 IDEMPOTENCY_CONFLICT。重放优先于当前规则/时间校验，返回原记录当前状态，即使已取消也不复活。取消的归属、状态检查、更新与审计同样在一个写事务内完成。

新增错误：400 TIME_INVALID；409 RESOURCE_UNAVAILABLE、RESERVATION_CONFLICT、IDEMPOTENCY_CONFLICT、STATE_NOT_ALLOWED；503 RULES_UNAVAILABLE（当前规则损坏）。现有 401、403、404、DATABASE_BUSY 和事务回滚策略保持有效。

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

以下路径保留给后续阶段，当前调用返回 404。

| 方法与路径 | 请求与约束 | 计划输出 |
| --- | --- | --- |
| POST /reservations/{id}/check-in | 本人 + CSRF、签到窗口 | 页面签到回执 |
| POST /reservations/{id}/leave 或 /return 或 /finish | 本人 + CSRF、状态和时间校验 | 状态回执 |
| POST /admin/rules | 管理员 + CSRF、完整设置 | 新版本；已有预约保留旧快照 |
| POST /admin/closures/preview | 管理员 + CSRF、范围与原因 | 影响清单和摘要，不写数据 |
| POST /admin/closures | 管理员 + CSRF、预览摘要 | 事务内复核后关闭；变化时 409 要求重新预览 |
| POST /admin/closures/{id}/reopen | 管理员 + CSRF | 重新开放，不恢复取消记录 |

后续操作也须使用统一事务策略；阶段二不执行签到超时补处理、后台任务、管理规则写入或资源关闭。当前创建与取消的事务和独立连接并发已覆盖，详见 [阶段二记录](PHASE2.md)。
