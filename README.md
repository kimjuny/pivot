# Pivot

一个基于 FastAPI + SQLModel 的 Agent 场景可视化系统，支持 Agent 与场景图（Scene Graph）的交互。

## 项目结构

```
pivot/
├── core/                    # 核心业务逻辑层
│   ├── agent/              # Agent 相关逻辑
│   ├── plan/               # 场景图规划
│   │   ├── __init__.py
│   │   ├── connection.py
│   │   ├── scene.py
│   │   └── subscene.py
│   └── llm/                # 大语言模型集成
│       ├── __init__.py
│       ├── abstract_llm.py
│       └── doubao_llm.py
│   └── utils/               # 工具类
│       ├── __init__.py
│       └── logging_config.py
├── server/                  # 后端服务层
│   ├── alembic/            # Alembic 自动生成的数据库迁移脚本
│   ├── app/                # FastAPI 应用
│   │   ├── __init__.py     # 入口文件：初始化 FastAPI 实例
│   │   ├── main.py             # 主应用：初始化 FastAPI 实例
│   │   ├── core/              # 关键：读取 .env 环境变量（DATABASE_URL）
│   │   ├── config.py       # 关键：读取 .env 环境变量（DATABASE_URL）
│   │   └── security.py     # 安全相关（JWT, 加密）
│   │   ├── db/                # 数据库层
│   │   │   ├── session.py      # 关键：创建引擎 (Engine) 和会话 (Session)
│   │   │   └── base.py         # 导入所有 SQLModel 模型，方便 Alembic 识别
│   │   ├── models/             # 存放数据库模型定义
│   │   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── scene.py
│   │   └── subscene.py
│   │   ├── schemas/            # 存放 Pydantic 模型（非 SQLModel 场景下使用）
│   │   ├── agent.py
│   │   ├── scene.py
│   │   └── subscene.py
│   │   ├── api/                # 路由层
│   │   ├── v1/ 
│   │   │   ├── api.py 
│   │   │   └── endpoints/ 
│   │   │       ├── agents.py      # Agent 相关的 CRUD 接口
│   │   │       ├── scenes.py      # Scene 和 Subscene 相关的 CRUD 接口
│   │   │       └── crud/               # 增删改查逻辑（封装具体的数据库操作）
│   │   │       ├── agent.py
│   │   │       ├── scene.py
│   │   │       └── connection.py
│   ├── .env                    # 关键：存储数据库连接字符串
│   ├── alembic.ini             # Alembic 配置文件
│   ├── requirements.txt
│   └── websocket.py           # WebSocket 连接管理
├── web/                     # 前端 React 应用
│   ├── src/
│   │   ├── components/       # React 组件
│   │   │   ├── AgentVisualization.jsx  # 场景图可视化组件
│   │   │   ├── ChatInterface.jsx       # 聊天界面组件
│   │   │   └── EditPanel.jsx           # 编辑面板组件
│   │   ├── store/            # 状态管理（Zustand）
│   │   │   └── agentStore.js
│   │   └── utils/           # 工具函数
│   │       ├── api.js
│   │       └── websocket.js
│   ├── App.jsx
│   ├── index.css
│   ├── main.jsx
│   ├── package.json
│   ├── postcss.config.js
│   ├── tailwind.config.js
│   ├── vite.config.js
│   └── index.html
├── .gitignore
├── ARCHITECTURE.md
├── README.md
└── start.sh                  # 启动脚本
```

## 技术栈

### 后端

- **FastAPI**: 现代、高性能的 Python Web 框架
- **SQLModel**: 既是 ORM（操作数据库），又是 Pydantic 模型（验证数据）。这意味着你不需要写两套类，极大减少了代码冗余。
- **Alembic**: 它是 SQLAlchemy 的迁移工具。通过它，你不需要手动在数据库里建表，它会自动探测代码的变化并生成迁移脚本，无论目标是 SQLite 还是 Postgres。
- **Pydantic**: 用于 API 请求和响应的数据验证
- **SQLAlchemy**: Python SQL 工具包和 ORM
- **WebSocket**: 实时通信支持

### 前端

- **React**: 现代 UI 框架
- **React Flow**: 流程图可视化库
- **Tailwind CSS**: 实用优先的 CSS 框架
- **Vite**: 快速的构建工具
- **Zustand**: 轻量级状态管理

## 数据库设计

### 核心实体

#### Agent

- `id`: 主键
- `name`: Agent 名称
- `api_key`: LLM API 密钥
- `created_at`: 创建时间
- `updated_at`: 更新时间

#### Scene

- `id`: 主键
- `name`: 场景名称
- `description`: 场景描述
- `created_at`: 创建时间
- `updated_at`: 更新时间
- `agent_id`: 外键，关联到 Agent

#### Subscene

- `id`: 主键
- `name`: 子场景名称
- `type`: 类型（start, normal, end）
- `state`: 状态（active, inactive）
- `description`: 描述
- `mandatory`: 是否必须执行
- `objective`: 目标
- `created_at`: 创建时间
- `updated_at`: 更新时间
- `scene_id`: 外键，关联到 Scene

#### Connection

- `id`: 主键
- `name`: 连接名称
- `condition`: 转换条件
- `from_subscene`: 源子场景名称
- `to_subscene`: 目标子场景名称
- `created_at`: 创建时间
- `updated_at`: 更新时间
- `from_subscene_obj`: 外键，关联到源 Subscene
- `to_subscene_obj`: 外键，关联到目标 Subscene

## API 接口

### Agent 相关

- `POST /api/v1/agents` - 创建 Agent
- `GET /api/v1/agents` - 获取所有 Agent
- `GET /api/v1/agents/{agent_id}` - 获取指定 Agent
- `PUT /api/v1/agents/{agent_id}` - 更新 Agent
- `DELETE /api/v1/agents/{agent_id}` - 删除 Agent

### Scene 相关

- `POST /api/v1/scenes` - 创建 Scene
- `GET /api/v1/scenes` - 获取所有 Scene
- `GET /api/v1/scenes/{scene_id}` - 获取指定 Scene
- `PUT /api/v1/scenes/{scene_id}` - 更新 Scene
- `DELETE /api/v1/scenes/{scene_id}` - 删除 Scene
- `GET /api/v1/scenes/{scene_id}/subscenes` - 获取 Scene 的所有 Subscene

### Subscene 相关

- `POST /api/v1/scenes/{scene_id}/subscenes` - 创建 Subscene
- `PUT /api/v1/subscenes/{subscene_id}` - 更新 Subscene
- `DELETE /api/v1/subscenes/{subscene_id}` - 删除 Subscene
- `GET /api/v1/subscenes/{subscene_id}` - 获取指定 Subscene

### Connection 相关

- `GET /api/v1/subscenes/{subscene_id}/connections` - 获取 Subscene 的所有连接
- `POST /api/v1/subscenes/{subscene_id}/connections` - 创建 Connection
- `PUT /api/v1/connections/{connection_id}` - 更新 Connection
- `DELETE /api/v1/connections/{connection_id}` - 删除 Connection

### WebSocket

- `/ws` - WebSocket 端点，用于实时通信和状态更新

## 环境变量

在项目根目录创建 `.env` 文件：

```bash
# 数据库连接（开发环境默认使用 SQLite）
DATABASE_URL=sqlite:///./pivot.db

# 生产环境使用 PostgreSQL
# DATABASE_URL=postgresql://user:password@localhost:5432/pivot

# LLM API 密钥
DOUBAO_SEED_API_KEY=your_api_key_here
```

## 安装依赖

```bash
cd server
pip install -r requirements.txt
```

## 启动项目

### 开发环境

```bash
./start.sh --dev
```

### 生产环境

```bash
./start.sh --prod
```

## 开发环境

开发环境默认使用 SQLite 数据库，生产环境使用 PostgreSQL 数据库。

### 数据库迁移

Alembic 会自动探测 `app/models/` 下的 SQLModel 模型变化，并生成相应的迁移脚本。

首次启动时，数据库会自动初始化，创建所有必要的表结构。

## 项目特性

### 数据层

- 使用 SQLModel 统一 ORM 和 Pydantic 验证
- 使用 Alembic 自动管理数据库迁移
- 支持 SQLite 和 PostgreSQL 数据库
- 自动创建表结构，无需手动建表

### API 层

- RESTful API 设计
- 完整的 CRUD 操作
- 统一的响应格式
- WebSocket 实时通信支持

### 前端

- React Flow 流程图可视化
- 实时状态更新
- 响应式设计
- 编辑功能（节点和边的属性编辑）

### 启动脚本

- 支持开发和生产环境切换
- 自动端口管理
- 优雅的进程停止

## 注意事项

1. **数据库初始化**：首次启动时会自动初始化数据库，创建所有必要的表结构
2. **环境变量**：确保 `.env` 文件中配置了 `DOUBAO_SEED_API_KEY`
3. **端口占用**：确保 8003（后端）和 3003（前端）端口未被占用
4. **CORS 配置**：开发环境允许所有来源，生产环境应配置具体的允许来源
5. **日志监控**：查看 `server/app/main.py` 中的日志配置，确保正确记录

## 开发指南

### 添加新的 Agent

1. 在数据库中创建 Agent 记录
2. 通过 API 调用 `/api/v1/agents` 创建 Agent
3. 在前端界面中配置 Agent 的 API 密钥

### 添加新的场景图

1. 创建 Scene 记录
2. 创建 Subscene 记录
3. 创建 Connection 记录
4. 通过 API 调用 `/api/v1/scenes` 创建 Scene

### 修改场景图

1. 通过 API 调用 `/api/v1/scenes/{scene_id}` 更新 Scene
2. 通过 API 调用 `/api/v1/scenes/{scene_id}/subscenes` 创建/更新 Subscene
3. 通过 API 调用 `/api/v1/scenes/{scene_id}/subscenes/{subscene_id}/connections` 创建/更新 Connection

## 故障排查

### 后端无法启动

- 检查端口 8003 是否被占用：`lsof -ti:8003`
- 检查 `.env` 文件是否存在且配置正确
- 查看日志输出了解具体错误

### 前端无法启动

- 检查端口 3003 是否被占用：`lsof -ti:3003`
- 确保已安装依赖：`npm install`
- 查看浏览器控制台了解具体错误

### 数据库连接失败

- 检查 `DATABASE_URL` 环境变量是否正确
- 确保数据库服务正在运行（PostgreSQL 或 SQLite）
- 查看数据库迁移是否成功执行

## 许可证

本项目仅供学习和演示使用。
