# File Read Deduplication — Content Hash Tracking

## Problem

Agent 执行任务时经常重复读取同一文件（长对话中遗忘已读内容，或为了确认文件状态）。每次 `read_file` 将完整内容注入上下文窗口，导致上下文空间浪费甚至溢出。尤其是大文件（几百到上千行），重复读取一次就浪费大量 token。

## Goal

当 `read_file` 读取的文本文件在当前 session 中**已被读取过相同行范围**且内容 hash 未变化时，返回简短摘要而非完整内容，节省上下文空间。

## Design Decisions

| 决策 | 选择 | 原因 |
|------|------|------|
| Hash 算法 | MD5 (`usedforsecurity=False`) | 已有先例（`skill_service.py:180`），速度快，32 字符，非安全场景 |
| Hash 计算位置 | 在现有 sandbox read script 中计算 | 无需额外 sandbox 调用，开销可忽略 |
| 去重粒度 | **按行范围追踪** — 记录每个文件已读过的行范围 | 支持部分读取场景（读过大文件前 400 行，再读 401-800 时应正常返回） |
| 去重文件类型 | 仅文本文件 | 图片走 multimodal blocks，文档走 Docling，逻辑差异大 |
| 持久化 | Session 表新增 `react_file_read_tracker` 列（JSON TEXT） | 跨任务、跨引擎、分布式安全 |
| 失效策略 | compaction 时清空全部 | compaction 后 LLM 丢失文件详情，必须重新读取 |
| 文件修改后 | 无需额外处理 | 每次读取都重新计算 hash，修改后 hash 必然不同 |
| 强制读取 | `force_read` 参数 | Agent 可显式绕过去重 |

## Tracker Data Model

### 存储

在 `Session` 表新增 `react_file_read_tracker` 列，存储 JSON：

```json
{
  "relative/path/to/file.py": {
    "hash": "a1b2c3d4e5f6...",
    "total_lines": 1000,
    "read_ranges": [[1, 400], [401, 800]]
  },
  "another/file.md": {
    "hash": "f6e5d4c3b2a1...",
    "total_lines": 50,
    "read_ranges": [[1, 50]]
  }
}
```

- Key：workspace 相对路径（sandbox script 返回的 `path` 字段）
- `hash`：文件当前内容的 MD5 hex digest
- `total_lines`：文件总行数
- `read_ranges`：已读取过的行范围列表（闭区间 `[start, end]`，会自动合并相邻/重叠范围）

### 范围合并规则

每次记录新的读取范围时，与已有范围合并。例如：

```
已有: [[1, 400]]          → 读取 401-800 → [[1, 800]]       (相邻合并)
已有: [[1, 400], [600, 1000]] → 读取 350-650 → [[1, 1000]] (重叠合并)
已有: [[1, 200]]          → 读取 400-600 → [[1, 200], [400, 600]] (不重叠，独立)
```

### 去重判断逻辑

```
输入: path, start_line, end_line, current_hash, force_read

1. if force_read → 返回完整内容，更新 tracker
2. 加载 tracker，查找 path 对应的 entry
3. if entry 不存在 → 返回内容，记录范围
4. if entry.hash ≠ current_hash → 文件已变化，清空 read_ranges，返回内容，记录新范围
5. if entry.hash == current_hash:
   a. 检查 [start_line, end_line] 是否被 read_ranges 完全覆盖
   b. 如果完全覆盖 → 返回去重摘要
   c. 如果未完全覆盖 → 返回内容，合并新范围到 read_ranges
```

## Edge Cases

| 场景 | 处理 |
|------|------|
| 读取 lines 1-400，再读 lines 500-900（大文件，无重叠） | 两次都返回内容，各自记录范围 |
| 读取 lines 1-400，再读 lines 300-500（有重叠） | 第二次返回 300-500 内容（因为有新内容 401-500），合并范围为 [[1, 500]] |
| 读取 lines 1-400，再读 lines 1-400（完全重复） | 第二次返回去重摘要 |
| 文件被 write_file/edit_file/run_bash 修改 | hash 不同 → 清空 read_ranges，返回新内容，记录新范围 |
| context compaction 发生 | 清空整个 tracker |
| 图片 / 文档文件 | 不走去重逻辑 |
| 同 session 新 task | tracker 持久化在 Session 行，跨 task 保持（直到 compaction） |
| delegation（子 agent） | 子 agent 有独立 session，tracker 互不干扰 |
| session_id 为 None | 静默跳过去重（不报错） |
| 空文件（0 行） | 视为范围 [1, 0]（空），可去重 |
| force_read=true | 跳过去重，始终返回完整内容，更新 tracker |

## Implementation

### Step 1: Session Model — 新增列

**`server/app/models/session.py`** — 新增字段：

```python
react_file_read_tracker: str | None = Field(
    default=None,
    description=(
        "JSON dict tracking file content hashes and read ranges for dedup. "
        "Key: workspace-relative path, value: {hash, total_lines, read_ranges}. "
        "Cleared on context compaction."
    ),
)
```

**`server/app/db/session.py`** — `ensure_session_schema_compatibility()` 新增：

```python
if "react_file_read_tracker" not in columns:
    conn.execute(text("ALTER TABLE session ADD COLUMN react_file_read_tracker VARCHAR"))
```

### Step 2: Tracker Helper Module（新文件）

**`server/app/orchestration/tool/builtin/_file_read_tracker.py`**

纯函数式 helper：

```python
def load_tracker(session_id: str, db_session_factory) -> dict | None
    # 从 Session.react_file_read_tracker 加载 JSON dict

def save_tracker(session_id: str, db_session_factory, tracker: dict) -> None
    # 写回 Session.react_file_read_tracker

def check_dedup(tracker, path, content_hash, start_line, end_line) -> bool
    # hash 匹配 + [start_line, end_line] 被 read_ranges 完全覆盖

def record_read(tracker, path, content_hash, total_lines, start_line, end_line) -> dict
    # 更新/创建 entry，合并范围，返回更新后的 tracker

def clear_tracker(session_id: str, db_session_factory) -> None
    # 清空（compaction 时调用）
```

范围合并 helper：

```python
def _merge_ranges(ranges: list[list[int]], new_start: int, new_end: int) -> list[list[int]]
    # 将 [new_start, new_end] 合并进 ranges，处理相邻和重叠
```

范围覆盖检查 helper：

```python
def _is_range_covered(ranges: list[list[int]], start: int, end: int) -> bool
    # 合并后检查 [start, end] 是否被完全覆盖
```

### Step 3: Sandbox Read Script — 增加 hash 计算

**`server/app/orchestration/tool/builtin/read_file.py`** — `_READ_FILE_SCRIPT`：

在 `text = path.read_text(...)` 之后加：

```python
import hashlib
content_hash = hashlib.md5(text.encode("utf-8", errors="replace"), usedforsecurity=False).hexdigest()
```

在 empty-file payload 和 normal payload 中都加 `"content_hash": content_hash`。

### Step 4: read_file 函数 — 增加 force_read 参数 + 去重逻辑

**`server/app/orchestration/tool/builtin/read_file.py`** — `read_file()` 函数：

**新增参数**：

```python
force_read: Annotated[
    bool,
    Param("If true, always return full content, bypassing dedup. Use when you need to confirm current file state.")
] = False,
```

**去重逻辑**（在 `file_type == "text" or "unknown"` 分支，调用 `_read_text_in_sandbox()` 之后）：

```python
if file_type == "text" or file_type == "unknown":
    # ... existing validation ...
    result = _read_text_in_sandbox(path, start_line, max_lines)

    # Dedup check for text reads
    ctx = get_current_tool_execution_context()
    if ctx and ctx.session_id and ctx.db_session_factory and not force_read:
        content_hash = result.get("content_hash", "")
        relative_path = result.get("path", path)
        actual_start = result["start_line"]
        actual_end = result["end_line"]

        tracker = load_tracker(ctx.session_id, ctx.db_session_factory) or {}

        if check_dedup(tracker, relative_path, content_hash, actual_start, actual_end):
            return _build_dedup_summary(relative_path, result, content_hash)

        # Record this read
        record_read(tracker, relative_path, content_hash,
                    result["total_lines"], actual_start, actual_end)
        save_tracker(ctx.session_id, ctx.db_session_factory, tracker)

    return result
```

**去重摘要函数**：

```python
def _build_dedup_summary(path: str, result: dict, content_hash: str) -> dict:
    start = result["start_line"]
    end = result["end_line"]
    range_desc = f"lines {start}-{end}" if start != 1 or end != result["total_lines"] else f"{result['total_lines']} lines (full file)"
    return {
        "path": path,
        "total_lines": result["total_lines"],
        "start_line": start,
        "end_line": end,
        "returned_line_count": 0,
        "has_more_before": False,
        "has_more_after": False,
        "truncated": False,
        "next_start_line": None,
        "previous_start_line": None,
        "content": (
            f"[File unchanged since last read — content already in context]\n"
            f"Path: {path}\n"
            f"Range: {range_desc}\n"
            f"Hash: {content_hash[:8]}...\n\n"
            f"If you need the full content, call read_file with force_read=true."
        ),
        "deduped": True,
        "content_hash": content_hash,
    }
```

### Step 5: write_file — 写入时记录 hash

**`server/app/orchestration/tool/builtin/write_file.py`**

`write_file` 写入的内容 Agent 完全已知（它刚生成的），等同于完整读取。

1. 在 Python 进程中直接计算 hash（不需要额外 sandbox 调用）：
```python
import hashlib
content_hash = hashlib.md5(content.encode("utf-8"), usedforsecurity=False).hexdigest()
```

2. 写入成功后，记录到 tracker：
```python
ctx = get_current_tool_execution_context()
if ctx and ctx.session_id and ctx.db_session_factory:
    tracker = load_tracker(ctx.session_id, ctx.db_session_factory) or {}
    total_lines = content.count("\n") + (0 if content.endswith("\n") else 1)
    record_read(tracker, relative_path, content_hash, total_lines, 1, total_lines)
    save_tracker(ctx.session_id, ctx.db_session_factory, tracker)
```

3. 返回值改为包含 hash 的 dict：
```python
return {
    "message": f"Wrote file: {relative_path}",
    "path": relative_path,
    "content_hash": content_hash,
    "total_lines": total_lines,
}
```

### Step 6: edit_file — 编辑后更新 hash

**`server/app/orchestration/tool/builtin/edit_file.py`**

`edit_file` 只修改了部分行，Agent 不拥有完整文件内容，所以：
- 更新 hash（以便后续 read_file 检测变化）
- **清空 read_ranges**（因为 Agent 只知道 diff 部分，不等于完整读取）

在 `_EDIT_FILE_SCRIPT` 中，文件已经在内存中（`updated_lines`），加一行 hash 计算：
```python
import hashlib
final_text = "".join(updated_lines)
payload["content_hash"] = hashlib.md5(final_text.encode("utf-8"), usedforsecurity=False).hexdigest()
payload["total_lines"] = len(updated_lines)
```

在 `edit_file()` 函数中，sandbox 执行成功后：
```python
ctx = get_current_tool_execution_context()
if ctx and ctx.session_id and ctx.db_session_factory:
    tracker = load_tracker(ctx.session_id, ctx.db_session_factory) or {}
    relative_path = payload.get("path", path)
    content_hash = payload.get("content_hash", "")
    total_lines = payload.get("total_lines", 0)
    # edit only updates hash, clears ranges (agent doesn't have full file in context)
    tracker[relative_path] = {"hash": content_hash, "total_lines": total_lines, "read_ranges": []}
    save_tracker(ctx.session_id, ctx.db_session_factory, tracker)
```

### Step 8: Compaction 时清空 Tracker

**`server/app/services/react_runtime_service.py`** — `replace_runtime_messages()` 和 `replace_session_runtime_messages()`：

在设置 `compact_result` 后：

```python
if compact_result is not None:
    session.react_file_read_tracker = "{}"
```

### Step 9: Engine Result Compaction（可选）

**`server/app/orchestration/react/engine.py`** — `_compact_result_for_llm()`：

为 `"read_file"` 和 `"write_file"` 添加 strip 规则，去掉 `content_hash` 和 `deduped` 字段（LLM 不需要看到内部元数据）。

### Step 10: Debug 面板 — Files Tab

#### Backend: 在 runtime-debug 响应中包含 tracker 数据

**`server/app/services/react_runtime_service.py`** — `build_runtime_debug_payload()`：

在返回的 payload dict 中增加 `file_read_tracker` 字段，直接从 `session.react_file_read_tracker` 读取并解析为 dict。

**`server/app/schemas/react.py`** — `ReactSessionRuntimeDebugResponse`：

新增字段：
```python
file_read_tracker: dict[str, Any] | None = None
```

#### Frontend: CompactDebugButton 增加 "Files" tab

**`web/src/components/ReactChatInterface.tsx`** — `CompactDebugButton`：

- `activeTab` 类型扩展为 `"compact" | "surface" | "files"`
- `TabsList` 从 `grid-cols-2` 改为 `grid-cols-3`，新增 `<TabsTrigger value="files">Files</TabsTrigger>`
- 新增 `<TabsContent value="files">` 内容区：

展示当前 session 的 file read tracker 状态：
- 表格或列表，每行显示：文件路径、MD5（前 8 位）、已读范围（如 `1-400, 500-900`）、总行数
- 空状态：`No files tracked yet`
- 数据来源：`debugState.runtimeDebug?.file_read_tracker`

## Files to Modify

| File | Change |
|------|--------|
| `server/app/models/session.py` | 新增 `react_file_read_tracker` 字段 |
| `server/app/db/session.py` | schema compat: ALTER TABLE ADD COLUMN |
| `server/app/orchestration/tool/builtin/_file_read_tracker.py` | **新建** — tracker helper + 范围合并/覆盖检查 |
| `server/app/orchestration/tool/builtin/read_file.py` | sandbox script 加 hash；`read_file()` 加 `force_read` 参数 + 去重逻辑 |
| `server/app/orchestration/tool/builtin/write_file.py` | 写入后计算 hash，记录到 tracker，返回 hash |
| `server/app/orchestration/tool/builtin/edit_file.py` | sandbox script 加 hash；编辑后更新 tracker（hash 更新，清空 ranges） |
| `server/app/services/react_runtime_service.py` | compaction 时清空 tracker |
| `server/app/orchestration/react/engine.py` | (可选) `_compact_result_for_llm` strip `content_hash`/`deduped` |
| `server/tests/orchestration/test_read_file_tool.py` | 新增去重和范围追踪测试 |
| `server/app/schemas/react.py` | `ReactSessionRuntimeDebugResponse` 新增 `file_read_tracker` 字段 |
| `web/src/components/ReactChatInterface.tsx` | Debug 面板新增 "Files" tab 展示 tracker 状态 |

## Verification

1. **完整重复读取**：读取文件两次（相同范围）→ 第二次返回去重摘要
2. **部分读取不重叠**：读取 lines 1-400，再读 500-900 → 两次都返回内容
3. **部分读取重叠**：读取 lines 1-400，再读 300-500 → 第二次返回内容（有新内容 401-500）
4. **文件修改**：修改文件后读取 → hash 不同，返回新内容
5. **Compaction 后**：触发 compaction 后读取同一文件 → 返回完整内容
6. **force_read**：用 `force_read=true` 读取已读文件 → 返回完整内容
7. **图片/文档**：不受影响
8. **Lint/Type check**：`podman compose exec backend poetry run ruff check server --fix && podman compose exec backend poetry run pyright server`
