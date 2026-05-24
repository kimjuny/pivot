/**
 * Pivot Action Handler Registry
 *
 * Unified protocol for tool → frontend UI actions.  Tools that need to
 * influence the frontend return a ``pivot_action`` envelope in their result
 * dict.  The SSE stream carries it to the frontend where a handler registered
 * for the action ``type`` processes it.
 *
 * ## Envelope (server-side)
 *
 * ```json
 * {
 *   "pivot_action": {
 *     "type": "open_workspace_web_preview",
 *     "category": "notify" | "approval",
 *     "payload": { ... }
 *   }
 * }
 * ```
 *
 * - **notify** — fire-and-forget; the engine continues, the frontend just reacts.
 * - **approval** — the engine pauses and emits a ``clarify`` event; the user
 *   must respond before execution resumes.
 *
 * ## Adding a new action type
 *
 * 1. Tool returns ``pivot_action`` with a unique ``type`` string.
 * 2. Implement a ``PivotActionHandler`` on the frontend.
 * 3. Call ``registerActionHandler(handler)`` at module load.
 *
 * No engine changes are needed for ``notify`` actions.  ``approval`` actions
 * are automatically handled by the existing clarify / user-action pipeline.
 */

import type { AutomationProposal } from "@/components/AutomationCreateDialog";

/** Arbitrary structured data the handler receives. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ActionPayload = Record<string, any>;

/**
 * Context provided to action handlers for interacting with ChatContainer
 * state without coupling handlers to the full component API.
 */
export interface ActionHandlerContext {
  /** Open the extension dock with the given preview intent. */
  openWorkspacePreviewIntent: (intent: {
    preview: unknown;
    availablePreviews: unknown[];
    activePreviewId: string | null;
  }) => void;
  /** Open the automation creation dialog pre-filled with a proposal. */
  openAutomationProposalDialog: (proposal: AutomationProposal) => void;
}

/** One action handler registered for a specific ``pivot_action.type``. */
export interface PivotActionHandler {
  /** The ``pivot_action.type`` string this handler processes. */
  type: string;
  /** Whether the engine pauses (``"approval"``) or continues (``"notify"``). */
  category: "notify" | "approval";
  /**
   * Process the action payload.
   *
   * For ``notify`` handlers this is called from ``applyStreamEvent`` when a
   * ``tool_result`` SSE event contains a matching ``pivot_action``.
   *
   * For ``approval`` handlers this is called when a ``clarify`` event contains
   * a matching ``pivot_action``.
   */
  handle(payload: ActionPayload, context: ActionHandlerContext): void;
}

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

const handlerRegistry = new Map<string, PivotActionHandler>();

/** Register a handler for a ``pivot_action.type`` string. */
export function registerActionHandler(handler: PivotActionHandler): void {
  if (handlerRegistry.has(handler.type)) {
    console.warn(
      `[actionHandlers] Overwriting existing handler for "${handler.type}"`,
    );
  }
  handlerRegistry.set(handler.type, handler);
}

/** Look up a handler by action type. */
export function getActionHandler(
  type: string,
): PivotActionHandler | undefined {
  return handlerRegistry.get(type);
}

// ---------------------------------------------------------------------------
// Built-in handlers
// ---------------------------------------------------------------------------

/**
 * Open the workspace web preview dock panel.
 *
 * Migrated from the inline ``extractWorkspacePreviewIntent`` in ChatContainer.
 */
registerActionHandler({
  type: "open_workspace_web_preview",
  category: "notify",
  handle(payload, context) {
    context.openWorkspacePreviewIntent({
      preview: payload.preview,
      availablePreviews: Array.isArray(payload.available_previews)
        ? payload.available_previews
        : [],
      activePreviewId:
        typeof payload.active_preview_id === "string"
          ? payload.active_preview_id
          : null,
    });
  },
});

/**
 * Open the automation creation dialog pre-filled with an Agent proposal.
 */
registerActionHandler({
  type: "propose_automation",
  category: "notify",
  handle(payload, context) {
    context.openAutomationProposalDialog({
      name: typeof payload.name === "string" ? payload.name : "",
      description:
        typeof payload.description === "string" ? payload.description : "",
      promptTemplate:
        typeof payload.prompt_template === "string"
          ? payload.prompt_template
          : "",
      cron: typeof payload.cron === "string" ? payload.cron : "",
      timezone:
        typeof payload.timezone === "string" ? payload.timezone : "UTC",
      sessionStrategy:
        payload.session_strategy === "isolate" ? "isolate" : "reuse",
    });
  },
});

// ---------------------------------------------------------------------------
// Dispatch helpers
// ---------------------------------------------------------------------------

interface ToolResultItem {
  result?: unknown;
  success?: unknown;
}

interface PivotActionEnvelope {
  type?: unknown;
  category?: unknown;
  payload?: unknown;
}

/**
 * Extract and dispatch any ``pivot_action`` found in a ``tool_result`` SSE
 * event to its registered handler.
 */
export function dispatchPivotActionFromToolResult(
  toolResults: unknown,
  context: ActionHandlerContext,
): void {
  if (!Array.isArray(toolResults)) return;

  for (const item of toolResults) {
    if (!item || typeof item !== "object") continue;
    const { result, success } = item as ToolResultItem;
    if (success !== true || !result || typeof result !== "object") continue;

    const pivotAction = (result as { pivot_action?: unknown })
      .pivot_action;
    if (!pivotAction || typeof pivotAction !== "object") continue;

    const envelope = pivotAction as PivotActionEnvelope;
    const actionType = envelope.type;
    if (typeof actionType !== "string") continue;

    const handler = getActionHandler(actionType);
    if (!handler) continue;

    const payload =
      typeof envelope.payload === "object" && envelope.payload !== null
        ? (envelope.payload as ActionPayload)
        : {};

    handler.handle(payload, context);
  }
}
