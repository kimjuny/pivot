# Chat Page Loading Optimization

## Overview

When a user navigates from the Agent list to a specific Agent's Chat page, **10 unique API endpoints** are called.
Due to React StrictMode double-rendering in development, all requests are duplicated, resulting in **20 actual HTTP requests**.

---

## Phase 1: Agent List Page (before entering Chat)

### 1. GET /api/consumer/agents

- **Why**: Render the agent selection grid (name, avatar, model badge)
- **All fields returned**: `id`, `name`, `description`, `created_by_user_id`, `use_scope`, `llm_id`, `session_idle_timeout_minutes`, `sandbox_timeout_seconds`, `compact_threshold_percent`, `active_release_id`, `client_state`, `model_name`, `max_iteration`, `tool_ids`, `skill_ids`, `created_at`, `updated_at`
- **Fields used**: `id`, `name`, `description`, `model_name`
- **Wasted**: 14/18 (**78%**)
- **DB queries**: `4 + 4N` (N = agents count) — N+1 in access checking (3 queries/agent) + N+1 in LLM display label resolution
- **Severity**: HIGH

### 2. GET /api/consumer/sessions?limit=30

- **Why**: Render the left sidebar session list (recent conversations)
- **All fields returned**: `session_id`, `agent_id`, `type`, `agent_name`, `agent_description`, `release_id`, `latest_release_id`, `is_stale`, `migrated_to_session_id`, `project_id`, `workspace_id`, `workspace_scope`, `test_workspace_hash`, `status`, `runtime_status`, `title`, `is_pinned`, `created_at`, `updated_at`
- **Fields used**: `session_id`, `agent_id`, `title`, `is_pinned`, `updated_at`
- **Wasted**: 14/19 (**74%**)
- **DB queries**: `5 + 3M` (M = total agents in DB) — fetches up to 10,000 agents for access filtering
- **Severity**: MEDIUM-HIGH

---

## Phase 2: Agent Chat Page

### 3. GET /api/consumer/agents/:id

- **Why**: Get agent config to bootstrap the Chat page — agent name (sidebar title), `llm_id` (drives LLM request), `tool_ids` (gates web search selector), `session_idle_timeout_minutes`
- **All fields returned**: Same 18 fields as #1
- **Fields used**: `id`, `name`, `llm_id`, `tool_ids`, `session_idle_timeout_minutes`, `model_name`
- **Wasted**: 12/18 (**67%**)
- **DB queries**: **8** (permission 3 + agent 1 + access 3 + LLM 1)
- **Severity**: HIGH

### 4. ~~GET /api/llms/:id~~ → GET /api/llms/usable/:id ✅ FIXED

- **Why**: Render the **Thinking Mode selector** (Auto/Think/No-think) in the chat composer bar
- **Fields returned (NEW)**: `id`, `name`, `model`, `protocol`, `streaming`, `image_input`, `image_output`, `max_context`, `thinking_policy`, `thinking_effort` — **no `api_key`**
- **Fields used**: `thinking_policy`, `thinking_effort`
- **DB queries**: **7** (permission 3 + LLM 1 + access 3)
- **Status**: ✅ Fixed — eliminated secret leak, reduced from 19 fields to 10

### 5. GET /api/sessions?agent_id=...&session_type=consumer

- **Why**: Render the **session list sidebar** — pinned sessions, project-grouped sessions, selection state
- **All fields returned**: `session_id`, `agent_id`, `type`, `release_id`, `latest_release_id`, `is_stale`, `migrated_to_session_id`, `project_id`, `workspace_id`, `workspace_scope`, `test_workspace_hash`, `status`, `runtime_status`, `title`, `is_pinned`, `created_at`, `updated_at`
- **Fields used**: `session_id`, `agent_id`, `type`, `release_id`, `project_id`, `workspace_id`, `workspace_scope`, `test_workspace_hash`, `status`, `runtime_status`, `title`, `is_pinned`, `created_at`, `updated_at`
- **Wasted**: 3/17 (**18%**)
- **DB queries**: `6 + 4N` (N = sessions) — N+1 per session for agent load + access check
- **Severity**: LOW (response efficient, but N+1 in access checks)

### 6. GET /api/projects?agent_id=...

- **Why**: Render **project groups** in the sidebar (expandable folders containing sessions)
- **All fields returned**: `id`, `project_id`, `agent_id`, `name`, `description`, `workspace_id`, `can_edit`, `created_at`, `updated_at`
- **Fields used**: `project_id`, `name`, `description`, `workspace_id`, `can_edit`
- **Wasted**: 4/9 (**44%**)
- **DB queries**: `8 + 6N` (N = projects) — N+1 double access check (USE + EDIT) per project, same user groups queried 2× per project without caching
- **Severity**: LOW

### 7. POST /api/react/runtime-skills

- **Why**: Render the **Skill selector** (slash-triggered `/` floating menu) and selected skill badges in the composer
- **All fields returned**: `name`, `description`, `path`
- **Fields used**: All 3
- **Wasted**: 0/3 (**0%**)
- **DB queries**: `11 + K` (K = skills count) — includes `sync_skill_registry` (full filesystem scan + DB sync) on every call + N+1 per skill
- **Severity**: HIGH (server-side burden — `sync_skill_registry` is extremely heavy for a read-only listing)

### 8. ~~GET /api/agents/:id/extensions/packages~~ → GET /api/agents/:id/chat-surfaces ✅ FIXED

- **Why**: Render the **Surface buttons** in the top-right corner of chat (e.g. "Workspace Editor") and detect which extensions provide chat surfaces
- **Fields returned (NEW)**: `installation_id`, `package_id`, `surface_key`, `display_name`, `logo_url`, `description`, `min_width`, `icon` — flat list, no version tree
- **Fields used**: All 8
- **DB queries**: `4 + N` (N = enabled bindings) — N+1 individual `get_installation` calls
- **Status**: ✅ Fixed — reduced from 8,362B / ~500 fields to 350B / 8 fields (**96% reduction**)

### 9. GET /api/agents/:id/web-search

- **Why**: Render the **Web Search Provider selector** in the composer bar (e.g. Baidu badge with logo)
- **All fields returned**: `id`, `agent_id`, `provider_key`, `enabled`, `effective_enabled`, `disabled_reason`, `auth_config`, `runtime_config`, `manifest` (full dict), `last_health_status`, `last_health_message`, `last_health_check_at`, `created_at`, `updated_at`
- **Fields used**: `enabled`, `provider_key`, `manifest.name`, `manifest.logo_url`
- **Wasted**: 11+ of 14+ fields (**~80%**) — includes `auth_config`/`runtime_config` which may contain secrets
- **DB queries**: `8 + 2N` (N = bindings) — same JOIN `list_agent_bound_extension_package_ids` queried 2× per binding (enabled_only=True, then False) without caching
- **Severity**: HIGH (security + server burden)

### 10. POST /api/react/context-usage

- **Why**: Render the **context usage ring** (circular gauge beside the Send button showing token usage %)
- **All fields returned**: `task_id`, `session_id`, `estimation_mode`, `message_count`, `session_message_count`, `used_tokens`, `remaining_tokens`, `max_context_tokens`, `used_percent`, `remaining_percent`, `system_tokens`, `conversation_tokens`, `session_tokens`, `preview_tokens`, `bootstrap_tokens`, `draft_tokens`, `includes_task_bootstrap`
- **Fields used**: `used_percent`, `remaining_percent`, `used_tokens`, `max_context_tokens`
- **Wasted**: 13/17 (**76%**)
- **DB queries**: **10~20+** depending on session/task state — includes `sync_skill_registry` (full filesystem scan), redundant agent/session reloads, double skill lookups
- **Severity**: HIGH (server-side burden — heaviest endpoint per request, called on every draft change)

---

## Summary Table

| # | Endpoint | Wasted | DB Queries | Security | Status |
|---|----------|--------|------------|----------|--------|
| 1 | GET /consumer/agents | 78% | 4+4N | - | 🔴 HIGH |
| 2 | GET /consumer/sessions | 74% | 5+3M | - | 🔴 MEDIUM-HIGH |
| 3 | GET /consumer/agents/:id | 67% | 8 | - | 🔴 HIGH |
| 4 | ~~GET /llms/:id~~ → GET /llms/usable/:id | 89%→0% | 7 | ✅ Fixed | ✅ DONE |
| 5 | GET /sessions | 18% | 6+4N | - | 🟢 LOW |
| 6 | GET /projects | 44% | 8+6N | - | 🟢 LOW |
| 7 | POST /react/runtime-skills | 0% | 11+K | - | 🔴 HIGH (server burden) |
| 8 | ~~GET extensions/packages~~ → GET /chat-surfaces | 98%→0% | 4+N | - | ✅ DONE |
| 9 | GET /agents/:id/web-search | ~80% | 8+2N | ⚠️ auth_config leak | 🔴 HIGH |
| 10 | POST /react/context-usage | 76% | 10~20+ | - | 🔴 HIGH (server burden) |

---

## Request Dependency Chain

```
3 GET /consumer/agents/:id  (agent detail)
├── 4 GET /llms/usable/:id               ← serial, needs llm_id from #3
├── 5 GET /sessions?agent_id=...         ← parallel with #6
│   └── 6 GET /projects?agent_id=...     ← parallel with #5
├── 7 POST /react/runtime-skills         ← parallel
├── 8 GET /agents/:id/chat-surfaces      ← parallel
├── 9 GET /agents/:id/web-search         ← parallel
└── 10 POST /react/context-usage         ← parallel
```

---

## Server-Side Burden Analysis

### Cross-Endpoint Redundant Queries

The same data is fetched repeatedly across endpoints within a single page load:

| Data | Endpoints That Fetch It | How Many Times |
|------|------------------------|----------------|
| **Agent row** (by agent_id) | 3, 5, 6, 7, 8, 9, 10 | 7+ times (endpoint 10 loads it 2-3× internally) |
| **User's group memberships** | All 10 | Every `has_resource_access` call (dozens of times per page load) |
| **Role / admin check** | All 10 | Every access check repeats `db.get(Role, user.role_id)` |
| **Extension bindings JOIN** | 7, 8, 9, 10 | Same `AgentExtensionBinding + ExtensionInstallation` JOIN queried 4+ times |
| **`sync_skill_registry`** (filesystem scan + DB sync) | 7, 10 | Called 2-3× per page load, each time scanning ALL skill files + writing to DB |

### Top Server-Side Concerns

| Priority | Issue | Impact | Endpoints |
|----------|-------|--------|-----------|
| **P0** | `sync_skill_registry` full filesystem scan on every call | CPU + I/O heavy, potentially writes to DB on read paths | #7, #10 |
| **P0** | Access check N+1: `is_admin()` + `_user_group_ids()` never cached | Same user's groups queried dozens of times per page load | All 10 |
| **P1** | Agent row loaded fresh by every endpoint | 7+ identical queries for the same row | #3,5,6,7,8,9,10 |
| **P1** | Extension bindings JOIN repeated across endpoints | Same JOIN data fetched 4+ times | #7,8,9,10 |
| **P2** | `has_project_access` called 2× per project (USE + EDIT) | Double 3-query access chain | #6 |
| **P2** | `list_agent_bound_extension_package_ids` called 2× per binding | Same query without caching | #9 |

---

## Bootstrap Merge Proposal

### Which endpoints to merge

The Chat page loads endpoints 3-10 after entering an agent. Of these, endpoints 3, 4, 5, 6, 8, 9 are **pure data fetches with no side effects** — they only read data and return JSON. These are the best candidates for merging.

| Merge In | Endpoint | Returns |
|----------|----------|---------|
| ✅ | #3 GET /consumer/agents/:id | Agent name, llm_id, tool_ids, timeouts |
| ✅ | #4 GET /llms/usable/:id | thinking_policy, thinking_effort |
| ✅ | #5 GET /sessions | Session list for sidebar |
| ✅ | #6 GET /projects | Project list for sidebar |
| ✅ | #8 GET /agents/:id/chat-surfaces | Surface buttons |
| ✅ | #9 GET /agents/:id/web-search | Provider key/name/logo for selector |
| ⚠️ | #7 POST /react/runtime-skills | Has side-effect (`sync_skill_registry`); keep separate but optimize |
| ⚠️ | #10 POST /react/context-usage | Called on draft change, not just page load; keep separate but optimize |

**Proposed new endpoint**: `GET /api/consumer/agents/:id/chat-bootstrap`

Returns in a single response:
```json
{
  "agent": { "id", "name", "llm_id", "tool_ids", "session_idle_timeout_minutes", "model_name" },
  "llm": { "thinking_policy", "thinking_effort" },
  "sessions": [...],
  "projects": [...],
  "chat_surfaces": [...],
  "web_search_providers": [{ "provider_key", "name", "logo_url" }]
}
```

### Server-side wins from merging

| Win | How |
|-----|-----|
| **Agent row: 1 query instead of 7+** | Fetch once, share across all sub-sections |
| **Access check: 1× instead of dozens** | Single permission check for the whole bootstrap |
| **Extension bindings JOIN: 1× instead of 4+** | Single JOIN, derive both chat-surfaces and web-search from it |
| **User groups: 1 query** | Load once, reuse for all access decisions |
| **Requests: 6 → 1** | Eliminates HTTP overhead, TLS handshake, header parsing |

### Estimated query reduction

**Before merge** (current, endpoints 3+4+5+6+8+9):
- Agent row: ~8 queries (endpoint 3)
- LLM: ~7 queries (endpoint 4)
- Sessions: 6+4N queries (endpoint 5)
- Projects: 8+6N queries (endpoint 6)
- Chat surfaces: 4+N queries (endpoint 8)
- Web search: 8+2N queries (endpoint 9)
- **Total: ~41 + 12N queries** (N = sessions, projects, bindings)

**After merge** (single bootstrap endpoint):
- Permission + user groups: ~4 queries (once)
- Agent row: 1 query
- LLM: 1 query
- Sessions: 1 query (no per-session access check needed — already authorized)
- Projects: 1 query (same)
- Extension bindings + installations: 1 JOIN query
- Web search bindings: already included in extension JOIN
- **Total: ~10 queries** (regardless of N)

### What to keep separate

- **#7 runtime-skills**: Keep separate but move `sync_skill_registry` to a background job or cache its result with TTL instead of running on every request.
- **#10 context-usage**: Keep separate (called on every draft keystroke) but optimize: remove `sync_skill_registry`, remove redundant agent/session reloads, cache skill metadata within a request.

---

## Next Steps

1. **Fix #9 web-search** — lightweight endpoint like #4/#8 (same pattern, quick win)
2. **Build chat-bootstrap endpoint** — merge #3+#4+#5+#6+#8+#9 into single request
3. **Optimize `sync_skill_registry`** — cache or background job, not per-request filesystem scan
4. **Optimize access check caching** — memoize `is_admin()` and `_user_group_ids()` within a request
