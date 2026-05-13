# read_file Multimodal Enhancement

## Background

Current file upload flow is eager — all uploaded files are preprocessed and fully injected into the first iteration's LLM context. This violates progressive disclosure:

- A 50-page PDF's entire content is force-fed even if the agent only needs one table
- All images are base64-encoded into the context even if the agent only needs the file path
- If the LLM doesn't support image input, the frontend blocks pasting entirely
- User intent may be "process this image externally" not "understand this image"

## New Flow

### Upload Stage

User uploads/pastes files → stored directly to `/workspace/.uploads/` → no preprocessing. Docling is removed from the upload pipeline entirely (just-in-time, see below).

### First Iteration — File Location Hints

Files are NOT injected into LLM context. Instead, their paths are listed in a top-level `attachments` field in the recursion payload:

```json
{
    "trace_id": "...",
    "iteration": 1,
    "user_intent": "用户原话...",
    "attachments": [
        {"path": "/workspace/.uploads/report.pdf", "kind": "document"},
        {"path": "/workspace/.uploads/screenshot.png", "kind": "image"}
    ],
    "current_plan": [],
    "action_result": []
}
```

The agent knows these files exist and where they are. It decides whether and when to read them.

### Agent Calls read_file — Three Paths by File Type

**Path 1: Text/Code files** (`.md`, `.txt`, `.py`, `.js`, `.json`, `.yaml`, etc.)
→ Existing `read_file` behavior: returns content with line numbers (compatible with `edit_file`)
→ Result goes into `action_result` as text

**Path 2: Complex documents** (`.pdf`, `.docx`, `.pptx`, `.xlsx`)
→ Just-in-time Docling conversion to markdown (no line number wrapping)
→ Result goes into `action_result` as text
→ Docling result is cached after first conversion; subsequent reads use cache

**Path 3: Images** (`.png`, `.jpg`, `.jpeg`, `.webp`)
→ Base64-encoded
→ Injected as multimodal block into the NEXT iteration's user message (not `action_result`)
→ Follows each provider's wire format (OpenAI Completion, OpenAI Response, Anthropic)
→ A brief text description (filename, dimensions) goes into `action_result` so the agent knows the image was loaded

### Two Distinct Attachment Semantics

| Mechanism | Purpose | Where | Agent Intent |
|-----------|---------|-------|--------------|
| `"attachments": []` in payload | Tell agent files exist and where | First iteration payload | "Know where it is" |
| Multimodal block in user message | Let LLM see image content | Next iteration user message | "Understand it" |
| Text in `action_result` | Document content or image metadata | Next iteration payload | "Read it" |

## Key Design Decisions

- **File type detection by extension** — simple and deterministic, no content sniffing needed
- **Docling is just-in-time** — no preprocessing at upload; only runs when agent reads a complex document
- **Agent transparency** — the agent just calls `read_file(path)`, doesn't need to know about file types
- **Image blob injection is engine-level** — the engine detects multimodal tool results and attaches them to the next user message, not the tool itself
- **Docling cached result** — first read processes with docling, subsequent reads use cached markdown

## Scope of Changes

### Server

1. **`file_service.py`** — Remove docling from upload; add just-in-time docling conversion method with caching
2. **`engine.py`** — Change first iteration: attach file paths instead of content blocks; add multimodal tool result injection for next iteration
3. **`read_file` tool** (`orchestration/tool/builtin/read_file.py`) — Add three-path file type branching; update docstring to document multimodal support
4. **`prompt_template.py`** — `build_runtime_payload_message` may need to handle dynamic multimodal blocks from tool results
5. **`react_task_supervisor.py`** — Stop calling `preprocess_files()` at task start; build attachment path list instead

### Frontend

1. **`useChatUploads.ts`** — Remove LLM image-input capability check that blocks pasting
2. **`ChatComposer.tsx`** — Allow all file types regardless of LLM multimodal support
