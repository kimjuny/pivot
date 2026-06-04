# File Tools 稳定性改造设计

## 背景

Pivot 当前内置文件工具包括：

- `read_file`: 读取 `/workspace` 下文件，文本文件返回分页内容，并记录 session 级 read tracker。
- `write_file`: 直接写入/覆盖 UTF-8 文本文件，并把写入后的文件记录为已读。
- `edit_file`: 接收 simplified unified diff，由工具解析 hunk 后按行号和上下文应用。

现在最不稳定的是 `edit_file`。根因不是 patch parser 不够努力，而是 unified diff 对 LLM 来说输出约束太多：hunk header、行号、old/new count、空行 prefix、上下文范围、CRLF 等任一出错都会导致失败。当前实现已经做了小范围 anchor 修正和换行兼容，但仍然是在补救一个天然易错的工具协议。

Claude Code 的稳定模式值得借鉴：`Edit` 不让模型直接写 diff，而是让模型提交 `old_string/new_string/replace_all`，工具内部做精确字符串替换，diff 只作为展示/审查产物生成。

## 设计目标

1. 稳定优先：减少模型需要手写的结构化文本，避免 unified diff 格式错误。
2. 简洁优先：删除 patch parser、hunk apply、行号锚点等复杂分支。
3. 安全覆盖：编辑/覆盖已有文件前，必须读过当前版本，避免覆盖用户或 formatter 的并发修改。
4. token 友好：`read_file` 默认不返回行号，直接返回可复制到 `old_string` 的原文。
5. 面向未来：状态记录通过 service 层，支持多实例/分布式场景下的 session 级一致性判断。

## Claude Code 模式总结

### Read

`Read` 的 `offset` 和 `limit` 是可选参数，不需要用户或模型必须输入范围。

源码 prompt 声称默认最多读取 2000 行，但当前实现路径里 `limit` 不填时传入 `undefined`，底层 reader 实际更接近读取整文件，主要受文件大小和 token 上限约束。

这个不一致点不建议照搬到 Pivot。Pivot 应该明确自己的行为：默认读取固定上限行数，并返回分页 metadata。

### Edit

Claude Code 的 `Edit` 输入：

```json
{
  "file_path": "/abs/path/file.py",
  "old_string": "exact text to replace",
  "new_string": "replacement text",
  "replace_all": false
}
```

核心规则：

- 编辑前必须读过文件。
- 文件读后如果被修改，编辑失败，要求重新读取。
- `old_string` 必须存在。
- `replace_all=false` 时，`old_string` 必须唯一。
- `replace_all=true` 时，替换所有出现位置。
- 工具内部生成 diff 用于 UI/审计，不让模型手写 diff。

### Write

`Write` 用于创建新文件或完整重写。覆盖已有文件前也要求先读过文件，并确认文件没有在读后发生变化。

## Pivot 当前问题

### read_file

改造前文本读取返回形如：

```text
1 | import os
2 | from pathlib import Path
```

这对 diff hunk 有帮助，但对 `old_string/new_string` 模式反而是噪音：

- 增加 token。
- 模型容易把 `N | ` 前缀复制进 `old_string`。
- prompt 需要额外提醒“不要包含行号前缀”。

另一个需要避免的问题是“重复读取去重”：如果 `read_file` 因为 tracker 里已有相同 hash/range 就返回短摘要，会破坏 Agent 主动重新对齐文件内容的能力。`read_file` 的语义应该非常直接：只要 Agent 调用，就返回当前文件内容片段。

### edit_file

当前 `edit_file(diff=...)` 的失败面过大：

- hunk header 行号不准。
- hunk count 与正文不一致。
- 空行漏写前导空格。
- 多文件 diff metadata 混入。
- 上下文不唯一或漂移。
- CRLF/LF 处理复杂。

这些复杂逻辑最终只是为了把 diff 转回“旧内容片段 -> 新内容片段”。应直接把工具协议改成字符串替换。

### write_file

当前 `write_file` 会直接覆盖已有文件，没有“必须先读过当前版本”的保护。稳定性和协作安全性不如 Claude Code。

## 新工具协议

### read_file

建议签名：

```python
def read_file(
    path: str,
    start_line: int = 1,
    max_lines: int = 1200,
    show_line_numbers: bool = False,
) -> dict[str, object]:
    ...
```

默认行为：

- `start_line` 可选，默认 1。
- `max_lines` 可选，默认 1200。
- `max_lines` 上限建议 2000。
- `show_line_numbers` 默认 `False`。
- `content` 默认返回原文，不带行号。
- 保留 `total_lines/start_line/end_line/has_more_after/next_start_line/content_hash` 等 metadata。
- 每次调用都返回当前内容片段；即使同一 session 中已经读过相同 range/hash，也不返回“已读过”的短摘要。
- 读取成功后只在后台记录 `hash/total_lines/read_ranges`，用于后续 edit/write 的安全校验和 debug 展示。

返回示例：

```json
{
  "path": "src/app.py",
  "total_lines": 2400,
  "start_line": 1,
  "end_line": 1200,
  "returned_line_count": 1200,
  "has_more_before": false,
  "has_more_after": true,
  "next_start_line": 1201,
  "content_hash": "md5...",
  "content": "原始文件内容片段"
}
```

当 `show_line_numbers=true` 时才返回带行号内容，用于定位或人工阅读。

### edit_file

建议签名：

```python
def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> dict[str, object]:
    ...
```

行为规则：

1. `old_string == new_string` 直接失败。
2. 文件不存在且 `old_string != ""` 时失败。
3. 文件不存在且 `old_string == ""` 时创建新文件。
4. 文件存在且 `old_string == ""` 时只允许空文件，否则失败，避免误把创建当覆盖。
5. 编辑已有文件前，必须在当前 session 内读过该文件的完整当前版本。
6. 如果当前文件 hash 与 tracker 记录不一致，失败并提示重新 `read_file`。
7. 精确匹配 `old_string`。
8. 如果找不到，失败并返回短错误。
9. 如果匹配多次且 `replace_all=false`，失败并提示增加上下文或设置 `replace_all=true`。
10. 替换成功后写回文件，并记录新的 hash/total_lines 为已读状态。

返回示例：

```json
{
  "message": "Edited file: src/app.py",
  "path": "src/app.py",
  "replacement_count": 1,
  "content_hash": "md5...",
  "total_lines": 123,
  "old_string_found": true
}
```

### write_file

建议签名保持不变：

```python
def write_file(path: str, content: str) -> dict[str, object]:
    ...
```

行为规则：

- 新文件：允许直接创建。
- 已有文件：必须先完整读取当前版本。
- 如果读后文件发生变化，失败并提示重新读取。
- 写入成功后，记录新 hash/total_lines 为已读状态。

`write_file` 只用于创建新文件或完整重写。修改已有文件时优先使用 `edit_file`。

## Files / Tracker 原则

`Files` 清单必须保留。它是 Pivot 版的 Claude Code `readFileState`，只是：

- Claude Code 的状态主要在进程内存里。
- Pivot 的状态持久化在 Session 的 `react_file_read_tracker` 里。
- Claude Code 主要用 `mtime` 判断新鲜度。
- Pivot 用 `content_hash` 判断新鲜度。

这个清单的定位是：

- 后台安全账本：证明 Agent 在当前 session 里读过哪个版本、哪些范围。
- edit/write 的乐观并发保护：写入前确认当前文件仍是 Agent 读过的版本。
- debug 面板数据源：展示 path、hash、total_lines、read_ranges，帮助判断为什么某次 edit/write 被允许或拒绝。

这个清单**不是**：

- `read_file` 的缓存。
- token 节省机制。
- 用来阻止 Agent 主动重复阅读文件内容的依据。

因此：

- `read_file` 每次都返回内容。
- Files 面板可以继续展示 `Read L1-428` 这类范围信息，便于 debug。
- 这些范围信息只影响 edit/write 是否具备“完整读过”的安全前置条件，不影响 read_file 输出。

## Tracker 改造

当前 `FileReadTrackerService` 只记录：

```json
{
  "path": {
    "hash": "...",
    "total_lines": 100,
    "read_ranges": [[1, 100]]
  }
}
```

建议保留字段，并增加语义方法，而不是另起 service：

```python
record_read(...)
record_full_file_state(...)
get_file_state(...)
require_current_full_read(...)
```

`require_current_full_read` / `require_full_read_hash` 的职责：

- 找到 session tracker entry。
- 确认 entry 覆盖完整文件。
- 返回该 entry 的 hash，供写入工具和当前文件 hash 对比。
- 不满足时抛出面向模型的清晰错误。

完整读取定义：

- `total_lines == 0` 且 hash 一致。
- 或 `read_ranges` 覆盖 `[1, total_lines]`。
- `write_file/edit_file` 成功后应记录 `[1, total_lines]`。

说明：不需要为了兼容旧 tracker 写大量迁移逻辑。本项目尚未上线，可以接受清空数据库重建。

## Compact 与 Files 清空

当 runtime context compact 成功后，必须清空 `react_file_read_tracker`。

原因：

- compact 后，模型上下文里的原始文件内容可能已经被摘要替代。
- 摘要不能作为 `old_string` 的可靠来源。
- 继续保留 Files 会让 edit/write 误以为 Agent 仍然完整掌握当前文件内容。

因此 compact 成功后的行为应是：

```text
compact success
  -> clear react_file_read_tracker
  -> Files debug 面板为空
  -> 后续 edit_file/write_file 修改已有文件前必须重新 read_file
```

这个设计比“把 Files 写进 compact 摘要里继续信任”更安全。compact 摘要可以描述“曾经读过/改过哪些文件”的事实，但不能恢复 edit/write 所需的精确文件上下文。

## mtime vs hash

Claude Code 主要用文件修改时间 `mtime` 作为 read state 的新鲜度标识，并在一些场景下用内容比较兜底。这个方案的优点是便宜：`stat` 一次就能判断文件是否可能变化，不需要每次读完整文件计算 hash。

Pivot 当前用 `md5(content)`。对 Pivot 来说，hash 更适合作为主标识：

- 更准确：mtime 可能因为文件系统精度、容器挂载、对象存储同步、formatter touch、跨实例时钟差异而出现误判。
- 更适合分布式：Pivot 需要兼顾 k8s、多实例、SeaweedFS/WebDAV/本地挂载等持久层，mtime 在不同 backend 上语义不一定完全一致。
- 更贴合现有实现：read tracker 已经存 `hash/total_lines/read_ranges`，继续扩展即可，不需要引入另一套状态。
- 成本可接受：`edit_file/write_file` 本来就要读取当前内容才能替换或覆盖；计算 hash 不会引入额外数量级成本。`read_file` 也已经读取内容并计算 hash。

建议决策：

- 只用 `content_hash` 作为一致性判断依据。
- `require_current_full_read` 用当前文件 hash 对比 tracker hash。
- 不记录、不比较、不返回 `mtime`，避免引入额外机制和分支。
- 如果未来真的遇到超大文件性能瓶颈，再单独设计优化；当前不要预留复杂性。

建议 tracker entry：

```json
{
  "hash": "md5...",
  "total_lines": 100,
  "read_ranges": [[1, 100]]
}
```

Session 的文件清单不是冗余数据，而是文件工具稳定性的核心状态。它服务于：

- `edit_file/write_file` 防陈旧写入：已有文件必须先完整读过，且当前 hash 与 tracker hash 一致，才允许修改或覆盖。
- debug 展示：让开发者看到当前 session 认为哪些文件是已知版本，以及读过哪些范围。

它不服务于 `read_file` 去重。`read_file` 被调用时必须返回内容。

## Diff 展示设计

改成 `old_string/new_string` 替换协议后，前端仍然可以保持现在的 diff 交互效果。关键是区分“工具输入协议”和“UI 展示协议”：

- 工具输入协议：模型提交 `old_string/new_string/replace_all`。
- UI 展示协议：工具执行后由后端基于 `original_content/updated_content` 生成 unified diff。

也就是说，不让模型写 diff，但系统仍然生成 diff。

### 后端返回字段

`edit_file` 成功后建议返回：

```json
{
  "message": "Edited file: src/app.py",
  "path": "src/app.py",
  "replacement_count": 1,
  "added_lines": 3,
  "removed_lines": 1,
  "diff": "@@ -10,7 +10,9 @@\n ...",
  "content_hash": "md5...",
  "total_lines": 123
}
```

`write_file` 覆盖已有文件成功后也可以返回 `diff`：

```json
{
  "message": "Wrote file: src/app.py",
  "path": "src/app.py",
  "type": "update",
  "added_lines": 20,
  "removed_lines": 18,
  "diff": "@@ -1,20 +1,22 @@\n ...",
  "content_hash": "md5...",
  "total_lines": 123
}
```

新文件创建时可以选择：

- 返回全量 added diff。
- 或保持当前 `write_file` content preview。

建议先保持当前 `write_file` preview 体验，新文件不强制生成 diff，避免大文件创建时 UI 过重。

### diff 生成位置

建议在 sandbox script 内或 server wrapper 内生成 unified diff。

优先方案：在 sandbox script 内完成。

原因：

- script 已经有 old/new 两份内容。
- 避免把完整 old/new content 传回 server 只为生成 diff。
- Python 标准库 `difflib.unified_diff` 足够满足当前前端 `parseUnifiedDiffLines`。

生成格式建议：

```python
import difflib

diff = "".join(
    difflib.unified_diff(
        original_text.splitlines(keepends=True),
        updated_text.splitlines(keepends=True),
        fromfile=f"a/{relative_path}",
        tofile=f"b/{relative_path}",
        n=3,
    )
)
```

注意：当前前端 `ToolDiffPreview` 已能解析 unified diff。改造后只需要把 `edit_file` 的 preview 数据源从“工具入参 `diff`”改成：

1. 如果工具结果里有 `diff`，展示结果 `diff`。
2. 如果工具还在 running，展示 `old_string/new_string` 的轻量 preview，或显示 `Waiting for generated diff...`。
3. summary 里的 `+N/-N` 优先使用工具结果的 `added_lines/removed_lines`；running 阶段可用 `old_string/new_string` 粗略估算。

这样前端交互不会丢，只是从“模型写的可能错误 diff”升级为“系统根据真实落盘结果生成的 diff”。这反而更可信。

### 前端改造点

当前 `RecursionCard` 里 `edit_file` preview 从参数 `diff` 取值。改造后：

- `edit_file` running 阶段：读取 `old_string/new_string/replace_all`，展示简短替换摘要。
- `edit_file` completed 阶段：从 `result.result.diff` 渲染 `ToolDiffPreview`。
- `countDiffLines` 仍可复用。
- `parseUnifiedDiffLines` 和 `ToolDiffPreview` 仍可复用。

这是一处数据来源调整，不需要重写 diff UI。

## 读写脚本设计

为了保持 sandbox 隔离，文件实际读写仍在 sandbox 内执行。

建议新增/调整小型 sandbox script：

### read text script

输入：`path/start_line/max_lines/show_line_numbers`

输出：

- 原文片段。
- hash。
- total_lines。
- start/end。
- pagination metadata。

### inspect text script

输入：`path`

输出：

- exists/is_dir。
- full content hash。
- total_lines。
- content，可选用于 edit/write 内部替换。

也可以直接在 `edit_file` 的 script 内读取当前内容、计算 hash、替换、写回，避免多次 sandbox round trip。

### edit text script

输入：`path/old_string/new_string/replace_all`

职责：

- 读取当前文件。
- 做精确字符串替换。
- 保持原文件换行，不按行重建。
- 写回。
- 输出新 hash、line count、replacement_count。

注意：staleness 检查最好在服务层先做一次，再在 sandbox script 内以当前内容为准替换。由于 sandbox exec 是单次进程，实际替换过程内部没有额外 await，已经足够接近原子读改写。

## Prompt 文案建议

### read_file

```text
Read a UTF-8 file under /workspace.
By default, returns raw file content without line numbers so it can be copied directly into edit_file.old_string.
Use start_line/max_lines to page through large files.
Set show_line_numbers=true only when line numbers are needed for navigation.
```

### edit_file

```text
Performs exact string replacements in a UTF-8 file under /workspace.
Always call read_file on the target file before editing an existing file.
Copy old_string exactly from read_file.content.
old_string must be unique unless replace_all=true.
Do not provide unified diffs or line numbers.
```

### write_file

```text
Write UTF-8 text to a file under /workspace.
Use this for new files or complete rewrites.
For existing files, call read_file first; the tool will fail if the file changed after reading.
Prefer edit_file for small modifications.
```

## 删除内容

改造后可以删除：

- `edit_file.py` 中 unified diff parser。
- hunk header parser。
- nearby anchor search。
- diff body materialization。
- simplified unified diff prompt。
- 旧的 diff 格式测试。

保留或新增：

- 字符串替换测试。
- 多匹配失败测试。
- `replace_all=true` 测试。
- 未读先编辑失败测试。
- 读后文件变化失败测试。
- 空文件/新文件创建测试。
- CRLF 保持测试。

## 验证标准

### 单元测试

新增/调整测试：

1. `read_file` 默认不返回行号。
2. `read_file(show_line_numbers=True)` 返回行号。
3. `read_file` 默认最多返回 `max_lines`，并给出 `next_start_line`。
4. `edit_file` 精确替换唯一字符串成功。
5. `edit_file` 多匹配且 `replace_all=false` 失败。
6. `edit_file(replace_all=true)` 替换全部。
7. `edit_file` 未读已有文件失败。
8. `edit_file` 读后 hash 变化失败。
9. `write_file` 创建新文件成功。
10. `write_file` 覆盖已有文件前未读失败。
11. `write_file` 覆盖读后未变文件成功。

### Podman 检查

按项目规则，提交前执行：

```bash
podman compose exec backend poetry run ruff check server --fix
podman compose exec backend poetry run ruff format server
podman compose exec backend poetry run pyright server
```

如果前端未改，不需要跑 frontend 检查。

## 建议实施顺序

1. 改 `FileReadTrackerService`，增加 full-read/current-state 判断方法。
2. 改 `read_file`，默认 raw content，增加 `show_line_numbers`。
3. 重写 `edit_file` 为 `old_string/new_string/replace_all`。
4. 给 `write_file` 增加已有文件 read-before-write 检查。
5. 删除旧 diff 测试，补新测试。
6. 跑 backend 单测和 lint/type-check。

## 开放问题

1. 默认 `max_lines` 选 1200 还是 2000？

   建议先用 1200。Pivot 当前默认 400，直接到 2000 可能 token 压力偏大；1200 在代码编辑场景更均衡。工具仍允许显式 `max_lines=2000`。

2. 是否保留 `edit_file(diff=...)` 兼容？

   建议不保留。本项目尚未上线，且兼容会让模型继续学到不稳定接口。直接改成干净的新协议。

3. `read_file` 去重摘要是否保留？

   不保留。`read_file` 的职责是返回当前内容片段；tracker 只做安全账本和 debug 数据源。重复读取的 token 压力应通过分页、默认行数上限、search/grep 缩小范围、runtime compaction 等机制处理，而不是让 `read_file` 返回“内容已在上下文”的摘要。
