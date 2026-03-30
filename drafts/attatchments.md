# Agent Answer Attachments Design

## Goal

Expose an `attachments` capability on the ReAct `ANSWER` action so the agent can
return generated files, and render them in chat as clickable cards. Clicking a
card should open `web/src/components/DraggableDialog.tsx` and preview the
attachment content (starting with Markdown, PDF, and images).

## Current State

### Protocol

`server/app/orchestration/react/system_prompt.md` currently documents:

```json
{
  "action": {
    "action_type": "ANSWER",
    "output": {
      "answer": "final user-facing answer",
      "attatchments": []
    }
  }
}
```

Notes:

- The field is currently spelled `attatchments` in the prompt.
- The parser does not enforce an answer-specific schema yet; it only requires
  `action.output` to be an object.

### Backend persistence

- ReAct task history currently persists the final assistant answer by reading the
  last `ANSWER` recursion's `action_output.answer`.
- User-uploaded files already have a dedicated lifecycle:
  `app/services/file_service.py`, `app/models/file.py`, `/api/files/...`.
- There is no equivalent persistence layer for agent-generated output files.

### Frontend

- Chat already supports user-uploaded attachments as cards.
- Assistant messages currently render only text content.
- Existing preview for uploaded images uses `AttachmentPreviewDialog`, which is a
  centered modal, not `DraggableDialog`.

## Recommendation

Do **not** expose raw sandbox absolute paths directly to the frontend.

Instead, add a dedicated service that:

1. accepts the model-declared sandbox paths from `ANSWER.output.attachments`
2. validates they are under `/workspace`
3. snapshots the files into backend-managed storage
4. persists normalized metadata on the task/session
5. exposes authenticated preview/download endpoints

This keeps the UI simple, makes history immutable, and avoids coupling the
frontend to live sandbox filesystem state.

## Why snapshotting is necessary

If we only store `/workspace/...` paths from the sandbox:

- later agent runs may overwrite the file
- the sandbox content is mutable, so history becomes unstable
- the frontend still cannot read the file without an API layer
- security checks become harder because every read becomes a live path lookup

Snapshotting the file when the answer is finalized gives us stable history and a
clean permission boundary.

## Naming recommendation

I recommend normalizing the public field name to `attachments`, not keeping the
misspelled `attatchments`.

Suggested rollout rule:

- update the prompt examples to emit `attachments`
- allow the backend normalizer to temporarily accept both
  `attachments` and `attatchments`
- persist and stream only the normalized `attachments`

This gives us a clean long-term contract without locking the typo into the rest
of the codebase.

## Proposed data model

Add a new persistence model instead of reusing `FileAsset`.

### Why a separate model is cleaner

`FileAsset` is currently optimized for **user uploads before task execution**:

- upload queue lifecycle
- session/task attachment on send
- image/document preprocessing for prompt input

Agent answer attachments are different:

- created by the agent after execution
- immutable output artifacts
- previewed from assistant messages, not user messages

Trying to overload `FileAsset` would mix two different lifecycles.

### New model

Suggested model: `TaskAttachment`

Example fields:

- `id`
- `attachment_id: str` public UUID
- `task_id: str`
- `session_id: str | None`
- `agent_id: int`
- `user: str`
- `display_name: str`
- `original_name: str`
- `mime_type: str`
- `extension: str`
- `size_bytes: int`
- `render_kind: str`
  - `markdown`
  - `pdf`
  - `image`
  - `text`
  - `download`
- `sandbox_path: str`
- `workspace_relative_path: str`
- `storage_path: str`
- `created_at`
- `updated_at`

If we later want extracted text caches, we can add:

- `text_cache_path: str | None`

## Service design

Add a dedicated reusable service under `server/app/services`, for example:

- `app/services/task_attachment_service.py`

Core responsibilities:

### 1. Normalize and validate answer output

Input:

- raw `ANSWER.output`
- authenticated runtime context (`username`, `agent_id`, `task_id`, `session_id`)

Rules:

- accept `attachments` or `attatchments`
- require a list of strings
- reject empty strings
- normalize sandbox paths
- reject anything outside `/workspace`
- reject directories
- reject missing files
- optionally reject symlinks

### 2. Resolve sandbox path to host path

We already have the host-side workspace root:

- `ensure_agent_workspace(username, agent_id)`

Sandbox `/workspace/foo/bar.md` can be resolved to host:

- `server/workspace/{username}/agents/{agent_id}/foo/bar.md`

This resolution should live in the service, not in API handlers or UI code.

### 3. Snapshot the artifact

Copy the resolved host file into backend-managed storage, for example:

- `server/workspace/{username}/task_attachments/{task_id}/{attachment_id}/artifact.ext`

This makes the artifact immutable even if the live workspace file changes later.

### 4. Infer preview metadata

Infer:

- MIME type
- extension
- size
- render kind
- user-facing display name

Initial render-kind mapping:

- `.md`, `.markdown` -> `markdown`
- `.pdf` -> `pdf`
- image MIME types -> `image`
- `.txt` and text MIME types -> `text`
- everything else -> `download`

### 5. CRUD methods

Keep the service generic and reusable:

- `create_from_answer_paths(...) -> list[TaskAttachment]`
- `list_by_task_ids(task_ids: list[str]) -> dict[str, list[TaskAttachmentListItem]]`
- `get_attachment_for_user(attachment_id: str, username: str) -> TaskAttachment | None`
- `delete_by_task_id(task_id: str) -> int`
- `delete_by_session_id(session_id: str) -> int`

This follows the project rule of keeping persistence access in the service layer.

## API and schema changes

### Backend schemas

Add new schema types, for example in `server/app/schemas/task_attachment.py`:

- `TaskAttachmentResponse`
- `TaskAttachmentListItem`

Public list item example:

```json
{
  "attachment_id": "uuid",
  "display_name": "report.md",
  "mime_type": "text/markdown",
  "extension": "md",
  "size_bytes": 10240,
  "render_kind": "markdown",
  "workspace_relative_path": "outputs/report.md",
  "created_at": "2026-03-30T12:00:00+00:00"
}
```

Do not expose host filesystem paths in the public API.

### React answer event

When `action_type == "ANSWER"`, stream normalized attachments in:

```json
{
  "type": "answer",
  "data": {
    "answer": "...",
    "attachments": [...]
  }
}
```

### Full session history

Extend `TaskMessage` with:

- `assistant_attachments: list[TaskAttachmentListItem] = []`

Keep user `files` unchanged for now. This keeps the contract explicit and avoids
mixing inbound files with assistant-generated artifacts.

### Optional simple chat history

`Session.chat_history` is not the main chat UI source today, but for consistency
it should eventually store assistant attachment metadata too. Two reasonable
options:

1. Add `attachments` to each chat-history message.
2. Keep `files` for user messages and add `assistant_attachments` for assistant messages.

Recommendation: use `attachments` only in the simple chat-history schema if that
endpoint is still important. Otherwise, prioritize full-history first.

### Attachment content endpoint

Add authenticated endpoints such as:

- `GET /api/task-attachments/{attachment_id}/content`

This should stream the stored snapshot with `FileResponse`.

One endpoint is enough for phase 1. The frontend can decide whether to read it
as text or as a blob.

## ReAct runtime changes

### Prompt contract

Update `server/app/orchestration/react/system_prompt.md`:

```json
{
  "action": {
    "action_type": "ANSWER",
    "output": {
      "answer": "final user-facing answer",
      "attachments": [
        "/workspace/outputs/report.md",
        "/workspace/outputs/slides.pdf"
      ]
    }
  }
}
```

Also clarify:

- attachments must be absolute sandbox paths under `/workspace`
- only include files that should be shown to the user
- prefer a small number of high-value artifacts

### Engine integration

Recommended place: inside `ReactEngine.execute_recursion(...)`, after the
decision is parsed and before `finalize_success(...)`.

Flow:

1. read raw `action_output`
2. if `action_type != "ANSWER"`, do nothing
3. if `action_type == "ANSWER"`, call `TaskAttachmentService.create_from_answer_paths(...)`
4. replace the raw path list in `action_output` with normalized attachment descriptors
5. persist the normalized output in recursion history
6. emit the same normalized descriptors in the `answer` SSE event

This ensures streaming payloads and persisted history use the same contract.

### Session history write

Current code writes:

```python
SessionService(self.db).update_chat_history(
    task.session_id,
    "assistant",
    answer_output.get("answer", ""),
)
```

This should be extended so assistant chat-history entries can also carry the
normalized attachment metadata.

## Frontend design

## Message model

Add a separate field to assistant messages:

- `assistantAttachments?: AssistantAttachment[]`

Recommendation: do **not** reuse the existing `attachments` field on
`ChatMessage` for assistant output. The current field is tightly associated with
user-uploaded files and preview behavior.

Suggested type:

```ts
export interface AssistantAttachment {
  attachmentId: string;
  displayName: string;
  mimeType: string;
  extension: string;
  sizeBytes: number;
  renderKind: "markdown" | "pdf" | "image" | "text" | "download";
  workspaceRelativePath: string;
  createdAt: string;
}
```

### Mapping changes

Update:

- `web/src/utils/api.ts`
- `web/src/pages/chat/types.ts`
- `web/src/pages/chat/utils/chatData.ts`
- `web/src/pages/chat/ChatContainer.tsx`

So that:

- full-history maps `assistant_attachments` into the assistant message
- live `answer` events also hydrate `assistantAttachments`

## Assistant card UI

Add a dedicated component instead of reusing the user-upload attachment list
directly:

- `AssistantAttachmentList.tsx`
- `AssistantAttachmentCard.tsx`
- `AssistantAttachmentDialog.tsx`

Why a separate component is better:

- assistant cards open `DraggableDialog`, not the current modal preview
- assistant cards should emphasize "artifact/output" rather than "uploaded file"
- the supported preview types are different

### Card behavior

Each card should show:

- icon by render kind
- display name
- extension or render-kind label
- file size
- optional workspace-relative path in muted text

Interaction:

- click card -> open `DraggableDialog`

## Dialog renderer

Use `web/src/components/DraggableDialog.tsx` as the shell.

Suggested content router:

- `MarkdownAttachmentViewer`
- `PdfAttachmentViewer`
- `ImageAttachmentViewer`
- `TextAttachmentViewer`
- `DownloadOnlyAttachmentViewer`

### Markdown

Recommended behavior:

- fetch content from `/task-attachments/{id}/content`
- read as text
- render as Markdown inside a scrollable panel

Dependency choice:

- Recommended: add `react-markdown`
- Fallback: reuse a minimal in-house formatter if you want zero new dependency

I recommend `react-markdown` because agent-generated Markdown artifacts will
likely be richer than the very limited answer-formatting subset currently used
by `FormattedAnswerContent.tsx`.

### PDF

Phase 1 recommendation:

- fetch as blob
- create object URL
- render with `<iframe>` or `<embed>` inside the draggable dialog

This avoids bringing in `pdf.js` unless we later need custom pagination,
annotation, or text search.

### Image

Reuse the same object-URL pattern already used in the chat attachment preview.

### Unsupported files

Show:

- metadata
- a "Download" or "Open raw file" button

This keeps the first version useful without blocking on every file type.

## Suggested frontend composition

Inside `AssistantMessageBlock.tsx`:

1. render final answer text
2. if `message.assistantAttachments?.length > 0`, render `AssistantAttachmentList`
3. keep the status/timestamp row below

This matches the mental model:

- text answer first
- artifacts immediately below the answer
- execution metadata last

## End-to-end flow

### Live answer

1. Agent writes files under sandbox `/workspace/...`
2. Agent returns `ANSWER.output.attachments`
3. Backend validates and snapshots them through `TaskAttachmentService`
4. Backend emits `answer` SSE with normalized attachment descriptors
5. Frontend updates the current assistant bubble and shows attachment cards
6. User clicks a card
7. `DraggableDialog` opens and renders the correct viewer

### Session restore

1. Frontend calls full-history
2. Backend returns `assistant_attachments` on each completed task
3. `buildMessagesFromHistory()` hydrates the same assistant cards
4. Clicking a restored card uses the same dialog flow as live answers

## Validation and safety rules

The backend service should enforce:

- attachments must be files, not directories
- attachments must stay inside `/workspace`
- missing files should either:
  - reject the entire attachment set, or
  - skip invalid entries and keep valid ones

Recommendation: skip invalid entries, log warnings, and still deliver the final
answer unless all attachments are invalid and the attachment is essential to the
answer.

Also enforce:

- max attachment count per answer, for example `<= 8`
- max attachment size per file
- total size cap per answer

Do not let the frontend request arbitrary filesystem paths.

## Testing plan

### Backend

Add unit tests for:

- typo normalization: `attatchments` -> `attachments`
- path normalization and `/workspace` boundary rejection
- host-path resolution
- snapshot copy behavior
- missing-file handling
- full-history serialization
- answer SSE payload shape

### Frontend

Add tests for:

- `buildMessagesFromHistory()` mapping assistant attachments
- live `answer` event updating `assistantAttachments`
- rendering assistant cards only when present
- clicking a card opens `DraggableDialog`
- Markdown viewer loads text content
- PDF viewer creates an object URL

## Recommended implementation order

1. Normalize the prompt contract to `attachments`.
2. Add `TaskAttachment` model, schemas, and service.
3. Persist and stream normalized answer attachments from the engine.
4. Expose `/task-attachments/{id}/content`.
5. Extend full-history payloads with `assistant_attachments`.
6. Add frontend types and history/event mapping.
7. Build assistant card list and `DraggableDialog` previewers.
8. Add tests.

## Files likely to change

Backend:

- `server/app/orchestration/react/system_prompt.md`
- `server/app/orchestration/react/engine.py`
- `server/app/services/session_service.py`
- `server/app/api/session.py`
- `server/app/api/react.py` if shared event schema helpers are added
- `server/app/api/task_attachments.py` or similar new router
- `server/app/models/...` new task attachment model
- `server/app/schemas/...` new task attachment schemas
- `server/app/services/task_attachment_service.py`

Frontend:

- `web/src/utils/api.ts`
- `web/src/pages/chat/types.ts`
- `web/src/pages/chat/utils/chatData.ts`
- `web/src/pages/chat/utils/chatData.test.ts`
- `web/src/pages/chat/ChatContainer.tsx`
- `web/src/pages/chat/components/AssistantMessageBlock.tsx`
- new assistant attachment components
- optionally a new Markdown renderer dependency in `web/package.json`

## Aligned decisions

The following points are now considered settled for implementation:

### 1. Field naming

- public protocol: `attachments`
- backend normalizer: temporarily accept both `attachments` and `attatchments`
- persistence and frontend payloads: emit only `attachments`

### 2. Markdown renderer

- add `react-markdown`

### 3. Invalid attachment handling

- skip invalid files
- log warnings on the backend
- keep the final answer usable unless every declared attachment fails validation

## Final recommendation

The cleanest long-term design is:

- keep prompt-level `attachments` as a lightweight path declaration by the model
- immediately translate those paths into persisted `TaskAttachment` records
- stream and restore only normalized attachment descriptors
- render assistant attachments with dedicated cards and a `DraggableDialog`
  preview flow

This avoids leaking raw filesystem concerns into the client, preserves stable
history, and keeps the persistence logic in a reusable service layer.
