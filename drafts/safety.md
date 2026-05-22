# Security Audit — Unresolved Issues

> Audited 2026-05-22. Issues sorted by severity.

---

## CRITICAL

### 1. JWT Secret Key 使用硬编码默认值

**File**: `server/app/api/auth.py:21`

```python
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
```

**风险**: 所有 `.env.*` 文件均未设置 `SECRET_KEY`，程序将回退到硬编码字符串。任何人都可以用这个字符串伪造 JWT token，冒充任意用户（包括 admin）。

**修复方案**:
- 在 `.env.production` 中添加 `SECRET_KEY=<随机强字符串>`
- 启动时检测：若使用默认值且 `ENV=production`，则拒绝启动
- 可选：开发环境也使用随机值，通过 `.env.development.local`（已 gitignore）提供

---

## HIGH

### ~~2. 无登录频率限制~~ — **已修复** (2026-05-22)

**修复内容**: 实现了基于数据库的 IP 级别登录频率限制（滑动窗口）。

**改动文件**:
- `server/app/config.py` — 新增 `LOGIN_RATE_LIMIT_PER_MINUTE` 配置项（默认 5）
- `server/app/models/login_attempt.py` — 新建 `LoginAttempt` 模型
- `server/app/services/login_rate_limit_service.py` — 新建限速服务
- `server/app/api/auth.py` — 登录接口接入限速检查，超限返回 429
- `server/app/db/session.py` — 注册新表

**行为**: 同一 IP 每分钟失败登录超过 `LOGIN_RATE_LIMIT_PER_MINUTE` 次后返回 HTTP 429，成功登录不计入限制。可通过环境变量 `LOGIN_RATE_LIMIT_PER_MINUTE` 调整阈值。

### 3. 全局异常处理器泄漏内部信息

**File**: `server/app/main.py:238-245`

```python
content={
    "detail": f"Internal server error: {exc!s}",
    "type": type(exc).__name__,
    "path": str(request.url),
}
```

**风险**: 未捕获异常会将完整错误信息、异常类型和请求路径暴露给客户端，可能泄漏数据库结构、文件路径等。

**修复方案**:
- 生产环境（`ENV=production`）仅返回 `"Internal server error"`
- 详细信息只写入服务端日志
- 开发环境可保留完整信息便于调试

### ~~4. 无密码修改功能~~ — **已修复** (2026-05-22)

**修复内容**: 实现了用户自助修改密码和管理员重置密码功能。

**改动文件**:
- `server/app/services/user_service.py` — 新增 `update_password` 方法
- `server/app/models/user.py` — 新增 `ChangePasswordRequest` schema
- `server/app/api/auth.py` — 新增 `POST /auth/change-password` 端点（验证当前密码，新密码 >= 8 字符且不能与当前密码相同）
- `server/app/api/operations_users.py` — 新增 `POST /operations/users/{user_id}/reset-password` 端点（需 `users.manage` 权限）
- `web/src/components/PasswordInput.tsx` — 提取共享密码输入组件（含显示/隐藏切换）
- `web/src/components/ChangePasswordDialog.tsx` — 新建用户自助修改密码对话框
- `web/src/studio/operations/ResetPasswordDialog.tsx` — 新建管理员重置密码对话框
- `web/src/client/ClientUserMenu.tsx` — 接入"修改密码"菜单项
- `web/src/components/Navigation.tsx` — 接入"修改密码"菜单项
- `web/src/studio/operations/UsersPanel.tsx` — 接入每行用户的重置密码按钮
- `web/src/studio/operations/api.ts` — 新增 `resetOperationsUserPassword` API 函数

**行为**:
- 用户可在 Client/Studio 的用户菜单中点击"Change password"自助修改密码，修改成功后自动登出
- 管理员可在 Operations > Users 面板中点击每行的钥匙图标为用户重置密码

---

## MEDIUM

### 5. Sandbox Manager Token 使用弱默认值

**File**: `compose.yaml:27`, `server/app/config.py:37`

```
SANDBOX_MANAGER_TOKEN=dev-sandbox-token
```

**风险**: Sandbox Manager 在 compose 网络内具有 privileged 权限，若 token 被猜中，攻击者可以执行任意容器命令。

**修复方案**: 生产环境必须设置为随机强 token，文档中明确提示。

### 6. CORS allow_methods / allow_headers 过于宽松

**File**: `server/app/main.py:99-101`

```python
allow_methods=["*"],
allow_headers=["*"],
```

**修复方案**: 限制为实际需要的 methods 和 headers（如 `["GET", "POST", "PUT", "DELETE", "PATCH"]`）。

### 7. JWT Token 无撤销机制

**File**: `server/app/api/auth.py:23`

```python
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
```

**风险**: Token 泄漏后在 24 小时内均可用，无黑名单或撤销机制。

**修复方案**:
- 短期：缩短 token 有效期（如 2-4 小时）
- 长期：引入 refresh token + token 黑名单机制

---

## LOW

### 8. `.env.development` / `.env.production` 被 Git 跟踪

**现状**: `server/.env.production` 和 `server/.env.development` 已被 git commit。

**风险**: 如果未来有人往里面添加 API key 等敏感信息，会直接进入版本控制。

**修复方案**: 改为 `.env.*.example` 模板文件（不含真实值），将 `.env.*` 加入 `.gitignore`。

### 9. 文件上传大小限制过大

**File**: `server/.env`

```
MAX_IMAGE_SIZE=104857600  # 100MB
MAX_FILE_SIZE=104857600   # 100MB
```

**风险**: 100MB 上传限制可能被滥用进行 DoS。

**修复方案**: 根据实际使用场景调整到合理大小（如 10-20MB）。

---

## 上线前必须修复

1. **#1** — 设置 `SECRET_KEY`（否则整个认证体系无效）
2. ~~**#2** — 添加登录频率限制~~ — **已修复**
3. **#3** — 关闭生产环境异常详情输出（否则泄漏内部信息）
4. ~~**#4** — 添加密码修改功能~~ — **已修复**
