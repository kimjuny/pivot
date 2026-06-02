# api.ts 拆分方案

## 现状

- **文件**: `web/src/utils/api.ts`
- **规模**: ~4,484 行, ~136 KB
- **消费者**: 29 个文件（28 个组件 + 1 个 AuthContext）
- **内容**: 基础设施代码 + 15 个业务域的接口/类型/函数

## 拆分目标

1. 按业务域拆分为独立模块，每个模块内聚（类型 + 函数在一起）
2. `api/index.ts` 做统一 re-export，**保持所有现有 `import { xxx } from '@/utils/api'` 和 `import { xxx } from '../utils/api'` 零改动**
3. 每个 API 函数仅依赖 `api/core.ts` 中的基础设施，不再跨域依赖

## 目录结构

```
web/src/utils/api/
├── index.ts            # 统一 re-export（保持向后兼容）
├── core.ts             # 基础设施：HTTP client, apiRequest, error classes
├── agents.ts           # Agent CRUD / draft / release / delegation / access
├── channels.ts         # Channel catalog / binding / health / link
├── web-search.ts       # Web search provider catalog / binding / health
├── media.ts            # Media provider catalog / binding / health
├── extensions.ts       # Extension packages / installation / hooks / binding
├── llms.ts             # LLM CRUD / access
├── sessions.ts         # Session / project / chat history
├── react.ts            # ReAct task / context usage / compact
├── files.ts            # File upload / download / delete
├── tools.ts            # Tool CRUD / source / access / lint check
├── skills.ts           # Skill CRUD / source / file tree / import
├── surfaces.ts         # Chat surface session / preview endpoint
├── analytics.ts        # Studio dashboard / agent analytics
└── workspace.ts        # Workspace file search
```

## 各模块详细内容

### 1. `core.ts` (~110 行)

从 api.ts 提取 **行 1–322** 的基础设施部分：

| 导出 | 类型 |
|------|------|
| `setApiBaseUrl`, `getApiBaseUrl` | 函数 |
| `setHttpClient`, `httpClient` | 函数 |
| `AuthError`, `ApiError` | 类 |
| `apiRequest`, `apiRequestFormData` | 函数 |
| `RequestOptions` | interface |
| `FileUploadSource` | type |
| `getAuthorizedHeaders` | 函数（提升为 export，供 files.ts 等直接使用） |

**依赖**: `auth-core` 模块

### 2. `agents.ts` (~310 行)

从 api.ts 提取 **行 96–635** 中与 Agent 相关的内容：

| 导出 | 类型 |
|------|------|
| `AgentReleaseRecord`, `AgentSavedDraftInfo`, `AgentDraftState` | interface |
| `AgentSidebarSectionStats`, `AgentSidebarStats` | interface |
| `AgentAccess`, `AgentAccessUserOption`, `AgentAccessGroupOption`, `AgentAccessOptions` | interface |
| `getAgents`, `createAgent`, `getAgentById`, `updateAgent`, `deleteAgent` | 函数 |
| `updateAgentClientState` | 函数 |
| `getAgentAccess`, `getAgentAccessOptions`, `getAgentCreateAccessOptions`, `updateAgentAccess` | 函数 |
| `getAgentSidebarStats` | 函数 |
| `getAgentDraftState`, `saveAgentDraft`, `publishAgentRelease` | 函数 |
| `updateAgentToolIds`, `updateAgentSkillIds` | 函数 |
| Delegation: `getAgentDelegations`, `replaceAgentDelegations`, `createAgentDelegation`, `deleteAgentDelegation` | 函数 |

**依赖**: `./core` 中的 `apiRequest`

### 3. `channels.ts` (~220 行)

从 api.ts 提取 **行 637–856**：

| 导出 | 类型 |
|------|------|
| `ChannelConfigField`, `ChannelManifest`, `ChannelEndpointInfo` | interface |
| `ChannelCatalogItem`, `ChannelBinding`, `ChannelLinkStatus` | interface |
| `getChannels`, `getChannel` | 函数 |
| `getAgentChannels`, `createAgentChannel`, `updateAgentChannel`, `deleteAgentChannel` | 函数 |
| `testAgentChannel`, `testChannelDraft`, `pollAgentChannel` | 函数 |
| `getChannelLinkStatus`, `completeChannelLink` | 函数 |

**依赖**: `./core` 中的 `apiRequest`

### 4. `web-search.ts` (~210 行)

从 api.ts 提取 **行 858–1069**：

| 导出 | 类型 |
|------|------|
| `WebSearchConfigField`, `WebSearchProviderManifest` | interface |
| `WebSearchCatalogItem`, `WebSearchBinding` | interface |
| `getWebSearchProviders` | 函数 |
| `getAgentWebSearchBindings`, `createAgentWebSearchBinding`, `updateAgentWebSearchBinding`, `deleteAgentWebSearchBinding` | 函数 |
| `testAgentWebSearchBinding`, `testWebSearchProviderDraft` | 函数 |

**依赖**: `./core` 中的 `apiRequest`

### 5. `media.ts` (~130 行)

从 api.ts 提取 **行 923–1155**：

| 导出 | 类型 |
|------|------|
| `MediaProviderConfigField`, `MediaProviderManifest` | interface |
| `MediaProviderCatalogItem`, `MediaProviderBinding` | interface |
| `getMediaGenerationProviders` | 函数 |
| `getAgentMediaProviderBindings`, `createAgentMediaProviderBinding`, `updateAgentMediaProviderBinding`, `deleteAgentMediaProviderBinding` | 函数 |
| `testAgentMediaProviderBinding`, `testMediaProviderDraft` | 函数 |

**依赖**: `./core` 中的 `apiRequest`

### 6. `extensions.ts` (~960 行)

从 api.ts 提取 **行 1157–2121**。这是最大的模块，包含：

| 导出 | 类型 |
|------|------|
| `ExtensionInstallation`, `ExtensionPendingUpgrade`, `ExtensionUpgradeMode` | interface/type |
| `ExtensionContributionSummary`, `ExtensionContributionItem` | interface |
| `ExtensionConfigurationField`, `ExtensionConfigurationSection`, `ExtensionConfigurationSchema` | interface |
| `ExtensionPackage`, `ExtensionReferenceSummary`, `ExtensionImportPreview` | interface |
| `ExtensionImportProgressEvent`, `ExtensionUninstallResult` | interface |
| `ExtensionHookExecution`, `ExtensionHookReplayResult` | interface |
| `ExtensionInstallationConfigurationState` | interface |
| `ExtensionInstallationAccess`, `ExtensionInstallationAccessOptions` | interface |
| `AgentExtensionBinding`, `AgentExtensionPackage` | interface |
| `ChatSurfaceDescriptorResponse` | interface |
| `WebSearchProviderOptionResponse`, `ChatBootstrapResponse` | interface |
| 所有 extension CRUD / import / hook / binding 函数 | 函数 |
| `getChatBootstrap`, `getAgentChatSurfaces` | 函数 |
| `parseExtensionImportProgressEvent`（内部 helper） | 函数 |

> **注意**: `ChatBootstrapResponse` 和 `ChatSurfaceDescriptorResponse` 放在 extensions.ts 是因为它们是 chat-bootstrap endpoint 的响应类型，该 endpoint 的主要目的是为 chat 页面聚合并返回 extensions 相关数据。如果后续觉得放在这里不够直观，可以单独放到 `chat.ts` 中。

**依赖**: `./core` 中的 `apiRequest`, `apiRequestFormData`, `httpClient`, `getAuthorizedHeaders`, `AuthError`, `getApiBaseUrl`

### 7. `llms.ts` (~210 行)

从 api.ts 提取 **行 2123–2328**：

| 导出 | 类型 |
|------|------|
| `getModels`, `getLLMs`, `getUsableLLMs`, `getUsableLLMById` | 函数 |
| `createLLM`, `getLLMById`, `updateLLM`, `deleteLLM` | 函数 |
| `LLMAccess`, `LLMAccessUserOption`, `LLMAccessGroupOption`, `LLMAccessOptions` | interface |
| `getLLMAccess`, `getLLMAccessOptions`, `getLLMCreateAccessOptions`, `updateLLMAccess` | 函数 |

**依赖**: `./core` 中的 `apiRequest`

### 8. `sessions.ts` (~400 行)

从 api.ts 提取 **行 2330–2729**：

| 导出 | 类型 |
|------|------|
| `ProjectResponse`, `ProjectListResponse`, `ProjectAccess`, `ProjectAccessOptions` | interface |
| `SessionListItem`, `SessionListResponse`, `SessionResponse` | interface |
| `SessionChatHistoryMessage`, `ChatFileAsset`, `TaskAttachmentAsset`, `ChatImageFile` | interface |
| `SessionChatHistoryResponse`, `SessionMigrateResponse` | interface |
| `RecursionDetail`, `CurrentPlanRecursionSummary`, `CurrentPlanStep` | interface |
| `TaskMessage`, `FullSessionHistoryResponse` | interface |
| Session/Project CRUD 函数 | 函数 |
| `getSessionHistory`, `getFullSessionHistory` | 函数 |

**依赖**: `./core` 中的 `apiRequest`

### 9. `react.ts` (~230 行)

从 api.ts 提取 **行 2817–3057**：

| 导出 | 类型 |
|------|------|
| `ReactTaskStartResponse`, `ReactTaskCancelResponse` | interface |
| `ReactPendingUserActionResponse`, `ReactRuntimeSkillItem` | interface |
| `ReactContextUsageSummary`, `ReactSessionRuntimeDebug` | interface |
| `ReactSessionCompactResponse` | interface |
| `startReactTask`, `cancelReactTask`, `submitReactUserAction`, `submitMidTaskInput` | 函数 |
| `getReactContextUsage`, `getReactRuntimeSkills` | 函数 |
| `getReactSessionRuntimeDebug`, `compactReactSession` | 函数 |

**依赖**: `./core` 中的 `apiRequest`

### 10. `files.ts` (~200 行)

从 api.ts 提取 **行 3059–3256**：

| 导出 | 类型 |
|------|------|
| `uploadChatFile`, `uploadChatImage` | 函数 |
| `deleteChatFile`, `deleteChatImage` | 函数 |
| `fetchChatFileBlob`, `fetchChatImageBlob` | 函数 |
| `fetchTaskAttachmentBlob` | 函数 |

**依赖**: `./core` 中的 `httpClient`, `getAuthorizedHeaders`, `AuthError`, `getApiBaseUrl`

### 11. `tools.ts` (~230 行)

从 api.ts 提取 **行 3258–3340 + 4119–4226**：

| 导出 | 类型 |
|------|------|
| `Tool`, `ToolParameterProperty`, `ToolParameters` | interface |
| `ToolExecutionType`, `ToolSourceType`, `ToolInventorySourceType`, `ToolSourceCategory` | type |
| `UsableTool`, `ManagedTool`, `ToolSourcePayload` | interface |
| `ToolAccess`, `ToolAccessOptions`, `ToolDiagnostic` | interface/type |
| `getTools`, `getUsableTools`, `getManageableTools` | 函数 |
| `getToolSource`, `updateToolSource`, `deleteToolSource` | 函数 |
| `getToolAccess`, `getToolAccessOptions`, `updateToolAccess`, `getToolCreateAccessOptions` | 函数 |
| `checkToolAst`, `checkToolRuff`, `checkToolPyright` | 函数 |

**依赖**: `./core` 中的 `apiRequest`

### 12. `skills.ts` (~470 行)

从 api.ts 提取 **行 3342–3808**：

| 导出 | 类型 |
|------|------|
| `SkillSource`, `SkillSourceCategory` | type |
| `BundleSkillImportFile`, `SkillImportProgressEvent` | interface |
| `UserSkill`, `UsableSkill`, `ManagedSkill` | interface/type |
| `SkillAccess`, `SkillAccessOptions` | interface/type |
| `GitHubSkillCandidate`, `GitHubSkillRepository`, `GitHubSkillProbeResponse` | interface |
| `SkillSourcePayload`, `SkillFileTreeEntry`, `SkillFileTree`, `SkillFileContent` | interface |
| 所有 skill CRUD / source / file tree / import 函数 | 函数 |
| `parseSkillImportProgressEvent`（内部 helper） | 函数 |

**依赖**: `./core` 中的 `apiRequest`, `httpClient`, `getAuthorizedHeaders`, `AuthError`, `getApiBaseUrl`

### 13. `surfaces.ts` (~300 行)

从 api.ts 提取 **行 3820–4117**：

| 导出 | 类型 |
|------|------|
| `SurfaceFilesApiResponse` | interface |
| `PreviewEndpointResponse`, `ReconnectPreviewEndpointResponse` | interface |
| `DevSurfaceBootstrapResponse`, `DevSurfaceSessionResponse` | interface |
| `InstalledSurfaceBootstrapResponse`, `InstalledSurfaceSessionResponse` | interface |
| `createDevSurfaceSession`, `createInstalledSurfaceSession` | 函数 |
| `createPreviewEndpoint`, `getPreviewEndpoints` | 函数 |
| `reconnectSurfacePreview` | 函数 |

**依赖**: `./core` 中的 `apiRequest`

### 14. `analytics.ts` (~230 行)

从 api.ts 提取 **行 4228–4455**：

| 导出 | 类型 |
|------|------|
| `StudioOverview`, `DailySessionCount`, `TaskStats` | interface |
| `DailyTokenUsage`, `AgentPopularity`, `RuntimeHealth` | interface |
| `RecentActivityItem`, `DailyUserActivity`, `DailyUserGrowth` | interface |
| `AgentOverview`, `IterationBucket`, `AgentUserStats` | interface |
| `AgentReleaseItem`, `DailyClientUsage`, `ChannelActivityItem` | interface |
| 所有 analytics 函数 | 函数 |

**依赖**: `./core` 中的 `apiRequest`

### 15. `workspace.ts` (~30 行)

从 api.ts 提取 **行 4457–4484**：

| 导出 | 类型 |
|------|------|
| `WorkspaceFileItem` | interface |
| `searchWorkspaceFiles` | 函数 |

**依赖**: `./core` 中的 `apiRequest`

---

## `index.ts` 设计

```typescript
// web/src/utils/api/index.ts
// 统一 re-export，保持所有现有 import 路径零改动

export * from './core';
export * from './agents';
export * from './channels';
export * from './web-search';
export * from './media';
export * from './extensions';
export * from './llms';
export * from './sessions';
export * from './react';
export * from './files';
export * from './tools';
export * from './skills';
export * from './surfaces';
export * from './analytics';
export * from './workspace';
```

这样：
- `import { getAgents } from '@/utils/api'` → 仍然有效（解析到 `@/utils/api/index.ts`）
- `import { getAgents } from '../utils/api'` → 仍然有效（解析到 `../utils/api/index.ts`）
- **29 个消费者文件零改动**

## 实施步骤

1. **创建 `web/src/utils/api/` 目录**
2. **先提取 `core.ts`** — 这是其他所有模块的依赖基础
3. **按任意顺序提取其余 14 个模块**（它们之间无依赖）
4. **创建 `index.ts`** 统一 re-export
5. **删除原 `api.ts`**（已被 `api/index.ts` 替代）
6. **验证** — 运行 `npm run type-check` 和 `npm run lint` 确保无破坏
7. **可选清理** — 将来各消费者文件可逐步改为从更精确的子模块导入（如 `import { getAgents } from '@/utils/api/agents'`），但这不是必须的

## 模块间依赖关系

```
core.ts ← 所有模块都依赖
```

各业务模块之间 **没有横向依赖**，所有模块仅依赖 `core.ts` 中的基础设施函数。这是此拆分方案最简洁的地方。

## 行数分布

| 模块 | 行数（约） |
|------|-----------|
| core.ts | 110 |
| agents.ts | 310 |
| channels.ts | 220 |
| web-search.ts | 210 |
| media.ts | 130 |
| extensions.ts | 960 |
| llms.ts | 210 |
| sessions.ts | 400 |
| react.ts | 230 |
| files.ts | 200 |
| tools.ts | 230 |
| skills.ts | 470 |
| surfaces.ts | 300 |
| analytics.ts | 230 |
| workspace.ts | 30 |
| **总计** | **~4,240**（+ index.ts ~20 行） |

## 风险与注意事项

1. **命名冲突**: `export *` re-export 时如果有同名导出会导致冲突。经检查，当前所有类型/函数命名都是唯一的，没有冲突。
2. **循环依赖**: 各业务模块不互相引用，只依赖 `core.ts`，不存在循环依赖风险。
3. **`StorageStatus` 类型**: 当前放在 `api.ts` 行 189–214，建议归入 `core.ts`（与 `getStorageStatus` 函数一起）或新建 `system.ts`。考虑到只有一个函数，归入 `core.ts` 更简单。
4. **`Tool` interface（行 2136）和 `Tool` from `getTools`**: 注意 `getTools` 返回的 `Tool` 类型和 `tools.ts` 中更丰富的 `UsableTool`/`ManagedTool` 是不同的。拆分时保持原样即可。
5. **`LLMAccessOptions` 被 `ToolAccessOptions` 和 `SkillAccessOptions` 复用**: 当前通过 `export type ToolAccessOptions = LLMAccessOptions` 实现。拆分时，这个别名可以放在 `core.ts` 中定义一个通用的 `AccessOptions` type，或者保持现状让 `tools.ts` 和 `skills.ts` 从 `llms.ts` 导入。建议放在 `core.ts` 中作为通用类型。
