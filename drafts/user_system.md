# Pivot User System Design

## 背景

Pivot 目前已经形成了两类产品入口：

- Studio：面向管理者和 Builder，用于创建、调试、发布和运营 Agent 及相关资产。
- Client：面向最终用户，包括 Web Consumer、Channel、Desktop 等入口，用于使用已发布或已授权的 Agent。

当前系统已经有 `User` 和 JWT 登录，但权限模型还停留在：

- 登录即可访问多数 Studio API。
- 部分用户数据通过 `username` 手动做归属判断。
- Consumer 侧 Agent 可见性主要由 `active_release_id` 和 `serving_enabled` 决定。
- Operations 已经是跨用户运营视角，但接口还没有真正做 admin 权限判断。

本设计目标是建立一套简洁、可逐步落地、适合 Pivot 当前阶段的统一用户系统。

## 设计原则

1. 统一账号体系

   Studio、Web Consumer、Channel、Desktop 使用同一套 `User`。

2. 不引入 Organization

   当前阶段不做多租户组织模型。Organization 太重，会提前引入账单、空间、组织级资产等产品心智。先用 `Group` 解决批量授权问题。

3. Role 控制入口和系统能力

   Role 决定用户是否能进入 Studio、是否能管理用户、是否能管理 Agent/Skill/Tool/Extension 等模块。

4. ResourceAccess 控制具体实体权限

   具体实体只区分 `use` 和 `edit`：

   - `use`：可见、可使用、可运行。
   - `edit`：可编辑、删除、发布、配置授权等管理动作。

5. 简单默认，按需细化

   不在创建每个实体时强迫用户理解复杂权限。创建者默认拥有 `edit`，实体默认按业务场景设置合理的 `use_scope`，需要共享时再进入权限面板调整。

6. 所有持久层交互通过 service

   用户、角色、权限、分组、实体授权都应通过 `server/app/services` 下的 service 访问，API/router 不直接操作持久层细节。

## 核心概念

### User

唯一账号主体。

建议字段：

```text
User
- id
- username
- password_hash
- role_id
- status: active | disabled
- display_name
- email
- created_at
- updated_at
```

说明：

- 第一阶段可以保留 `username` 作为已有业务的兼容字段。
- 新增逻辑应尽量使用 `user_id` 做关联，逐步减少对 `username` 的权限判断依赖。
- `status = disabled` 的用户不能登录，也不能通过 Channel 继续使用系统。

### Role

Role 控制入口和系统能力。

系统初始化默认创建三个角色：

```text
user
builder
admin
```

建议字段：

```text
Role
- id
- key
- name
- description
- is_system
- created_at
- updated_at
```

默认语义：

| Role | 语义 |
| --- | --- |
| `user` | 只能进入 Client 端，使用自己有 `use` 权限的实体 |
| `builder` | 可以进入 Studio，创建资源，管理自己有 `edit` 权限的实体 |
| `admin` | 系统管理员，管理用户、角色、分组和所有资源 |

约束建议：

- `admin` 角色不能删除。
- 系统中至少保留一个 active admin 用户。
- `admin` 建议在后端有兜底 bypass：即使 RolePermission 表误删，`role.key == "admin"` 仍然拥有全部系统权限，避免把系统锁死。

### Permission

Permission 是系统支持的能力清单。

Permission catalog 由代码定义并在系统初始化时同步入库。用户不能创建后端不认识的 permission key，但可以通过 Roles 菜单编辑 Role 与 Permission 的关系。

建议字段：

```text
Permission
- id
- key
- name
- description
- category
- is_system
```

第一版建议权限清单：

```text
client.access
studio.access

users.manage
groups.manage
roles.manage

operations.view

agents.manage
llms.manage
tools.manage
skills.manage
extensions.manage
channels.manage
media_generation.manage
web_search.manage
storage.view
```

说明：

- `*.manage` 是系统模块权限，不表示能编辑所有实体。
- 例如 `agents.manage` 表示能进入 Agent 管理模块、能创建 Agent、能尝试管理 Agent。
- 编辑某个具体 Agent 还需要该 Agent 的 `edit` 实体权限。

### RolePermission

持久化 Role 与 Permission 的关系。

```text
RolePermission
- role_id
- permission_id
```

默认 seed：

```text
user:
- client.access

builder:
- client.access
- studio.access
- agents.manage
- tools.manage
- skills.manage
- storage.view

admin:
- all permissions
```

后续可以根据产品发展把 builder 的默认权限扩展到：

```text
llms.manage
extensions.manage
channels.manage
media_generation.manage
web_search.manage
```

但第一版建议保守，避免普通 Builder 一开始就能配置高风险 secret、channel auth、extension trust。

### Group

Group 是批量授权单位，不代表独立空间。

不要先叫 Team。Team 容易让用户以为有 Team 首页、Team 资产空间、Team 配置和 Team 账单。当前阶段 `Group` 更准确。

建议字段：

```text
Group
- id
- name
- description
- created_by_user_id
- created_at
- updated_at
```

### GroupMember

```text
GroupMember
- group_id
- user_id
- created_at
```

Group 的用途：

- 给一批用户授权使用某个 Agent。
- 给一批 Builder 授权编辑某个 Agent。
- 给一批用户共享某个 Project 或 Workspace。
- 避免每个实体都一个一个选择 User。

### ResourceAccess

具体实体授权表。

```text
ResourceAccess
- id
- resource_type
- resource_id
- principal_type: user | group
- principal_id
- access_level: use | edit
- created_at
- updated_at
```

建议约束：

```text
unique(resource_type, resource_id, principal_type, principal_id, access_level)
```

权限语义：

| Access | 含义 |
| --- | --- |
| `use` | Studio 侧可见、可选择、可引用、可使用 |
| `edit` | 可编辑、删除、发布、配置授权；自动包含 `use` |

重要边界：

- 默认情况下，实体级 `use/edit` 都是 Studio 侧协作权限。
- 对 LLM、Skill、Tool、Extension、Project 等实体，`use` 表示其他 admin/builder 能否在 Studio 中看到、选择、引用该实体。
- 只有 Agent 的 `use` 会直接影响 Client/User 端：Client、Channel、Desktop 等最终用户入口能否看到、进入、运行某个 Agent，应只看 `Agent.use`。
- Agent 运行时引用的底层实体不再按最终用户重新检查 `use`。例如 A 在 Studio 中有某个 LLM 的 `use` 权限，并用它配置了 Agent；该 Agent 授权给 B 使用后，B 运行 Agent 时不需要同时拥有这个 LLM 的 `use` 权限。
- 底层实体的权限控制发生在 Studio 配置阶段，而不是 Client 运行阶段。运行阶段以 Agent 授权和 Agent 已保存的配置为边界。

实体自身建议增加：

```text
created_by_user_id
use_scope: all | selected
```

`use_scope` 语义：

| Scope | 含义 |
| --- | --- |
| `all` | 所有 active 登录用户可 `use` |
| `selected` | 只有 ResourceAccess 中被授权的 users/groups 可 `use` |

`edit` 不建议支持 `all`。`edit` 应始终是 selected 模型，并且创建者默认拥有不可移除的 `edit`。

## 实体编辑 Auth Tab

对所有具备实体级 `use/edit` 权限、且本身有编辑 dialog 的资源，统一在编辑 dialog 中增加 `Auth` tab。

`Auth` tab 只管理某一个具体实体的资源级授权，不改变 Role/Permission 的系统能力边界：

- Role / Permission 控制入口和系统能力，例如 `llms.manage`、`agents.manage`、`users.manage`。
- `Auth` tab 控制某一个具体实体谁可以 `use`，谁可以 `edit`。

交互统一为两块：

- `Use`：谁可以在 Studio 侧看见、使用、选择、引用该实体。Agent 例外：Agent 的 `Use` 同时决定 Client/User 端能否看到和运行该 Agent。
- `Edit`：谁可以修改、删除、继续授权该实体。

每块都使用同一套 user/group 选择器：

- selected users
- selected groups

规则：

- creator 默认必须拥有 `edit`，不能被移除。
- `edit` 自动隐含 `use`，后端判断时以 `edit => use` 为准。
- admin 作为系统级 override，不需要被写入每个实体的 ResourceAccess。
- Group 只作为批量授权单位，不引入 Organization/Team 空间。
- Agent 的 `use_scope = all | selected` 是 Client/User 端可用范围。
- LLM、Skill、Tool、Extension、Project 等实体的 `use_scope = all | selected` 是 Studio 侧可用范围，不应该影响外部用户运行 Agent。

实现策略：

- 第一阶段：各实体保留自己的 access API，便于处理实体特有逻辑，例如 Project 同步 Workspace。
- 前端抽出可复用的 principal selector / Auth tab 组件。
- 当 Agent、Project、LLM 等 3-4 个实体的行为稳定后，再考虑是否收敛为 generic resource-access API。

## 权限判断规则

### 系统权限判断

系统权限用于判断用户是否能访问某个模块或执行某类系统操作。

判断顺序：

```text
1. 用户不存在或 disabled -> deny
2. role.key == "admin" -> allow
3. 查询 RolePermission 是否包含目标 permission -> allow/deny
```

示例：

- 能不能进入 Studio：`studio.access`
- 能不能管理 Users：`users.manage`
- 能不能进入 Operations Sessions：`operations.view`
- 能不能进入 Agent 管理模块：`agents.manage`

### 实体权限判断

实体权限用于判断用户是否能 `use` 或 `edit` 某个具体资源。

判断顺序：

```text
1. 用户不存在或 disabled -> deny
2. role.key == "admin" -> allow
3. requested access 是 use，且实体 use_scope == all -> allow
4. 用户是实体 created_by_user_id -> allow edit/use
5. 用户或其 Group 有 edit grant -> allow edit/use
6. requested access 是 use，且用户或其 Group 有 use grant -> allow
7. deny
```

说明：

- `edit` 自动包含 `use`。
- 创建者默认拥有 `edit`，不能被移除。
- `use_scope = all` 只影响 `use`，不影响 `edit`。
- 除 Agent 外，实体 `use` 判断只应用于 Studio 侧的列表、选择器、配置和引用动作。
- Agent 运行时不向最终用户递归检查 LLM/Skill/Tool/Extension 等底层实体的 `use` 权限。

## 适用实体

第一阶段优先落到 Agent。

```text
Agent
- created_by_user_id
- use_scope
- ResourceAccess grants
```

后续逐步扩展：

```text
Project
Workspace
Skill
Tool
ExtensionInstallation
AgentChannelBinding
LLM / Provider Config
MediaGeneration Provider
WebSearch Provider
```

不同实体的推荐默认：

| Entity | 默认 use_scope | 默认 edit |
| --- | --- | --- |
| Agent draft | selected | creator |
| Published Agent | 发布时选择 all/selected | creator + selected editors |
| Project | selected | creator |
| Workspace | 跟随 Session/Project | creator 或 Project editors |
| User Tool | all | creator |
| User Skill | all | creator |
| Built-in Tool | all | none |
| ExtensionInstallation | selected/admin controlled | installer/admin |
| ChannelBinding | selected | agent editors |
| LLM Provider Config | selected/admin controlled | admin/selected managers |

补充：

- 上表的非 Agent 实体默认值描述的是 Studio 侧协作模型。
- Client/User 端最终用户的可见性和可运行性只由 Agent 授权决定，不由 Agent 内部引用的 LLM/Skill/Tool/Extension 等实体授权决定。

## FastAPI 权限设计

### 不推荐全局 middleware/interceptor 做全部权限

FastAPI middleware 只能自然拿到 request path/method/header。真实权限判断通常需要：

- 当前用户。
- 数据库 session。
- 路由 path 参数。
- 业务实体。
- 实体创建者。
- group membership。
- `use_scope`。
- 具体 endpoint 语义。

把这些放进 middleware 会让逻辑变成路径字符串匹配，不好测试，也不符合当前 service 层规则。

### 推荐方案

使用三层设计：

```text
1. Authentication dependency
2. System permission dependency
3. Resource access service
```

建议文件：

```text
server/app/api/auth.py
server/app/security/permission_catalog.py
server/app/api/permissions.py
server/app/services/permission_service.py
server/app/services/access_service.py
server/app/models/access.py
```

职责：

| 文件 | 职责 |
| --- | --- |
| `api/auth.py` | 登录、JWT、`get_current_user` |
| `security/permission_catalog.py` | 代码内置的 Permission key 清单 |
| `api/permissions.py` | FastAPI dependency：`permissions(...)` 等 |
| `services/permission_service.py` | Role/Permission 查询和 seed |
| `services/access_service.py` | ResourceAccess 查询、授权、实体 use/edit 判断 |
| `models/access.py` | Role、Permission、Group、GroupMember、ResourceAccess 等模型 |

### 系统权限 dependency

建议把 endpoint 里的权限声明写得短一些，避免大量重复样板。

推荐命名：

```python
permissions(Permission.OPERATIONS_VIEW)
```

而不是：

```python
require_system_permission(SystemPermission.OPERATIONS_VIEW)
```

其中：

- `Permission` 是代码内置 permission catalog 的 enum。
- 数据库里的 `Permission.key` 与 enum value 对齐。
- `permissions(...)` 返回一个 FastAPI dependency。

示例实现：

```python
def permissions(*required_permissions: Permission):
    def dependency(
        current_user: User = Depends(get_current_user),
        db: DBSession = Depends(get_db),
    ) -> User:
        PermissionService(db).require_permissions(
            current_user,
            required_permissions,
        )
        return current_user

    return dependency
```

使用方式：

```python
@router.get("/operations/sessions")
async def list_operations_sessions(
    current_user: User = Depends(permissions(Permission.OPERATIONS_VIEW)),
):
    ...
```

Studio 模块：

```python
current_user: User = Depends(permissions(Permission.STUDIO_ACCESS))
```

Agent 管理模块：

```python
current_user: User = Depends(permissions(Permission.AGENTS_MANAGE))
```

### 实体权限 service

实体权限也不应使用裸字符串，例如：

```python
resource_type="agent"
access_level="edit"
```

这种写法容易拼错，也会让开发者绕开系统约束。推荐使用类型化参数。

建议 enum：

```python
class ResourceType(str, Enum):
    AGENT = "agent"
    PROJECT = "project"
    WORKSPACE = "workspace"
    SKILL = "skill"
    TOOL = "tool"
    EXTENSION = "extension"
    CHANNEL_BINDING = "channel_binding"
    LLM = "llm"
    MEDIA_GENERATION_PROVIDER = "media_generation_provider"
    WEB_SEARCH_PROVIDER = "web_search_provider"


class AccessLevel(str, Enum):
    USE = "use"
    EDIT = "edit"
```

推荐调用：

```python
AccessService(db).require_access(
    user=current_user,
    resource_type=ResourceType.AGENT,
    resource_id=agent_id,
    access_level=AccessLevel.EDIT,
)
```

也可以提供面向实体 class 的封装，以减少 `ResourceType` 选择错误：

```python
AccessService(db).require_entity_access(
    user=current_user,
    entity_cls=Agent,
    entity_id=agent_id,
    access_level=AccessLevel.EDIT,
)
```

内部通过 registry 解析：

```python
RESOURCE_REGISTRY = {
    Agent: ResourceType.AGENT,
    Project: ResourceType.PROJECT,
    Workspace: ResourceType.WORKSPACE,
    Skill: ResourceType.SKILL,
}
```

推荐第一版同时支持两种形式：

- router 层更常用 `require_entity_access(..., entity_cls=Agent, ...)`，可读性更好。
- service 内部和跨实体批量查询使用 `ResourceType` enum，更适合存储和过滤。

典型 endpoint 组合：

```text
编辑 Agent:
1. require system permission: agents.manage
2. require resource access: agent.edit

Client 使用 Agent:
1. require system permission: client.access
2. require resource access: agent.use

查看 Operations:
1. require system permission: operations.view
2. 不做 session.user == current_user.username 限制
```

## Operations UI 设计

Operations 菜单下增加：

```text
Operations
- Sessions
- Users
- Groups
- Roles
```

### Users

能力：

- 查看用户列表。
- 创建用户。
- 禁用/启用用户。
- 重置密码。
- 修改用户 role。
- 查看用户所属 groups。
- 查看用户最近 sessions。

权限：

```text
users.manage
```

### Groups

能力：

- 创建 group。
- 修改 group 名称和描述。
- 添加/移除成员。
- 查看 group 被授权的资源。

权限：

```text
groups.manage
```

### Roles

能力：

- 查看 role 列表。
- 创建自定义 role。
- 修改 role 描述。
- 编辑 role 与 permission 的关系。
- 删除非系统 role。

权限：

```text
roles.manage
```

约束：

- `admin` 不能删除。
- 不允许移除最后一个 active admin。
- Permission key 来源于系统 catalog，不能在 UI 随意创建未知 permission。

## API 初稿

### Users API

```text
GET    /api/operations/users
POST   /api/operations/users
PATCH  /api/operations/users/{user_id}
POST   /api/operations/users/{user_id}/reset-password
```

### Groups API

```text
GET    /api/operations/groups
POST   /api/operations/groups
PATCH  /api/operations/groups/{group_id}
DELETE /api/operations/groups/{group_id}
GET    /api/operations/groups/{group_id}/members
POST   /api/operations/groups/{group_id}/members
DELETE /api/operations/groups/{group_id}/members/{user_id}
```

### Roles API

```text
GET    /api/operations/roles
POST   /api/operations/roles
PATCH  /api/operations/roles/{role_id}
DELETE /api/operations/roles/{role_id}
GET    /api/operations/permissions
PUT    /api/operations/roles/{role_id}/permissions
```

### Resource Access API

可以先只做 Agent：

```text
GET /api/agents/{agent_id}/access
PUT /api/agents/{agent_id}/access
```

请求语义：

```json
{
  "use_scope": "selected",
  "use_user_ids": [1, 2],
  "use_group_ids": [3],
  "edit_user_ids": [4],
  "edit_group_ids": [5]
}
```

服务端规则：

- 自动确保 creator 在 edit users 中。
- edit users/groups 自动拥有 use，不需要重复写入 use grant。
- admin 可以修改任何 Agent access。
- builder 必须有该 Agent 的 `edit` 权限才能修改 access。

## 初始化与迁移

系统启动时应调用 seed service：

```text
PermissionService.seed_permissions()
RoleService.seed_default_roles()
UserService.ensure_default_user()
```

默认结果：

```text
Role:
- user
- builder
- admin

Permission:
- 所有系统内置 permission catalog

RolePermission:
- user -> client.access
- builder -> client.access, studio.access, agents.manage, tools.manage, skills.manage
- admin -> all permissions

User:
- default 用户存在时，确保 role = admin
- default 用户不存在时，创建 default / 123456 / admin
```

因为项目尚未上线，可以优先采用清晰 schema，不需要写过多历史兼容逻辑。若 schema 变动导致本地开发数据库异常，可以删除开发数据库后重启。

## 分阶段实施计划

### Phase 1：Role 和系统权限地基

目标：

- User 拥有 role。
- Role/Permission/RolePermission 入库。
- 默认创建 user、builder、admin。
- default 用户默认 admin。
- 后端有统一 `permissions(Permission.X)` dependency。

改动：

```text
server/app/models/access.py
server/app/services/permission_service.py
server/app/api/permissions.py
server/app/api/auth.py
server/app/db/session.py
```

验证：

- default 登录后可访问 Studio。
- 非 admin 用户不能访问 Operations Users/Roles。
- `admin` 即使 RolePermission 缺失也不会锁死系统。

### Phase 2：Operations Users/Roles

目标：

- Operations 下新增 Users 和 Roles。
- admin 可修改用户 role。
- admin 可编辑 role 与 permission 的关系。

改动：

```text
server/app/api/operations_users.py
server/app/api/operations_roles.py
web/src/studio/operations/*
web/src/components/Navigation.tsx
```

验证：

- admin 能创建/禁用用户。
- admin 能把用户从 `user` 改成 `builder`。
- builder 不能访问 Users/Roles 管理页面和 API。

### Phase 3：保护现有 Studio 高风险入口

目标：

- Operations Sessions 需要 `operations.view`。
- Agent 管理需要 `agents.manage`。
- LLM/Tool/Skill/Extension/Channel 等管理入口分别需要对应 permission。

建议映射：

| API 模块 | Permission |
| --- | --- |
| `/api/operations/sessions` | `operations.view` |
| `/api/agents*` Studio 写操作 | `agents.manage` |
| `/api/llms*` | `llms.manage` |
| `/api/tools*` | `tools.manage` |
| `/api/skills*` | `skills.manage` |
| `/api/extensions*` | `extensions.manage` |
| `/api/channels*` 管理接口 | `channels.manage` |
| `/api/media-generation*` | `media_generation.manage` |
| `/api/web-search*` | `web_search.manage` |
| `/api/system/storage-status` | `storage.view` 或登录即可 |

验证：

- user 只能进入 Client。
- builder 可以进入 Studio，但不能访问没有 permission 的模块。
- admin 全部可访问。

### Phase 4：Group/GroupMember

目标：

- Operations 下新增 Groups。
- 可以创建 group、管理 group member。
- ResourceAccess 可引用 group。

验证：

- group 成员变更会影响实体授权判断。
- 删除 group 时清理或阻止关联 ResourceAccess。

### Phase 5：Agent use/edit 授权

目标：

- Agent 增加 `created_by_user_id` 和 `use_scope`。
- 创建 Agent 时创建者自动拥有 edit。
- Studio Agent 列表只显示当前用户可 edit 的 Agent，admin 看全部。
- Consumer Agent 列表只显示当前用户可 use 的 Agent。
- Agent access 面板支持 all/selected 和 users/groups。

验证：

- user 只能看到被授权 use 的 Agent。
- builder 只能编辑自己创建或被授权 edit 的 Agent。
- edit 自动包含 use。
- creator 的 edit 不能被移除。

### Phase 6：扩展到 Project/Workspace/Asset

目标：

- Project 支持 selected users/groups 协作。
- Workspace 文件读写通过 AccessService 验证。
- Skill/Tool/Extension/Channel/LLM Provider 等逐步接入 use/edit 或 manage 权限。

当前进展：

- Project 列表改为按 `ResourceType.PROJECT` 的 `use/edit` 判断可见性。
- Project metadata 更新、删除需要 `project.edit`。
- Project access API 已支持读取、更新 selected users/groups。
- Project access 更新会同步到 `ResourceType.WORKSPACE`，从而统一控制项目 workspace 的文件读写。
- Project response 返回 `can_edit`，前端可以隐藏 use-only 协作者不应看到的编辑动作。
- Workspace 授权判断已收敛到 `AccessService.has_workspace_access()`；Workspace file CRUD、Preview endpoint 和 Surface session 对共享 Project workspace 不再只认 workspace owner，而是通过 `ResourceType.WORKSPACE` 的 `use/edit` 授权判断协作者是否能读写文件、启动/连接预览和 surface 会话。
- LLM 配置已接入 `ResourceType.LLM` 的 `edit` 权限；创建者默认获得 edit，列表/读取/更新/删除只对有 edit 的用户开放。
- LLM 已新增 Studio 侧 usable selector API：Agent 配置选择 LLM 时只读取当前用户有 `LLM.use` 或 `LLM.edit` 的安全字段，不暴露 `api_key`、endpoint、extra config 等管理信息。
- LLM 编辑 dialog 已增加 `Auth` tab，可通过同一套 user/group 选择器管理 `use/edit` 授权。
- Skill 已新增 Studio 侧 usable selector API：Agent 技能选择器和 Agent 侧边栏只读取当前用户有 `Skill.use` 或 `Skill.edit` 的技能；use-only Skill 可以被配置进 Agent，但不会开放 Skill 源码编辑能力。
- Skill 已从旧 `private/shared` 产品语义收敛到统一 Auth：Skill registry 增加 `use_scope`，Skills 列表新增实体设置入口，实体编辑 dialog 使用左侧 vertical tabs + 右侧固定高度内容的 `General/Auth` 结构；原 pencil 入口保留为直接编辑 Skill 目录文件。
- Tool 已从旧 `private/shared` 产品语义收敛到统一 Auth：Tools 列表移除 `Type/private/shared` 操作表达，新增实体设置入口；Tool 编辑 dialog 使用左侧 vertical tabs + 右侧固定高度内容的 `General/Auth` 结构；原 pencil 入口保留为直接编辑 `tool.py`。
- Tool 已新增 `ToolResource` auth metadata，不存源码，只持久化 Tool 的 `use_scope` 和 ResourceAccess 关联键；源码文件仍通过 workspace service 管理。
- User-created Tool 默认 `use_scope = all`，创建者默认拥有 `edit`；Tool name 必须同时满足 `.py` 文件名 stem 和 Python function name 规则，并要求源码中定义同名 decorated function。
- Built-in Tool 固定为所有人可 `use`、无人可 `edit`；可以打开 settings/source 查看，但不能修改 Auth 或源码。
- Tool 已新增 Studio 侧 usable selector API：Agent Tool 选择器和 Agent 侧边栏只读取当前用户有 `Tool.use` 或 `Tool.edit` 的工具；builtin tools 始终可用。
- Skill/Tool 管理页已从旧的文件作用域列表切换到实体权限视角：列表展示当前用户有 `use` 或 `edit` 的实体；`use-only` 实体可见、源码只读、不能保存 Auth 或删除；`edit` 实体可改源码、Auth 和删除。
- Skill/Tool 源码读取已通过实体级 `use` 判断；源码更新、删除已通过实体级 `edit` 判断，避免再依赖“只能操作当前用户自己文件”的旧入口语义。
- Manual Tool 新建入口已收敛到 `ToolService.create_manual_tool_source()`，由 service 同时负责写入源码、创建 `ToolResource`、授予创建者 `edit`，API 层不再拼装文件写入和授权初始化。
- `Auth` tab 的 `Use` 权限支持 `Everyone` / `Selected Members`，实体新建默认 `Everyone`。
- Skill Import 不再暴露 `private/shared`；导入只确认来源与 Skill Name，导入后默认 `Use = Selected Members` 且只包含创建者本人，`Edit` 默认包含创建者本人。需要共享时再进入 Skill Settings 的 `Auth` tab 调整。
- Skill 源码编辑器升级为目录级编辑器：左侧是 collapsible 文件树，右侧是 Monaco；`SKILL.md` 是默认打开文件，Skill 目录内的其他文本文件也应可查看和编辑。目录树读取通过实体级 `use` 判断，文件更新通过实体级 `edit` 判断。
- Skill 文件树必须渐进式读取：根目录只加载直接 children；所有文件夹默认闭合；点击展开某个文件夹时才通过 Skill service 复用 `LocalDirectoryFileService` 读取该目录的直接 children，避免一次性加载大型 Skill 目录。
- Skill 源码编辑器已补齐目录级 CRUD 闭环：File Tree 根区域和每个文件夹都可新增 file/folder；文件和文件夹都可通过 `...` 菜单删除，删除前必须 Alert 确认；新增/删除都通过 Skill service 复用 `LocalDirectoryFileService` 并在成功后重新 restage Skill artifact。
- Skill 源码编辑器对不支持预览的文件不触发 toast，而是在 Monaco 区域内显示英文不可预览提示；加载状态统一使用 spinner。AlertDialog 层级需要高于 DraggableDialog，避免删除确认被 Monaco/浮窗遮挡。
- Skill/Tool 的源码编辑器是实体设置 dialog 的子流程：从 `General` 打开 Monaco 时先隐藏设置 dialog，避免 modal overlay/focus trap 与 Monaco 交互冲突。新建 Skill/Tool 的未落库源码仍先回填当前 draft，已有实体的源码文件保存直接落到对应 service。
- ExtensionInstallation 已接入 `ResourceType.EXTENSION` 的 `use/edit` 权限：安装者默认获得 `edit`，列表/详情只展示当前用户有 `use` 或 `edit` 的安装版本，状态切换、卸载、Setup 配置读取/保存都需要 `edit`。
- Extension 详情页新增 `Auth` tab，复用统一 `ResourceAuthTab`，按 installed version 管理 `use/edit` 授权；如果当前用户只有 `use` 没有 `edit`，可看到只读提示但不能修改 Auth。
- Extension 详情页的 `Setup` 和 `Hook Replay` tab 应动态展示：没有 installation setup fields 的版本不渲染 Setup tab；没有 lifecycle hooks 的 package 不渲染 Hook Replay tab，避免空 tab 干扰操作。
- Extension hook execution 列表只展示当前用户拥有所属 Extension `use` 的 package 日志；Hook Replay 和 installation references 属于管理动作，必须拥有对应 installed version 的 `edit` 权限。
- Agent 绑定 Extension 的选择器已接入 `Extension.use/edit`：Agent 配置扩展时只展示当前 Studio 用户可用的 ExtensionInstallation；保存绑定时后端再次校验 `Extension.use`，避免绕过前端选择器。
- Agent 子配置统一继承 `Agent.edit` 管理边界：Extension binding 和 Channel binding 的列表、创建、更新、删除、测试、轮询等 Studio 管理动作都必须先校验当前用户能编辑父 Agent；Channel webhook / external link 等运行时入口不递归检查 Studio 侧底层实体授权。
- Channel Provider、Media Generation Provider 和 Web Search Provider 当前没有独立导入/创建入口，provider definition 不单独设计 Auth；extension-backed provider 跟随所属 ExtensionInstallation，provider catalog、单项读取、draft test 和创建 binding 都必须先确认当前 Studio 用户拥有所属 Extension 的 `use` 权限；provider binding 作为 Agent 子配置继承 `Agent.edit`。对应 binding 的列表、创建、更新、删除、测试等 Studio 管理动作都必须先校验父 Agent 可编辑。
- `chat_surfaces.py` 的 workspace 文件入口已确认全部通过 `WorkspaceFileService`；preview/surface proxy 和 websocket 在取得 workspace backend path 之前，会先通过 `SurfaceSessionService` / `PreviewEndpointService` 校验 session、surface token 和 `Workspace.edit`，不在 API 层用裸路径绕过授权。
- 前端已抽出可复用的 `ResourceAuthTab`，后续实体可以复用同一套 Auth tab 交互。
- 已对齐权限边界：LLM/Skill/Tool/Extension 等底层实体的 `use` 是 Studio 侧配置权限；Agent 对外开放后，最终用户运行 Agent 时只检查 `Agent.use`，不会因为缺少底层实体 `use` 权限而失败。
- 已对齐配置边界：实体 `use` 只代表 Studio 配置候选可见、可选择，不代表自动绑定到既有 Agent。新建/导入 Skill、Tool、Extension 后，只会出现在 Agent 配置弹窗的候选列表中；只有用户显式保存 Tool/Skill selection 或 Extension binding 后，才算进入该 Agent 的已配置能力集。`agent.tool_ids` / `agent.skill_ids` 的 `null` 也按“未选择任何手动 Tool/Skill”处理，不再表示“未来所有可用 Tool/Skill 自动启用”。Extension 贡献的 Tool/Skill 只随显式 Extension binding 进入 Agent。

### Phase 7：Agent Auth 产品化

目标：

- Agent New/Edit Dialog 增加标准 `Auth` tab，和 General/Advanced 使用同一个保存入口。
- Agent `use` 明确面向 Client/User 端，不是 Studio Builder/Admin 的配置可见性。
- Agent `edit` 第一版只允许 creator/admin，不开放 Builder 协作编辑。

当前进展：

- Agent New/Edit Dialog 已接入 `Auth` tab，用于配置哪些最终用户/用户组可以从 Web、Desktop、Channel 等客户端看到和运行 Agent。
- Agent `Auth` tab 现已展示 `Use` + `Edit` 两个 tab：`Use` 可配置最终用户范围；`Edit` 第一版固定只读展示 creator/admin，不允许共享给其他 Builder。
- Agent 创建时可同步写入 `use_scope`、selected users/groups；Agent 编辑保存时同步更新 Agent `use` 授权。
- 后端 `AccessService.set_agent_access()` 已收敛为 creator-only edit：即使请求传入额外 edit users/groups，也不会授予非 creator 的 Agent edit。
- Client/User 侧的 Agent 可见性与进入权限已开始收口到 `Agent.use`：`/consumer/agents`、`/consumer/agents/{id}`、`/consumer/sessions` 已按 `Agent.use` 过滤；`/sessions`、`/sessions/{id}`、`/sessions/{id}/history`、`/sessions/{id}/full-history`、`/sessions/{id}` update/delete 也会在 session owner 校验后再次确认当前用户仍拥有该 Agent 的 `use` 或 `edit` 权限。
- ReAct runtime 入口已补齐同一条边界：`/react/tasks`、`/react/chat/stream`、`/react/context-usage`、`/react/runtime-skills`、`/react/sessions/{id}/events/stream`、`/react/sessions/{id}/runtime-debug`、`/react/tasks/{id}` 及其 recursions/states 查询，都会同时检查系统入口权限（`client.access` 或 `agents.manage`）与当前 Agent 的资源权限（consumer = `use`，studio_test = `edit`）。
- `chat-surfaces` / `chat-previews` 这一层也已补齐同一条边界：创建、读取、重连 surface session / preview endpoint 时，不只检查 session owner 和 workspace 权限，还会重新确认当前用户对底层 Agent 仍然拥有对应权限（consumer = `use`，studio_test = `edit`）。因此，旧的 surface token、preview id 或已创建 session 不再能绕过后续的 Agent 授权变更。
- ReAct / Channel runtime 对下挂 Tool / Skill 的解析已从“按当前终端用户的 Studio 可见性筛选”改为“按 Agent 已配置的 allowlist / Extension bundle 解析”：
  - manual Tool runtime 不再从当前终端用户自己的 `users/{username}/tools` 目录取可用工具，而是按 Agent allowlist 里的全局 tool name 查到对应 `ToolResource` 和 creator，再加载该 Tool 源码；
  - manual Skill runtime 不再要求当前终端用户同时拥有该 Skill 的 Studio `use`，而是按 Agent allowlist 里的全局 skill name 直接解析 registry row 和 sandbox mount；
  - extension-contributed Tool / Skill 继续只跟随 Agent 已绑定的 Extension bundle，不受最终用户 Studio `use` 影响。
- 因而，最终用户一旦拥有某个 Agent 的 `use`，运行该 Agent 时只看：
  - Agent 自身的 `use`
  - Agent 当前 pinned runtime config（release / studio_test snapshot / live config）
  - Agent 显式绑定的 Extension / Tool / Skill / Provider 配置
  而不会再因为当前终端用户没有底层实体的 Studio `use` 而把这些能力从 runtime 中过滤掉。

注意：

- 文件、数据库、缓存等持久层访问必须继续通过 service 层。
- Workspace/File 相关接口不能直接依赖前端传入路径判断权限，应先解析业务实体，再由 service 校验权限。
- 最终用户一旦拥有某个 Agent 的 `use`，该 Agent 运行时不会再递归要求用户同时拥有其下挂 LLM/Skill/Tool/Extension/Provider 的 Studio `use` 权限；底层实体权限只约束 Studio 配置期。

## 开放问题

1. builder 默认是否应该拥有 `llms.manage`、`extensions.manage`、`channels.manage`？

   这些权限涉及 secret、外部通道和 extension trust。建议第一版不默认给 builder，等产品使用反馈后再决定。

2. Agent 发布是否需要独立 permission？

   第一版可以归入 `agents.manage` + `agent.edit`。如果未来发布成为强治理动作，可以新增：

   ```text
   agents.publish
   ```

3. Operations Sessions 是否需要只读和 replay 分开？

   当前先用：

   ```text
   operations.view
   ```

   如果 Hook Replay、任务重放、强制取消等操作变多，再新增：

   ```text
   operations.manage
   ```

## 推荐结论

Pivot 第一版用户系统应采用：

```text
User + Role + Permission + Group + ResourceAccess
```

其中：

- Role 控制系统入口和模块能力。
- Permission catalog 由系统定义并 seed 入库。
- RolePermission 持久化，可在 Operations / Roles 中编辑。
- Group 只作为批量授权单位，不引入 Organization/Team 空间。
- 实体权限统一为 `use` 和 `edit`。
- FastAPI 使用 dependency 做系统权限控制，service 做实体权限判断。

这套模型足够简单，也能覆盖 Pivot 的 Studio、Client、Channel、Desktop 统一账号体系，并且可以从 Agent 开始逐步扩展到其他实体。
