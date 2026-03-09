import { useState, useRef, useEffect, useCallback, ChangeEvent, ClipboardEvent, FormEvent, KeyboardEvent } from 'react';
import { ArrowUp, Plus, Loader2, CheckCircle2, XCircle, AlertCircle, Brain, MessageSquare, Square, MessageCircle, Trash2, PlusCircle, PanelLeftClose, PanelLeft, ImagePlus, Paperclip, FileText, FileSpreadsheet, Presentation, Wrench } from 'lucide-react';
import { toast } from 'sonner';
import { formatTimestamp } from '../utils/timestamp';
import { getAuthToken, isTokenValid, AUTH_EXPIRED_EVENT } from '../contexts/auth-core';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  createSession,
  listSessions,
  deleteSession,
  getFullSessionHistory,
  getLLMById,
  deleteChatFile,
  fetchChatFileBlob,
  uploadChatFile,
  type ChatFileAsset,
  type FileUploadSource,
  SessionListItem,
  TaskMessage,
  RecursionDetail,
  API_BASE_URL,
} from '../utils/api';

/**
 * Props for ReactChatInterface component.
 */
interface ReactChatInterfaceProps {
  /** Unique identifier of the agent */
  agentId: number;
  /** Display name of the current agent shown in chat UI title copy */
  agentName?: string;
  /** Primary LLM configuration ID used to gate image upload affordances */
  primaryLlmId?: number;
}

/**
 * Stream event type from ReAct backend.
 */
type ReactStreamEventType =
  | 'skill_resolution_start'
  | 'skill_resolution_result'
  | 'token_rate'
  | 'recursion_start'
  | 'reasoning'
  | 'observe'
  | 'thought'
  | 'abstract'
  | 'action'
  | 'tool_call'
  | 'plan_update'
  | 'reflect'
  | 'answer'
  | 'clarify'
  | 'task_complete'
  | 'error';

/**
 * Token usage information.
 */
interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cached_input_tokens?: number;
}

/**
 * Stream event from ReAct backend.
 */
interface ReactStreamEvent {
  type: ReactStreamEventType;
  task_id: string;
  trace_id?: string | null;
  iteration: number;
  delta?: string | null;
  data?: unknown;
  timestamp: string;
  created_at?: string;
  updated_at?: string;
  tokens?: TokenUsage;
  total_tokens?: TokenUsage;
}

/**
 * Safely parse JSON text and return unknown on success.
 */
function parseJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

/**
 * Narrow unknown values to plain object records.
 */
function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

/**
 * Runtime guard for backend stream event payloads.
 */
function isReactStreamEvent(value: unknown): value is ReactStreamEvent {
  const record = asRecord(value);
  if (!record) return false;
  const traceId = record.trace_id;
  return (
    typeof record.type === 'string'
    && typeof record.task_id === 'string'
    && (traceId === undefined || typeof traceId === 'string' || traceId === null)
    && typeof record.iteration === 'number'
    && typeof record.timestamp === 'string'
  );
}

/**
 * Parse token-rate payload from streaming events.
 */
function parseTokenRateData(data: unknown): {
  tokensPerSecond: number;
  estimatedCompletionTokens: number;
} | null {
  const record = asRecord(data);
  if (!record) return null;

  const rawRate = record.tokens_per_second;
  const rawEstimated = record.estimated_completion_tokens;
  if (typeof rawRate !== 'number' || typeof rawEstimated !== 'number') {
    return null;
  }

  return {
    tokensPerSecond: Math.max(rawRate, 0),
    estimatedCompletionTokens: Math.max(Math.round(rawEstimated), 0),
  };
}

/**
 * Plan step payload shape from RE_PLAN output.
 */
interface PlanStepData {
  step_id: string;
  general_goal: string;
  specific_description: string;
  completion_criteria: string;
  status: string;
}

/**
 * Recursion record in chat history.
 */
interface RecursionRecord {
  uid: string;
  iteration: number;
  trace_id: string | null;
  thinking?: string;
  observe?: string;
  thought?: string;
  abstract?: string;
  action?: string;
  events: ReactStreamEvent[];
  status: 'running' | 'completed' | 'error';
  errorLog?: string;
  startTime: string;
  endTime?: string;
  tokens?: TokenUsage;
  liveTokensPerSecond?: number;
  estimatedCompletionTokens?: number;
  hasSeenPositiveRate?: boolean;
  zeroRateStreak?: number;
}

const ZERO_RATE_STREAK_TO_RENDER = 2;

/**
 * Skill selection status shown before recursion starts.
 */
interface SkillSelectionState {
  status: 'loading' | 'done';
  count: number;
  selectedSkills: string[];
  durationMs?: number;
  tokens?: TokenUsage;
}

/**
 * Image attachment metadata used by the chat UI.
 */
interface ChatAttachment {
  fileId: string;
  kind: 'image' | 'document';
  originalName: string;
  mimeType: string;
  format: string;
  extension: string;
  width: number;
  height: number;
  sizeBytes: number;
  pageCount?: number | null;
  canExtractText?: boolean;
  suspectedScanned?: boolean;
  textEncoding?: string | null;
  previewUrl?: string;
}

/**
 * Local upload queue item shown in the composer.
 */
interface PendingUploadItem extends ChatAttachment {
  clientId: string;
  source: FileUploadSource;
  status: 'uploading' | 'ready' | 'error';
  errorMessage?: string;
}

/**
 * Message in chat history.
 */
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  attachments?: ChatAttachment[];
  timestamp: string;
  task_id?: string;
  recursions?: RecursionRecord[];
  status?: 'running' | 'skill_resolving' | 'completed' | 'error' | 'waiting_input';
  totalTokens?: TokenUsage;
  skillSelection?: SkillSelectionState;
}

const AUTO_SCROLL_BOTTOM_THRESHOLD_PX = 96;
const CLIPBOARD_FILE_EXTENSION_BY_MIME: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
  "text/markdown": "md",
  "text/x-markdown": "md",
  "text/plain": "md",
};

/**
 * Build stable chat attachment metadata from API payloads.
 */
function toChatAttachment(file: ChatFileAsset, previewUrl?: string): ChatAttachment {
  return {
    fileId: file.file_id,
    kind: file.kind,
    originalName: file.original_name,
    mimeType: file.mime_type,
    format: file.format,
    extension: file.extension,
    width: file.width,
    height: file.height,
    sizeBytes: file.size_bytes,
    pageCount: file.page_count,
    canExtractText: file.can_extract_text,
    suspectedScanned: file.suspected_scanned,
    textEncoding: file.text_encoding,
    previewUrl,
  };
}

/**
 * Clipboard file objects occasionally lose their original filename across apps,
 * so infer a stable extension from MIME type before uploading.
 */
function normalizeClipboardFile(file: File, index: number): File {
  if (file.name) {
    return file;
  }

  const inferredExtension = CLIPBOARD_FILE_EXTENSION_BY_MIME[file.type]
    || file.type.split("/")[1]
    || "bin";
  return new File([file], `clipboard-${Date.now()}-${index}.${inferredExtension}`, {
    type: file.type || "application/octet-stream",
  });
}

/**
 * Render a deterministic icon for document attachments.
 */
function AttachmentFileIcon({ attachment }: { attachment: ChatAttachment }) {
  const extension = attachment.extension.toLowerCase();
  if (extension === 'pptx') {
    return <Presentation className="h-5 w-5 text-muted-foreground" />;
  }
  if (extension === 'xlsx') {
    return <FileSpreadsheet className="h-5 w-5 text-muted-foreground" />;
  }
  return <FileText className="h-5 w-5 text-muted-foreground" />;
}

/**
 * Fetch and render an authenticated image thumbnail.
 */
function AttachmentThumbnail({
  attachment,
  alt,
  className,
}: {
  attachment: ChatAttachment;
  alt: string;
  className?: string;
}) {
  const [src, setSrc] = useState<string | null>(attachment.previewUrl ?? null);
  const shouldRenderImage = attachment.kind === 'image' || attachment.mimeType.startsWith('image/');

  useEffect(() => {
    if (!shouldRenderImage) {
      setSrc(null);
      return;
    }

    if (attachment.previewUrl) {
      setSrc(attachment.previewUrl);
      return;
    }

    const controller = new AbortController();
    let objectUrl: string | null = null;

    const loadImage = async () => {
      try {
        const blob = await fetchChatFileBlob(attachment.fileId, controller.signal);
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      } catch (err) {
        if (controller.signal.aborted) {
          return;
        }
        console.error('Failed to load image attachment:', err);
      }
    };

    void loadImage();

    return () => {
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [attachment.fileId, attachment.previewUrl, shouldRenderImage]);

  if (!shouldRenderImage) {
    return (
      <div className={`flex h-full w-full items-start justify-center bg-muted pt-1.5 ${className ?? ''}`}>
        <AttachmentFileIcon attachment={attachment} />
      </div>
    );
  }

  if (src) {
    return (
      <img
        src={src}
        alt={alt}
        className={className ?? 'h-full w-full object-cover'}
      />
    );
  }

  return (
    <div className={`flex h-full w-full items-center justify-center bg-muted ${className ?? ''}`}>
      <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
    </div>
  );
}

/**
 * Component to fetch and display recursion state in a tooltip.
 */
function RecursionStateViewer({ taskId, iteration }: { taskId: string; iteration: number }) {
  const [state, setState] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Function to fetch state
  const fetchState = async () => {
    if (state) return;
    setLoading(true);
    try {
      const apiUrl = `${API_BASE_URL}/react/tasks/${taskId}/states/${iteration}`;

      const token = getAuthToken();
      const headers: Record<string, string> = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(apiUrl, { headers });
      if (!response.ok) throw new Error('Failed to fetch state');

      const data = await response.json() as { current_state: string };
      // current_state is a JSON string in the response
      const parsedState = JSON.parse(data.current_state) as unknown;
      setState(JSON.stringify(parsedState, null, 2));
    } catch (err) {
      setError('Failed to load state');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip onOpenChange={(open) => {
        if (open) void fetchState();
      }}>
        <TooltipTrigger asChild>
          <button className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-full hover:bg-muted focus:outline-none focus:ring-1 focus:ring-ring" title="View state">
            <AlertCircle className="w-3.5 h-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-[500px] max-h-[400px] overflow-auto p-4 font-mono text-xs shadow-lg border border-border">
          {loading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="w-3 h-3 animate-spin" />
              Loading state...
            </div>
          ) : error ? (
            <span className="text-destructive">{error}</span>
          ) : (
            <pre className="whitespace-pre-wrap break-all">
              {state}
            </pre>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/**
 * ReAct Chat interface component for agent interaction.
 * Displays streaming conversation with ReAct agent and shows execution details.
 */
function ReactChatInterface({ agentId, agentName, primaryLlmId }: ReactChatInterfaceProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRecursions, setExpandedRecursions] = useState<Record<string, boolean>>({});
  const [replyTaskId, setReplyTaskId] = useState<string | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const documentInputRef = useRef<HTMLInputElement>(null);
  const uploadControllersRef = useRef<Map<string, AbortController>>(new Map());
  const pendingFilesRef = useRef<PendingUploadItem[]>([]);
  const [pendingFiles, setPendingFiles] = useState<PendingUploadItem[]>([]);

  // Session state
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [isLoadingSession, setIsLoadingSession] = useState<boolean>(false);
  const [isInitialized, setIsInitialized] = useState<boolean>(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(false);
  const [supportsImageInput, setSupportsImageInput] = useState<boolean>(false);
  const previousMessageCountRef = useRef<number>(0);
  const autoScrollEnabledRef = useRef<boolean>(true);
  const lastScrollTopRef = useRef<number>(0);
  const forceAutoScrollNextRef = useRef<boolean>(false);

  /**
   * Build persisted skill selection state from historical task payload.
   */
  const buildSkillSelectionFromTask = useCallback((task: TaskMessage): SkillSelectionState | undefined => {
    const raw = task.skill_selection_result;
    if (!raw || typeof raw !== 'object') {
      return undefined;
    }

    const selectedSkills = Array.isArray(raw.selected_skills)
      ? raw.selected_skills.filter((item): item is string => typeof item === 'string' && item.length > 0)
      : [];
    const count = typeof raw.count === 'number' ? raw.count : selectedSkills.length;
    const durationMs = typeof raw.duration_ms === 'number' ? raw.duration_ms : undefined;

    const rawTokens = raw.tokens;
    const tokens: TokenUsage | undefined = rawTokens && typeof rawTokens === 'object'
      && typeof rawTokens.prompt_tokens === 'number'
      && typeof rawTokens.completion_tokens === 'number'
      && typeof rawTokens.total_tokens === 'number'
      ? {
        prompt_tokens: rawTokens.prompt_tokens,
        completion_tokens: rawTokens.completion_tokens,
        total_tokens: rawTokens.total_tokens,
        cached_input_tokens: typeof rawTokens.cached_input_tokens === 'number'
          ? rawTokens.cached_input_tokens
          : 0,
      }
      : undefined;

    return {
      status: 'done',
      count,
      selectedSkills,
      durationMs,
      tokens,
    };
  }, []);

  /**
   * Convert persisted task history into renderable chat messages.
   */
  const buildMessagesFromHistory = useCallback((tasks: TaskMessage[]): ChatMessage[] => {
    const loadedMessages: ChatMessage[] = [];

    for (const task of tasks) {
      loadedMessages.push({
        id: `user-${task.task_id}`,
        role: 'user',
        content: task.user_message,
        attachments: (task.files ?? []).map((file) => toChatAttachment(file)),
        timestamp: task.created_at,
      });

      const recursions: RecursionRecord[] = task.recursions.map((r: RecursionDetail) => {
        const events: ReactStreamEvent[] = [];

        if (r.action_type === 'CALL_TOOL') {
          let toolCalls: unknown[] = [];
          let toolResults: unknown[] = [];

          if (r.action_output) {
            const actionData = asRecord(parseJson(r.action_output));
            if (actionData && Array.isArray(actionData.tool_calls)) {
              toolCalls = actionData.tool_calls;
            }
          }

          if (r.tool_call_results) {
            const parsedResults = parseJson(r.tool_call_results);
            if (Array.isArray(parsedResults)) {
              toolResults = parsedResults;
            }
          }

          if (toolCalls.length > 0 || toolResults.length > 0) {
            events.push({
              type: 'tool_call',
              task_id: task.task_id,
              trace_id: r.trace_id,
              iteration: r.iteration,
              data: {
                tool_calls: toolCalls,
                tool_results: toolResults,
              },
              timestamp: r.updated_at,
            });
          }
        }

        if (r.action_type === 'RE_PLAN' && r.action_output) {
          const planData = parseJson(r.action_output);
          if (planData !== null) {
            events.push({
              type: 'plan_update',
              task_id: task.task_id,
              trace_id: r.trace_id,
              iteration: r.iteration,
              data: planData,
              timestamp: r.updated_at,
            });
          }
        }

        return {
          uid: `history-${task.task_id}-${r.trace_id || `iter-${r.iteration}`}`,
          iteration: r.iteration,
          trace_id: r.trace_id,
          thinking: r.thinking || undefined,
          observe: r.observe || undefined,
          thought: r.thought || undefined,
          abstract: r.abstract || undefined,
          action: r.action_type || undefined,
          events,
          status: r.status === 'done' ? 'completed' : r.status === 'error' ? 'error' : 'completed',
          errorLog: r.error_log || undefined,
          startTime: r.created_at,
          endTime: r.updated_at,
          tokens: {
            prompt_tokens: r.prompt_tokens,
            completion_tokens: r.completion_tokens,
            total_tokens: r.total_tokens,
            cached_input_tokens: r.cached_input_tokens ?? 0,
          },
        };
      });

      const aggregatedTaskTokens = recursions.reduce<TokenUsage>(
        (acc, recursion) => ({
          prompt_tokens: acc.prompt_tokens + (recursion.tokens?.prompt_tokens ?? 0),
          completion_tokens: acc.completion_tokens + (recursion.tokens?.completion_tokens ?? 0),
          total_tokens: acc.total_tokens + (recursion.tokens?.total_tokens ?? 0),
          cached_input_tokens: (acc.cached_input_tokens ?? 0) + (recursion.tokens?.cached_input_tokens ?? 0),
        }),
        {
          prompt_tokens: 0,
          completion_tokens: 0,
          total_tokens: 0,
          cached_input_tokens: 0,
        }
      );

      loadedMessages.push({
        id: `assistant-${task.task_id}`,
        role: 'assistant',
        content: task.agent_answer || '',
        timestamp: task.updated_at,
        task_id: task.task_id,
        recursions,
        skillSelection: buildSkillSelectionFromTask(task),
        status: task.status === 'completed' ? 'completed' : task.status === 'failed' ? 'error' : 'completed',
        totalTokens: {
          prompt_tokens: aggregatedTaskTokens.prompt_tokens,
          completion_tokens: aggregatedTaskTokens.completion_tokens,
          total_tokens: aggregatedTaskTokens.total_tokens || task.total_tokens,
          cached_input_tokens: aggregatedTaskTokens.cached_input_tokens ?? 0,
        },
      });
    }

    return loadedMessages;
  }, [buildSkillSelectionFromTask]);

  /**
   * Keep composer queue isolated from message history and clean up uploads safely.
   */
  const removePendingFile = useCallback(async (clientId: string) => {
    const target = pendingFiles.find((item) => item.clientId === clientId);
    if (!target) {
      return;
    }

    const controller = uploadControllersRef.current.get(clientId);
    if (controller) {
      controller.abort();
      uploadControllersRef.current.delete(clientId);
    }

    setPendingFiles((prev) => prev.filter((item) => item.clientId !== clientId));
    if (target.previewUrl) {
      URL.revokeObjectURL(target.previewUrl);
    }

    if (target.status === 'ready') {
      try {
        await deleteChatFile(target.fileId);
      } catch (err) {
        console.error('Failed to delete pending chat file:', err);
      }
    }
  }, [pendingFiles]);

  /**
   * Start upload verification for newly added files.
   */
  const enqueueFiles = useCallback((files: File[], source: FileUploadSource) => {
    files.forEach((file) => {
      const clientId = `${source}-${crypto.randomUUID()}`;
      const isPreviewableImage = file.type.startsWith('image/');
      const previewUrl = isPreviewableImage ? URL.createObjectURL(file) : undefined;
      const initialItem: PendingUploadItem = {
        clientId,
        fileId: '',
        kind: isPreviewableImage ? 'image' : 'document',
        originalName: file.name,
        mimeType: file.type || 'application/octet-stream',
        format: '',
        extension: file.name.split('.').pop()?.toLowerCase() || '',
        width: 0,
        height: 0,
        sizeBytes: file.size,
        previewUrl,
        source,
        status: 'uploading',
      };

      setPendingFiles((prev) => [...prev, initialItem]);

      const controller = new AbortController();
      uploadControllersRef.current.set(clientId, controller);

      const uploadFile = async () => {
        try {
          const uploadedFile = await uploadChatFile(file, source, controller.signal);
          setPendingFiles((prev) => prev.map((item) => (
            item.clientId === clientId
              ? {
                ...item,
                ...toChatAttachment(uploadedFile, previewUrl),
                status: 'ready',
              }
              : item
          )));
        } catch (err) {
          if (controller.signal.aborted) {
            return;
          }

          const errorMessage = err instanceof Error ? err.message : 'Failed to upload file';
          setPendingFiles((prev) => prev.map((item) => (
            item.clientId === clientId
              ? {
                ...item,
                status: 'error',
                errorMessage,
              }
              : item
          )));
        } finally {
          uploadControllersRef.current.delete(clientId);
        }
      };

      void uploadFile();
    });
  }, []);

  /**
   * Filter image uploads when the primary LLM does not support them.
   */
  const partitionFilesByImageCapability = useCallback((files: File[]) => {
    const acceptedFiles: File[] = [];
    let blockedImageCount = 0;

    files.forEach((file) => {
      if (file.type.startsWith('image/') && !supportsImageInput) {
        blockedImageCount += 1;
        return;
      }
      acceptedFiles.push(file);
    });

    return { acceptedFiles, blockedImageCount };
  }, [supportsImageInput]);

  /**
   * Handle file picker changes from the composer menu.
   */
  const handleFileInputChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(event.target.files ?? []);
    const { acceptedFiles, blockedImageCount } = partitionFilesByImageCapability(selectedFiles);
    if (blockedImageCount > 0) {
      toast.error('The primary LLM does not accept image input.');
    }
    if (acceptedFiles.length > 0) {
      enqueueFiles(acceptedFiles, 'local');
    }
    event.target.value = '';
  }, [enqueueFiles, partitionFilesByImageCapability]);

  /**
   * Handle document picker changes from the composer menu.
   */
  const handleDocumentInputChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(event.target.files ?? []);
    if (selectedFiles.length > 0) {
      enqueueFiles(selectedFiles, 'local');
    }
    event.target.value = '';
  }, [enqueueFiles]);

  /**
   * Accept pasted images and files from Clipboard API into the upload queue.
   */
  const handlePaste = useCallback((event: ClipboardEvent<HTMLTextAreaElement>) => {
    const clipboardFiles = new Map<string, File>();
    let clipboardIndex = 0;

    const addClipboardFile = (file: File | null) => {
      if (!file) {
        return;
      }

      const normalizedFile = normalizeClipboardFile(file, clipboardIndex);
      clipboardIndex += 1;
      const dedupeKey = [
        normalizedFile.name,
        normalizedFile.size,
        normalizedFile.type,
        normalizedFile.lastModified,
      ].join(':');
      clipboardFiles.set(dedupeKey, normalizedFile);
    };

    for (const item of Array.from(event.clipboardData.items)) {
      if (item.kind !== 'file') {
        continue;
      }
      addClipboardFile(item.getAsFile());
    }

    for (const file of Array.from(event.clipboardData.files)) {
      addClipboardFile(file);
    }

    const filesToUpload = Array.from(clipboardFiles.values());
    if (filesToUpload.length === 0) {
      return;
    }

    const { acceptedFiles, blockedImageCount } = partitionFilesByImageCapability(filesToUpload);
    if (acceptedFiles.length === 0) {
      if (blockedImageCount > 0) {
        toast.error('The primary LLM does not accept image input.');
      }
      return;
    }

    event.preventDefault();
    if (blockedImageCount > 0) {
      toast.error('The primary LLM does not accept image input.');
    }
    enqueueFiles(acceptedFiles, 'clipboard');
  }, [enqueueFiles, partitionFilesByImageCapability]);

  /**
   * Reload the session list for current agent.
   * Used after task completion so subject/message_count update immediately.
   */
  const refreshSessionList = useCallback(async (): Promise<SessionListItem[]> => {
    const response = await listSessions(agentId);
    setSessions(response.sessions);
    return response.sessions;
  }, [agentId]);

  /**
   * Initialize sessions on mount.
   * Loads existing sessions without creating one implicitly.
   * New sessions are created only by explicit user action or first send.
   */
  useEffect(() => {
    const initSessions = async () => {
      if (isInitialized || isLoadingSession) return;

      setIsLoadingSession(true);
      try {
        // First, load existing sessions
        const existingSessions = await refreshSessionList();

        // If there are existing sessions, select the most recent one and load its history
        if (existingSessions.length > 0) {
          const firstSessionId = existingSessions[0].session_id;
          setCurrentSessionId(firstSessionId);

          // Load history for the first session
          try {
            const history = await getFullSessionHistory(firstSessionId);
            setMessages(buildMessagesFromHistory(history.tasks));
          } catch (historyErr) {
            console.error('Failed to load initial session history:', historyErr);
          }
        } else {
          // Keep empty state. Session is created only by explicit user action
          // or lazily on first message send.
          setCurrentSessionId(null);
          setMessages([]);
        }

        setIsInitialized(true);
      } catch (err) {
        console.error('Failed to initialize sessions:', err);
        setError('Failed to initialize session');
      } finally {
        setIsLoadingSession(false);
      }
    };
    void initSessions();
  }, [agentId, buildMessagesFromHistory, isInitialized, isLoadingSession, refreshSessionList]);

  /**
   * Abort in-flight uploads when the chat UI unmounts.
   */
  useEffect(() => () => {
    uploadControllersRef.current.forEach((controller) => controller.abort());
    uploadControllersRef.current.clear();
    pendingFilesRef.current.forEach((item) => {
      if (item.previewUrl) {
        URL.revokeObjectURL(item.previewUrl);
      }
    });
  }, []);

  useEffect(() => {
    pendingFilesRef.current = pendingFiles;
  }, [pendingFiles]);

  /**
   * Resolve primary LLM image-input support for composer capability gating.
   *
   * Why: users should not see or trigger image attachment paths when the
   * selected primary model cannot consume them.
   */
  useEffect(() => {
    let isCancelled = false;

    if (!primaryLlmId) {
      setSupportsImageInput(false);
      return () => {
        isCancelled = true;
      };
    }

    setSupportsImageInput(false);

    const loadPrimaryLlm = async () => {
      try {
        const llm = await getLLMById(primaryLlmId);
        if (!isCancelled) {
          setSupportsImageInput(llm.image_input);
        }
      } catch (err) {
        if (!isCancelled) {
          console.error('Failed to load primary LLM capabilities:', err);
          setSupportsImageInput(false);
        }
      }
    };

    void loadPrimaryLlm();

    return () => {
      isCancelled = true;
    };
  }, [primaryLlmId]);

  /**
   * Create a new session and switch to it.
   */
  const handleNewSession = async () => {
    setIsLoadingSession(true);
    try {
      autoScrollEnabledRef.current = true;
      forceAutoScrollNextRef.current = true;
      const session = await createSession(agentId);
      setCurrentSessionId(session.session_id);
      setMessages([]); // Clear messages for new session
      setPendingFiles([]);
      setSessions((prev) => [{
        session_id: session.session_id,
        agent_id: session.agent_id,
        status: session.status,
        subject: session.subject?.content || null,
        created_at: session.created_at,
        updated_at: session.updated_at,
        message_count: 0,
      }, ...prev]);
    } catch (err) {
      console.error('Failed to create new session:', err);
      setError('Failed to create new session');
    } finally {
      setIsLoadingSession(false);
    }
  };

  /**
   * Switch to an existing session and load its history.
   */
  const handleSelectSession = async (sessionId: string) => {
    if (sessionId === currentSessionId || isLoadingSession) return;

    setCurrentSessionId(sessionId);
    setIsLoadingSession(true);
    setPendingFiles([]);
    autoScrollEnabledRef.current = true;
    forceAutoScrollNextRef.current = true;

    try {
      // Load full session history with recursion details
      const history = await getFullSessionHistory(sessionId);

      setMessages(buildMessagesFromHistory(history.tasks));
    } catch (err) {
      console.error('Failed to load session history:', err);
      setMessages([]); // Clear messages on error
    } finally {
      setIsLoadingSession(false);
    }
  };

  /**
   * Delete a session.
   */
  const handleDeleteSession = async (sessionId: string) => {
    try {
      await deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
      if (sessionId === currentSessionId) {
        // Switch to another session or clear if no sessions left
        const remainingSessions = sessions.filter((s) => s.session_id !== sessionId);
        if (remainingSessions.length > 0) {
          void handleSelectSession(remainingSessions[0].session_id);
        } else {
          // Create a new session if all are deleted
          setCurrentSessionId(null);
          setMessages([]);
          setIsInitialized(false); // Allow re-initialization to create new session
        }
      }
    } catch (err) {
      console.error('Failed to delete session:', err);
      setError('Failed to delete session');
    }
  };

  /**
   * Scroll chat view to bottom.
   */
  const scrollToBottom = useCallback((behavior: ScrollBehavior) => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) return;

    // Keep a small bottom gap so the newest bubble does not touch the edge.
    const bottomGap = 20;
    const targetTop = Math.max(
      scrollContainer.scrollHeight - scrollContainer.clientHeight - bottomGap,
      0
    );
    lastScrollTopRef.current = targetTop;
    scrollContainer.scrollTo({ top: targetTop, behavior });
  }, []);

  /**
   * Whether scroll position is currently near the bottom.
   */
  const isNearBottom = useCallback((): boolean => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) return true;
    const distanceToBottom =
      scrollContainer.scrollHeight
      - scrollContainer.scrollTop
      - scrollContainer.clientHeight;
    return distanceToBottom <= AUTO_SCROLL_BOTTOM_THRESHOLD_PX;
  }, []);

  /**
   * Track manual scroll so we don't force-scroll while user reads history.
   */
  const handleScroll = useCallback(() => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) return;

    const currentTop = scrollContainer.scrollTop;
    const userScrolledUp = currentTop + 2 < lastScrollTopRef.current;
    const nearBottom = isNearBottom();

    if (userScrolledUp) {
      autoScrollEnabledRef.current = false;
      forceAutoScrollNextRef.current = false;
    } else if (nearBottom) {
      autoScrollEnabledRef.current = true;
    }

    lastScrollTopRef.current = currentTop;
  }, [isNearBottom]);

  /**
   * Auto-scroll to bottom when messages update.
   */
  useEffect(() => {
    const forceAutoScroll = forceAutoScrollNextRef.current;
    const scrollContainer = scrollContainerRef.current;
    if (scrollContainer && !forceAutoScroll) {
      // Guard against missed scroll events: if viewport is far from bottom,
      // treat it as manual history browsing and stop force-follow.
      const distanceToBottom =
        scrollContainer.scrollHeight
        - scrollContainer.scrollTop
        - scrollContainer.clientHeight;
      if (distanceToBottom > AUTO_SCROLL_BOTTOM_THRESHOLD_PX) {
        autoScrollEnabledRef.current = false;
      }
    }

    if (!autoScrollEnabledRef.current && !forceAutoScroll) {
      previousMessageCountRef.current = messages.length;
      return;
    }

    const behavior: ScrollBehavior =
      messages.length > previousMessageCountRef.current ? 'smooth' : 'auto';
    scrollToBottom(behavior);
    forceAutoScrollNextRef.current = false;
    previousMessageCountRef.current = messages.length;
  }, [messages, scrollToBottom]);

  const readyPendingFiles = pendingFiles.filter((item) => item.status === 'ready' && item.fileId);
  const hasUploadingFiles = pendingFiles.some((item) => item.status === 'uploading');
  const canSendMessage = !isStreaming && !hasUploadingFiles && (
    inputMessage.trim().length > 0 || readyPendingFiles.length > 0
  );

  /**
   * Handle form submission to send message.
   */
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (canSendMessage) {
        void sendMessage();
      }
    }
  };

  /**
   * Handle form submission to send message.
   */
  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!canSendMessage) return;

    void sendMessage();
  };

  /**
   * Stop the current streaming execution.
   * Aborts the fetch request and cancels LLM execution.
   */
  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  };

  /**
   * Send message to ReAct agent.
   */
  const sendMessage = async () => {
    // If replying, use the replyTaskId. Otherwise undefined.
    const currentReplyTaskId = replyTaskId;
    const filesToSend = readyPendingFiles;
    const sentAttachments = filesToSend.map((file) => ({
      fileId: file.fileId,
      kind: file.kind,
      originalName: file.originalName,
      mimeType: file.mimeType,
      format: file.format,
      extension: file.extension,
      width: file.width,
      height: file.height,
      sizeBytes: file.sizeBytes,
      pageCount: file.pageCount,
      canExtractText: file.canExtractText,
      suspectedScanned: file.suspectedScanned,
      textEncoding: file.textEncoding,
      previewUrl: file.previewUrl,
    }));

    // Reset reply state if we are sending
    if (currentReplyTaskId) {
      setReplyTaskId(null);
    }

    autoScrollEnabledRef.current = true;
    forceAutoScrollNextRef.current = true;
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: inputMessage,
      attachments: sentAttachments,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputMessage('');
    setPendingFiles((prev) => prev.filter((item) => item.status !== 'ready'));
    setError(null);
    setIsStreaming(true);

    // Create assistant message placeholder
    const assistantMessageId = `assistant-${Date.now()}`;
    const assistantMessage: ChatMessage = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      recursions: [],
      status: 'running',
    };

    setMessages((prev) => [...prev, assistantMessage]);

    // Start SSE stream
    abortControllerRef.current = new AbortController();

    try {
      // Lazily create a session only when user sends the first message.
      let activeSessionId = currentSessionId;
      if (!activeSessionId) {
        const session = await createSession(agentId);
        activeSessionId = session.session_id;
        setCurrentSessionId(activeSessionId);
        setSessions((prev) => [{
          session_id: session.session_id,
          agent_id: session.agent_id,
          status: session.status,
          subject: session.subject?.content || null,
          created_at: session.created_at,
          updated_at: session.updated_at,
          message_count: 0,
        }, ...prev]);
      }

      // Check token validity before making request
      if (!isTokenValid()) {
        window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
        throw new Error('Token expired or invalid. Please log in again.');
      }

      // Use direct backend URL to bypass Vite proxy for SSE streaming
      // This prevents potential data loss in proxy layer
      const apiUrl = `${API_BASE_URL}/react/chat/stream`;

      const token = getAuthToken();
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      };

      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(apiUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          agent_id: agentId,
          message: userMessage.content,
          user: 'web-user',
          task_id: currentReplyTaskId,
          session_id: activeSessionId,
          file_ids: filesToSend.map((file) => file.fileId),
        }),
        signal: abortControllerRef.current.signal,
      });

      // Handle 401 Unauthorized
      if (response.status === 401) {
        window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
        throw new Error('Authentication expired. Please log in again.');
      }

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      if (!response.body) {
        throw new Error('Response body is null');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let currentTaskId: string | null = null;
      let currentRecursion: RecursionRecord | null = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.trim() || !line.startsWith('data: ')) continue;

          const data = line.slice(6).trim();
          if (!data) continue;

          try {
            const parsedEvent = parseJson(data);
            if (!isReactStreamEvent(parsedEvent)) {
              continue;
            }
            const event: ReactStreamEvent = parsedEvent;

            if (event.type === 'skill_resolution_start') {
              currentTaskId = event.task_id;
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantMessageId
                    ? {
                      ...msg,
                      task_id: currentTaskId ?? undefined,
                      status: 'skill_resolving' as const,
                      skillSelection: {
                        status: 'loading',
                        count: 0,
                        selectedSkills: [],
                      },
                    }
                    : msg
                )
              );
            } else if (event.type === 'skill_resolution_result') {
              const skillData = event.data as {
                count?: number;
                selected_skills?: string[];
                duration_ms?: number;
                tokens?: TokenUsage;
              } | undefined;
              const selectedSkills = skillData?.selected_skills ?? [];
              const selectedCount = typeof skillData?.count === 'number'
                ? skillData.count
                : selectedSkills.length;

              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantMessageId
                    ? {
                      ...msg,
                      status: 'running' as const,
                      skillSelection: {
                        status: 'done',
                        count: selectedCount,
                        selectedSkills,
                        durationMs: skillData?.duration_ms,
                        tokens: skillData?.tokens,
                      },
                    }
                    : msg
                )
              );
            } else if (event.type === 'recursion_start') {
              // Mark previous recursion as completed if it's still running.
              // Capture a snapshot before setMessages — the callback is enqueued
              // and executed later; by then currentRecursion may point elsewhere.
              if (currentRecursion && currentRecursion.status === 'running') {
                const prevRecursionSnapshot: RecursionRecord = {
                  ...currentRecursion,
                  status: 'completed',
                  endTime: event.timestamp,
                };
                // Also update the local variable so subsequent code sees the right state
                currentRecursion = prevRecursionSnapshot;
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id === assistantMessageId) {
                      // Filter out nulls and update matching recursion
                      const filtered = (msg.recursions || []).filter((r): r is RecursionRecord => r !== null);
                      const updatedRecursions = filtered.map((r) =>
                        r.uid === prevRecursionSnapshot.uid ? prevRecursionSnapshot : r
                      );
                      return { ...msg, recursions: updatedRecursions };
                    }
                    return msg;
                  })
                );
              }

              // Start new recursion
              currentTaskId = event.task_id;
              const newRecursionSnapshot: RecursionRecord = {
                uid: `live-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
                iteration: event.iteration,
                trace_id: event.trace_id ?? null,
                events: [event],
                status: 'running',
                startTime: event.timestamp,
                liveTokensPerSecond: undefined,
                estimatedCompletionTokens: 0,
                hasSeenPositiveRate: false,
                zeroRateStreak: 0,
              };
              currentRecursion = newRecursionSnapshot;

              // Capture snapshot here for the same stale-closure reason
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantMessageId
                    ? {
                      ...msg,
                      status: 'running',
                      skillSelection: msg.skillSelection?.status === 'loading'
                        ? {
                          ...msg.skillSelection,
                          status: 'done',
                          count: 0,
                          selectedSkills: [],
                        }
                        : msg.skillSelection,
                      task_id: currentTaskId ?? undefined,
                      // Filter out any nulls from previous state before adding new recursion
                      recursions: [...(msg.recursions?.filter((r): r is RecursionRecord => r !== null) || []), newRecursionSnapshot],
                    }
                    : msg
                )
              );
            } else if (currentRecursion && currentTaskId) {
              // Create new events array to ensure React detects state changes
              const existingRecursion: RecursionRecord = currentRecursion;
              const updatedEvents: ReactStreamEvent[] = [...existingRecursion.events, event];

              if (event.type === 'token_rate') {
                const tokenRate = parseTokenRateData(event.data);
                if (tokenRate) {
                  const previousRate = existingRecursion.liveTokensPerSecond;
                  const previousHasSeenPositiveRate = existingRecursion.hasSeenPositiveRate === true;
                  const previousZeroRateStreak = existingRecursion.zeroRateStreak ?? 0;

                  let nextRate: number | undefined = previousRate;
                  let nextHasSeenPositiveRate = previousHasSeenPositiveRate;
                  let nextZeroRateStreak = previousZeroRateStreak;

                  if (tokenRate.tokensPerSecond > 0) {
                    nextRate = tokenRate.tokensPerSecond;
                    nextHasSeenPositiveRate = true;
                    nextZeroRateStreak = 0;
                  } else if (!previousHasSeenPositiveRate) {
                    // Before we observe a positive throughput, suppress leading
                    // zero-rate flashes that make the meter feel jittery.
                    nextRate = undefined;
                    nextZeroRateStreak = 0;
                  } else {
                    nextZeroRateStreak = previousZeroRateStreak + 1;
                    if (nextZeroRateStreak >= ZERO_RATE_STREAK_TO_RENDER) {
                      nextRate = 0;
                    }
                  }

                  currentRecursion = {
                    ...existingRecursion,
                    trace_id: event.trace_id || existingRecursion.trace_id,
                    events: updatedEvents,
                    liveTokensPerSecond: nextRate,
                    estimatedCompletionTokens: tokenRate.estimatedCompletionTokens,
                    hasSeenPositiveRate: nextHasSeenPositiveRate,
                    zeroRateStreak: nextZeroRateStreak,
                  };
                } else {
                  currentRecursion = {
                    ...existingRecursion,
                    trace_id: event.trace_id || existingRecursion.trace_id,
                    events: updatedEvents,
                  };
                }
              } else if (event.type === 'observe') {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  observe: event.delta ?? '',
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === 'reasoning') {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  thinking: `${existingRecursion.thinking ?? ''}${event.delta ?? ''}`,
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === 'thought') {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  thought: event.delta ?? '',
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === 'abstract') {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  abstract: event.delta ?? '',
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === 'action') {
                // Mark recursion as completed after action event
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  action: event.delta ?? '',
                  status: 'completed' as const,
                  endTime: event.timestamp,
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === 'tool_call') {
                // Tool call event - just add to events, no special field update needed
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                };
              } else if (event.type === 'error') {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  status: 'error' as const,
                  endTime: event.timestamp,
                  // Preserve tokens if available in error event
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === 'answer') {
                // Answer event - update message content and mark recursion completed
                const answerData = event.data as { answer?: string } | undefined;
                if (answerData?.answer) {
                  setMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === assistantMessageId
                        ? {
                          ...msg,
                          content: answerData.answer ?? '',
                        }
                        : msg
                    )
                  );
                }
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  status: 'completed' as const,
                  endTime: event.timestamp,
                };
              } else if (event.type === 'clarify') {
                // For CLARIFY, we set content similar to ANSWER so it shows in the main box
                const clarifyData = event.data as { question?: string } | undefined;
                if (clarifyData?.question) {
                  setMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === assistantMessageId
                        ? {
                          ...msg,
                          content: clarifyData.question ?? '',
                          status: 'waiting_input' as const,
                        }
                        : msg
                    )
                  );
                }
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  status: 'completed' as const,
                  endTime: event.timestamp,
                };
              } else if (event.type === 'task_complete') {
                // Task complete - update message status and all running recursions
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id === assistantMessageId) {
                      // Filter out nulls and mark all running recursions as completed
                      const filtered = (msg.recursions || []).filter((r): r is RecursionRecord => r !== null);
                      const updatedRecursions = filtered.map((r) =>
                        r.status === 'running'
                          ? { ...r, status: 'completed' as const, endTime: event.timestamp }
                          : r
                      );
                      return {
                        ...msg,
                        status: 'completed',
                        skillSelection: msg.skillSelection?.status === 'loading'
                          ? {
                            ...msg.skillSelection,
                            status: 'done',
                            count: 0,
                            selectedSkills: [],
                          }
                          : msg.skillSelection,
                        recursions: updatedRecursions,
                        timestamp: event.timestamp,  // Update to task completion time
                        totalTokens: event.total_tokens,  // Save total token usage
                      };
                    }
                    return msg;
                  })
                );
                // Don't update currentRecursion for task_complete - it's handled above
                // Skip the general setMessages call below
                currentRecursion = null;

                // Refresh session list so updated subject/message_count are visible
                // immediately in sidebar without re-entering the page.
                void refreshSessionList().catch((refreshErr) => {
                  console.error('Failed to refresh session list after task completion:', refreshErr);
                });
              } else {
                // Handle other events (plan_update, reflect, etc.) - just add to events
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                };
              }

              // Update recursion events - preserve all currentRecursion data.
              // Skip if currentRecursion was set to null (e.g., for task_complete).
              // IMPORTANT: Capture currentRecursion into an immutable const snapshot
              // BEFORE calling setMessages. React state updater functions are enqueued
              // and executed asynchronously during reconciliation. The `currentRecursion`
              // let-variable may be mutated (or nulled) by a later SSE event before
              // React runs this callback, causing a null-dereference crash at runtime.
              if (currentRecursion) {
                const frozenRecursion: RecursionRecord = currentRecursion;
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id === assistantMessageId) {
                      // Filter out nulls and update matching recursion
                      const filtered = (msg.recursions || []).filter((r): r is RecursionRecord => r !== null);
                      const updatedRecursions = filtered.map((r) =>
                        r.uid === frozenRecursion.uid
                          ? { ...frozenRecursion }
                          : r
                      );
                      return { ...msg, recursions: updatedRecursions };
                    }
                    return msg;
                  })
                );
              }
            }
          } catch (err) {
            console.error('Failed to parse SSE event:', err);
          }
        }
      }

      setIsStreaming(false);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        // User cancelled - mark current recursion as cancelled
        const cancelTime = new Date().toISOString();
        setMessages((prev) =>
          prev.map((msg) => {
            if (msg.id === assistantMessageId) {
              // Filter out nulls first, then mark the last running recursion as cancelled
              const filteredRecursions = msg.recursions?.filter((r): r is RecursionRecord => r !== null) || [];
              const updatedRecursions = filteredRecursions.map((r, idx, arr) =>
                idx === arr.length - 1 && r.status === 'running'
                  ? { ...r, status: 'error' as const, endTime: cancelTime }
                  : r
              );
              return {
                ...msg,
                status: 'error',
                content: msg.content || 'Execution stopped by user',
                skillSelection: msg.skillSelection?.status === 'loading'
                  ? {
                    ...msg.skillSelection,
                    status: 'done',
                    count: 0,
                    selectedSkills: [],
                  }
                  : msg.skillSelection,
                recursions: updatedRecursions,
                timestamp: cancelTime,  // Update to cancellation time
              };
            }
            return msg;
          })
        );
      } else {
        const error = err instanceof Error ? err : new Error(String(err));
        const errorTime = new Date().toISOString();
        setError(error.message);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId
              ? {
                ...msg,
                status: 'error',
                content: `Error: ${error.message}`,
                skillSelection: msg.skillSelection?.status === 'loading'
                  ? {
                    ...msg.skillSelection,
                    status: 'done',
                    count: 0,
                    selectedSkills: [],
                  }
                  : msg.skillSelection,
                timestamp: errorTime,  // Update to error time
              }
              : msg
          )
        );
      }
      setIsStreaming(false);
    }
  };

  /**
   * Toggle recursion expansion.
   */
  const toggleRecursion = (messageId: string, recursionUid: string) => {
    const key = `${messageId}-${recursionUid}`;
    setExpandedRecursions((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  /**
   * Format answer content with basic markdown support.
   * Handles: ### and #### headings, **bold**, line breaks, and paragraphs.
   */
  const formatAnswerContent = (content: string) => {
    if (!content) return null;

    // First, normalize paragraph breaks
    // Split content into blocks by analyzing heading patterns
    const lines = content.split('\n');
    const blocks: string[] = [];
    let currentBlock: string[] = [];

    for (const line of lines) {
      // Check if line is a heading
      if (line.match(/^#{3,4}\s+/)) {
        // Save current block if it has content
        if (currentBlock.length > 0) {
          blocks.push(currentBlock.join('\n'));
          currentBlock = [];
        }
        // Start new block with heading
        currentBlock.push(line);
      } else if (line.trim() === '' && currentBlock.length > 0) {
        // Empty line - might be paragraph break
        currentBlock.push(line);
      } else {
        // Regular content line
        currentBlock.push(line);
      }
    }

    // Add final block
    if (currentBlock.length > 0) {
      blocks.push(currentBlock.join('\n'));
    }

    // Render blocks
    return blocks.map((block, bIdx) => {
      const trimmedBlock = block.trim();
      if (!trimmedBlock) return null;

      // Check for headings (must use #### before ### to avoid false matches)
      const h4Match = trimmedBlock.match(/^####\s+(.+?)(\n|$)/);
      const h3Match = trimmedBlock.match(/^###\s+(.+?)(\n|$)/);

      if (h4Match) {
        const headingText = h4Match[1];
        const remainingText = trimmedBlock.substring(h4Match[0].length).trim();

        return (
          <div key={bIdx} className="mb-2.5">
            <h4 className="text-sm font-semibold text-foreground mb-1.5">{headingText}</h4>
            {remainingText && (
              <div className="text-sm text-foreground leading-relaxed">
                {formatInlineMarkdown(remainingText)}
              </div>
            )}
          </div>
        );
      }

      if (h3Match) {
        const headingText = h3Match[1];
        const remainingText = trimmedBlock.substring(h3Match[0].length).trim();

        return (
          <div key={bIdx} className="mb-3">
            <h3 className="text-base font-bold text-foreground mb-2">{headingText}</h3>
            {remainingText && (
              <div className="text-sm text-foreground leading-relaxed">
                {formatInlineMarkdown(remainingText)}
              </div>
            )}
          </div>
        );
      }

      // Regular paragraph
      return (
        <p key={bIdx} className="text-sm text-foreground leading-relaxed mb-2">
          {formatInlineMarkdown(trimmedBlock)}
        </p>
      );
    }).filter(Boolean);
  };

  /**
   * Format inline markdown (bold, line breaks).
   */
  const formatInlineMarkdown = (text: string) => {
    const parts: (string | JSX.Element)[] = [];
    let lastIndex = 0;

    // Match **bold** patterns
    const boldPattern = /\*\*(.+?)\*\*/g;
    let match;

    while ((match = boldPattern.exec(text)) !== null) {
      // Add text before match
      if (match.index > lastIndex) {
        const beforeText = text.substring(lastIndex, match.index);
        parts.push(...formatLineBreaks(beforeText, parts.length));
      }

      // Add bold text
      parts.push(
        <strong key={`bold-${match.index}`} className="font-semibold">
          {match[1]}
        </strong>
      );

      lastIndex = match.index + match[0].length;
    }

    // Add remaining text
    if (lastIndex < text.length) {
      parts.push(...formatLineBreaks(text.substring(lastIndex), parts.length));
    }

    return parts;
  };

  /**
   * Convert line breaks to <br /> tags.
   */
  const formatLineBreaks = (text: string, startKey: number) => {
    const lines = text.split('\n');
    const result: (string | JSX.Element)[] = [];

    lines.forEach((line, idx) => {
      if (idx > 0) {
        result.push(<br key={`br-${startKey}-${idx}`} />);
      }
      if (line) {
        result.push(line);
      }
    });

    return result;
  };

  /**
   * Calculate duration in seconds between two ISO timestamps.
   */
  const calculateDuration = (startTime: string, endTime?: string): number => {
    if (!endTime) return 0;
    const start = new Date(startTime).getTime();
    const end = new Date(endTime).getTime();
    return Math.round((end - start) / 1000 * 10) / 10; // Round to 1 decimal place
  };

  /**
   * Format token count with thousands separator.
   */
  const formatTokenCount = (count: number): string => {
    return count.toLocaleString();
  };

  /**
   * Render token usage with hoverable details.
   */
  const renderTokenUsage = (tokens: TokenUsage, label: string, className?: string) => {
    return (
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className={className ?? "text-xs text-muted-foreground tabular-nums whitespace-nowrap cursor-help underline decoration-dotted underline-offset-2"}>
              {label}
            </span>
          </TooltipTrigger>
          <TooltipContent side="top" className="text-xs leading-relaxed">
            <div>Input: {formatTokenCount(tokens.prompt_tokens)}</div>
            <div>Cached Input: {formatTokenCount(tokens.cached_input_tokens ?? 0)}</div>
            <div>Output: {formatTokenCount(tokens.completion_tokens)}</div>
            <div>Total: {formatTokenCount(tokens.total_tokens)}</div>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  };

  /**
   * Check if recursion has any failed tool calls.
   */
  const hasFailedTools = (recursion: RecursionRecord): boolean => {
    const toolCallEvents = recursion.events.filter((e) => e.type === 'tool_call');

    for (const event of toolCallEvents) {
      const toolData = event.data as {
        tool_results?: Array<{ success: boolean }>;
      } | undefined;

      if (toolData?.tool_results?.some((result) => !result.success)) {
        return true;
      }
    }

    return false;
  };

  /**
   * Get effective recursion status considering tool execution results.
   */
  const getRecursionStatus = (recursion: RecursionRecord): 'running' | 'completed' | 'warning' | 'error' => {
    if (recursion.status === 'running') return 'running';
    if (recursion.status === 'error') return 'error';

    // If status is 'completed', check if there are failed tools
    if (hasFailedTools(recursion)) {
      return 'warning';
    }

    return 'completed';
  };

  /**
   * Render a recursion record.
   */
  const renderRecursion = (messageId: string, recursion: RecursionRecord, taskId?: string) => {
    const key = `${messageId}-${recursion.uid}`;
    const isExpanded = expandedRecursions[key];
    const effectiveStatus = getRecursionStatus(recursion);

    const toolCallEvents = recursion.events.filter((e) => e.type === 'tool_call');

    return (
      <div key={key} className="border border-border rounded-md mb-3 overflow-hidden bg-muted/20">
        {/* Header */}
        <button
          onClick={() => toggleRecursion(messageId, recursion.uid)}
          className="w-full flex items-center justify-between px-3 py-2 hover:bg-muted/30 transition-colors"
        >
          <div className="flex items-center gap-2 flex-1 min-w-0">
            {effectiveStatus === 'running' && (
              <Loader2
                key={`${key}-running`}
                className="w-3.5 h-3.5 text-primary animate-spin flex-shrink-0"
              />
            )}
            {effectiveStatus === 'completed' && (
              <CheckCircle2
                key={`${key}-completed`}
                className="w-3.5 h-3.5 text-success flex-shrink-0 status-icon-enter"
              />
            )}
            {effectiveStatus === 'warning' && (
              <AlertCircle
                key={`${key}-warning`}
                className="w-3.5 h-3.5 text-warning flex-shrink-0 status-icon-enter"
              />
            )}
            {effectiveStatus === 'error' && (
              <XCircle
                key={`${key}-error`}
                className="w-3.5 h-3.5 text-danger flex-shrink-0 status-icon-enter"
              />
            )}
            {effectiveStatus === 'running' && !recursion.abstract ? (
              <span
                className="text-xs font-semibold truncate animate-thinking-wave"
                style={{
                  background: 'linear-gradient(90deg, #9ca3af 0%, #e5e7eb 25%, #f3f4f6 50%, #e5e7eb 75%, #9ca3af 100%)',
                  backgroundSize: '400% 100%',
                  WebkitBackgroundClip: 'text',
                  backgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                }}
              >
                Thinking...
              </span>
            ) : (
              <span
                className="text-xs font-semibold text-foreground truncate"
                title={recursion.abstract || `Iteration ${recursion.iteration + 1}`}
              >
                {recursion.abstract || `Iteration ${recursion.iteration + 1}`}
              </span>
            )}
            {toolCallEvents.length > 0 && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-primary/10 text-primary flex-shrink-0">
                {toolCallEvents.length} tool{toolCallEvents.length > 1 ? 's' : ''}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2.5 flex-shrink-0">
            {recursion.endTime && (
              <span className="text-xs text-muted-foreground tabular-nums">
                {calculateDuration(recursion.startTime, recursion.endTime)}s
              </span>
            )}
            {recursion.status === 'running' && typeof recursion.liveTokensPerSecond === 'number' ? (
              <span
                className="text-xs text-muted-foreground tabular-nums whitespace-nowrap"
                title={
                  typeof recursion.estimatedCompletionTokens === 'number'
                    ? `Estimated output: ${formatTokenCount(recursion.estimatedCompletionTokens)} tokens`
                    : undefined
                }
              >
                {recursion.liveTokensPerSecond.toFixed(1)} tokens/s
              </span>
            ) : recursion.tokens && (
              renderTokenUsage(
                recursion.tokens,
                `${formatTokenCount(recursion.tokens.total_tokens)} tokens`
              )
            )}
          </div>
        </button>

        {isExpanded && (
          <div className="px-3 pb-3 space-y-2">
            {/* Provider Thinking */}
            {recursion.thinking && (
              <div className="bg-background/60 rounded border border-border p-2">
                <div className="flex items-center gap-1.5 mb-1.5">
                  <Brain className="w-3.5 h-3.5 text-primary" />
                  <span className="text-xs font-semibold text-foreground">THINKING</span>
                </div>
                <div className="max-h-64 overflow-y-auto pl-5 pr-1 text-xs text-muted-foreground whitespace-pre-wrap break-words leading-relaxed">
                  {recursion.thinking}
                </div>
              </div>
            )}

            {/* Observe */}
            {recursion.observe && (
              <div className="bg-background/50 rounded border border-border p-2">
                <div className="flex items-center gap-1.5 mb-1">
                  <div className="w-3.5 h-3.5 flex items-center justify-center">
                    <div className="w-1 h-4 bg-blue-500 rounded-full" />
                  </div>
                  <span className="text-xs font-semibold text-foreground">OBSERVE</span>
                </div>
                <p className="text-xs text-muted-foreground pl-5 leading-relaxed">
                  {recursion.observe}
                </p>
              </div>
            )}

            {/* Thought */}
            {recursion.thought && (
              <div className="bg-background/50 rounded border border-border p-2">
                <div className="flex items-center gap-1.5 mb-1">
                  <Brain className="w-3.5 h-3.5 text-purple-500" />
                  <span className="text-xs font-semibold text-foreground">THOUGHT</span>
                </div>
                <p className="text-xs text-muted-foreground pl-5 leading-relaxed">
                  {recursion.thought}
                </p>
              </div>
            )}

            {/* Action */}
            {recursion.action && (
              <div className="bg-background/50 rounded border border-border p-2">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5">
                    <div className="w-3.5 h-3.5 flex items-center justify-center">
                      <div className="w-1 h-4 bg-green-500 rounded-full" />
                    </div>
                    <span className="text-xs font-semibold text-foreground">ACTION</span>
                  </div>
                  {taskId && (
                    <RecursionStateViewer taskId={taskId} iteration={recursion.iteration} />
                  )}
                </div>
                <p className="text-xs font-mono text-primary pl-5">
                  {recursion.action}
                </p>
              </div>
            )}

            {/* Tool Details */}
            {recursion.events.map((event, idx) => {
              if (event.type === 'tool_call') {
                const toolData = event.data as {
                  tool_calls?: Array<{ id: string; name: string; arguments: Record<string, unknown> | string }>;
                  tool_results?: Array<{ tool_call_id: string; name: string; result?: unknown; error?: string; success: boolean }>;
                } | undefined;

                return (
                  <div key={idx} className="bg-background/50 border border-border rounded p-2">
                    <div className="flex items-center gap-1.5 mb-2">
                      <Wrench className="w-3.5 h-3.5 text-orange-500" />
                      <span className="text-xs font-semibold text-foreground">TOOL EXECUTION</span>
                    </div>
                    <div className="space-y-3 pl-5">
                      {/* Tool Calls (Input Parameters) */}
                      {toolData?.tool_calls?.map((call, cidx) => (
                        <div key={`call-${cidx}`} className="space-y-1">
                          <div className="text-xs font-semibold text-foreground">
                            📥 Call: {call.name}
                          </div>
                          <div className="text-xs p-2 bg-muted/30 rounded font-mono text-muted-foreground border border-border/50">
                            <div className="text-[10px] text-muted-foreground/70 mb-1">Arguments:</div>
                            {typeof call.arguments === 'string'
                              ? call.arguments
                              : JSON.stringify(call.arguments, null, 2)}
                          </div>
                        </div>
                      ))}

                      {/* Tool Results (Output) */}
                      {toolData?.tool_results?.map((result, ridx) => (
                        <div key={`result-${ridx}`} className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-foreground">
                              📤 Result: {result.name}
                            </span>
                            {result.success ? (
                              <span className="text-xs px-1.5 py-0.5 rounded bg-success/10 text-success">
                                ✓
                              </span>
                            ) : (
                              <span className="text-xs px-1.5 py-0.5 rounded bg-danger/10 text-danger">
                                ✗
                              </span>
                            )}
                          </div>
                          {result.result !== undefined && result.result !== null && (
                            <div className="text-xs p-2 bg-muted/30 rounded font-mono text-muted-foreground border border-border/50 break-all">
                              {typeof result.result === 'string'
                                ? result.result
                                : JSON.stringify(result.result, null, 2)}
                            </div>
                          )}
                          {result.error && (
                            <div className="text-xs p-2 bg-danger/10 rounded text-danger border border-danger/30">
                              {result.error}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                );
              }

              if (event.type === 'plan_update') {
                const planData = event.data as {
                  plan?: PlanStepData[]
                } | undefined;

                return (
                  <div key={idx} className="bg-background/50 border border-border rounded p-2">
                    <div className="flex items-center gap-1.5 mb-2">
                      <Brain className="w-3.5 h-3.5 text-purple-500" />
                      <span className="text-xs font-semibold text-foreground">PLAN UPDATE</span>
                    </div>
                    {planData?.plan && planData.plan.length > 0 ? (
                      <div className="space-y-1 pl-5">
                        {planData.plan.map((step, sidx) => (
                          <div key={sidx} className="text-xs text-muted-foreground">
                            {sidx + 1}. {step.general_goal || 'Untitled step'}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-xs text-muted-foreground/50 pl-5 italic">
                        No plan data available
                      </div>
                    )}
                  </div>
                );
              }

              if (event.type === 'reflect') {
                const reflectData = event.data as { summary?: string } | undefined;

                return (
                  <div key={idx} className="bg-background/50 border border-border rounded p-2">
                    <div className="flex items-center gap-1.5 mb-2">
                      <Brain className="w-3.5 h-3.5 text-indigo-500" />
                      <span className="text-xs font-semibold text-foreground">REFLECT</span>
                    </div>
                    <div className="text-xs text-muted-foreground pl-5 leading-relaxed">
                      {reflectData?.summary || 'Reflecting on current state...'}
                    </div>
                  </div>
                );
              }

              if (event.type === 'error') {
                const errorData = event.data as { error?: string } | undefined;
                return (
                  <div key={idx} className="bg-danger/5 border border-danger/30 rounded p-2">
                    <div className="flex items-center gap-1.5 mb-1">
                      <XCircle className="w-3.5 h-3.5 text-danger" />
                      <span className="text-xs font-semibold text-danger">ERROR</span>
                    </div>
                    <div className="text-xs pl-5 text-danger/90">
                      {errorData?.error || 'Unknown error'}
                    </div>
                  </div>
                );
              }

              return null;
            })}

            {/* Error Log - Display if recursion has error_log */}
            {recursion.errorLog && (
              <div className="bg-danger/5 border border-danger/30 rounded p-2">
                <div className="flex items-center gap-1.5 mb-1">
                  <XCircle className="w-3.5 h-3.5 text-danger" />
                  <span className="text-xs font-semibold text-danger">ERROR LOG</span>
                </div>
                <div className="text-xs pl-5 text-danger/90 leading-relaxed">
                  {recursion.errorLog}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  const renderAttachments = (
    attachments: ChatAttachment[] | undefined,
    variant: 'message' | 'composer' = 'message'
  ) => {
    if (!attachments || attachments.length === 0) {
      return null;
    }

    if (variant === 'composer') {
      return (
        <div className="flex flex-wrap gap-2 px-3 pt-3">
          {attachments.map((attachment) => {
            const queueItem = attachment as PendingUploadItem;
            const baseControlClassName = 'absolute -top-1.5 z-10 flex h-5 w-5 items-center justify-center rounded-full bg-transparent transition-colors';
            const statusIcon = queueItem.status === 'uploading'
              ? (
                  <span
                    className={`${baseControlClassName} -left-1.5 text-muted-foreground`}
                    aria-label="Attachment is processing"
                  >
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  </span>
                )
              : queueItem.status === 'error'
                ? (
                    <TooltipProvider delayDuration={200}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span
                            className={`${baseControlClassName} -left-1.5 cursor-help text-destructive`}
                            aria-label="Attachment failed"
                            tabIndex={0}
                          >
                            <XCircle className="h-3.5 w-3.5" />
                          </span>
                        </TooltipTrigger>
                        <TooltipContent
                          side="top"
                          className="max-w-64 whitespace-pre-wrap break-words text-xs leading-relaxed"
                        >
                          {queueItem.errorMessage || 'Upload failed'}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  )
                : null;

            return (
              <div
                key={queueItem.clientId}
                className="group relative h-12 w-12"
              >
                <div
                  className={`relative flex h-full w-full overflow-hidden rounded-lg border bg-muted ${queueItem.status === 'error'
                    ? 'border-destructive/60 bg-destructive/[0.035] shadow-[0_0_0_1px_oklch(var(--destructive)/0.18)]'
                    : 'border-border/80'
                    }`}
                >
                  <AttachmentThumbnail
                    attachment={queueItem}
                    alt={queueItem.originalName}
                  />
                  <div className="absolute inset-x-0 bottom-0 bg-background/88 px-1.5 py-1 text-[9px] leading-tight">
                    <div className="truncate text-foreground">{queueItem.originalName}</div>
                  </div>
                </div>
                {statusIcon}
                <button
                  type="button"
                  onClick={() => {
                    void removePendingFile(queueItem.clientId);
                  }}
                  className={`${baseControlClassName} -right-1.5 text-destructive/80 opacity-0 pointer-events-none group-hover:pointer-events-auto group-hover:opacity-100 hover:text-destructive`}
                  title="Remove attachment"
                  aria-label={`Remove ${queueItem.originalName}`}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            );
          })}
        </div>
      );
    }

    return (
      <div className="mb-3 flex flex-wrap gap-2">
        {attachments.map((attachment) => (
          <div
            key={attachment.fileId}
            className="overflow-hidden rounded-xl border border-border bg-background/70"
          >
            <div className="h-28 w-28">
              <AttachmentThumbnail
                attachment={attachment}
                alt={attachment.originalName}
              />
            </div>
            <div className="max-w-28 border-t border-border/60 px-2 py-1 text-[10px] text-muted-foreground">
              <div className="truncate">{attachment.originalName}</div>
              {attachment.kind === 'document' && (
                <div className="truncate uppercase">
                  {attachment.extension}
                  {attachment.pageCount ? ` · ${attachment.pageCount}p` : ''}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    );
  };

  const isConversationEmpty = messages.length === 0;
  const normalizedAgentName = agentName?.trim() || 'ReAct Agent';

  return (
    <div className="flex h-full bg-background text-foreground overflow-hidden">
      {/* Sidebar - Session List */}
      <div
        className={`flex-shrink-0 border-r border-border flex flex-col bg-muted/30 transition-all duration-300 ease-in-out ${isSidebarCollapsed ? 'w-12' : 'w-64'
          }`}
      >
        {/* Sidebar Header */}
        <div className={`p-3 border-b border-border flex items-center ${isSidebarCollapsed ? 'justify-center' : 'justify-between'}`}>
          {!isSidebarCollapsed && (
            <Button
              onClick={() => void handleNewSession()}
              variant="outline"
              className="flex-1 justify-start gap-2"
              disabled={isLoadingSession || isStreaming}
            >
              <PlusCircle className="w-4 h-4" />
              New Session
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className={`h-8 w-8 ${isSidebarCollapsed ? '' : 'ml-2'}`}
            onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
            title={isSidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {isSidebarCollapsed ? (
              <PanelLeft className="w-4 h-4" />
            ) : (
              <PanelLeftClose className="w-4 h-4" />
            )}
          </Button>
        </div>

        {/* Session List */}
        {!isSidebarCollapsed && (
          <div className="flex-1 overflow-y-auto">
            <div className="p-2 space-y-1">
              {sessions.length === 0 ? (
                <div className="text-center text-muted-foreground text-sm py-4">
                  {isLoadingSession ? (
                    <div className="flex items-center justify-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Creating session...</span>
                    </div>
                  ) : (
                    <span>No sessions yet</span>
                  )}
                </div>
              ) : (
                sessions.map((session) => (
                  <div
                    key={session.session_id}
                    onClick={() => void handleSelectSession(session.session_id)}
                    className={`w-full text-left p-2 rounded-lg transition-colors group cursor-pointer ${session.session_id === currentSessionId
                      ? 'bg-primary/10 border border-primary/30'
                      : 'hover:bg-muted border border-transparent'
                      }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <MessageCircle className="w-3.5 h-3.5 flex-shrink-0 text-muted-foreground" />
                          <span className="text-sm font-medium truncate">
                            {session.subject || 'New conversation'}
                          </span>
                        </div>
                        <div className="text-xs text-muted-foreground mt-1 pl-5">
                          {formatTimestamp(session.updated_at)}
                        </div>
                        <div className="text-xs text-muted-foreground mt-0.5 pl-5">
                          {session.message_count} messages
                        </div>
                      </div>
                      <button
                        type="button"
                        className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 flex items-center justify-center rounded hover:bg-accent"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDeleteSession(session.session_id);
                        }}
                        title="Delete session"
                      >
                        <Trash2 className="w-3.5 h-3.5 text-muted-foreground hover:text-destructive" />
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* Collapsed state - show icon buttons */}
        {isSidebarCollapsed && (
          <div className="flex-1 flex flex-col items-center py-2 space-y-2">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={() => void handleNewSession()}
              disabled={isLoadingSession || isStreaming}
              title="New Session"
            >
              <PlusCircle className="w-4 h-4" />
            </Button>
          </div>
        )}
      </div>

      {/* Main Chat Area - single scrollable container for both messages and input */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div ref={scrollContainerRef} className="flex-1 overflow-y-auto" onScroll={handleScroll}>
          {/* Centered content container */}
          <div className="max-w-3xl mx-auto px-4 pt-4 pb-6">
            {isConversationEmpty ? (
              <div className="text-center text-muted-foreground mt-12 animate-fade-in min-h-[36vh] flex flex-col items-center justify-center">
                <div className="mb-4">
                  <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-muted flex items-center justify-center">
                    <MessageSquare className="w-8 h-8 text-muted-foreground" />
                  </div>
                  <p className="text-base font-medium text-foreground mb-2">
                    Chat with {normalizedAgentName}
                  </p>
                  <p className="text-sm opacity-70">
                    Ask questions or give tasks. I'll show you my reasoning process.
                  </p>
                </div >
              </div >
            ) : (
              messages.map((message) => (
                <div key={message.id} className="space-y-2 mb-6 last:mb-0">
                  {message.role === 'user' ? (
                    <div className="flex justify-end">
                      <div className="max-w-[85%] px-4 py-2.5 rounded-2xl shadow-sm bg-primary text-primary-foreground rounded-br-none">
                        <div className="font-semibold text-xs mb-1 opacity-90 tracking-wide uppercase">
                          YOU
                        </div>
                        <div className="text-[10px] mb-1 opacity-70 font-mono">
                          {formatTimestamp(message.timestamp)}
                        </div>
                        {message.attachments && message.attachments.length > 0 && (
                          <div className="rounded-xl bg-primary-foreground/10 p-2">
                            {renderAttachments(message.attachments)}
                          </div>
                        )}
                        {message.content && (
                          <div className="text-sm leading-relaxed whitespace-pre-wrap break-words">
                            {message.content}
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {/* Skill resolution */}
                      {message.skillSelection && (
                        <div className="border border-border rounded-md overflow-hidden bg-muted/20">
                          <div className="w-full flex items-center justify-between px-3 py-2">
                            <div className="flex items-center gap-2 flex-1 min-w-0">
                            {message.skillSelection.status === 'loading' ? (
                              <>
                                <Loader2 className="w-3.5 h-3.5 text-primary animate-spin flex-shrink-0" />
                                <span
                                  className="text-xs font-semibold truncate animate-thinking-wave"
                                  style={{
                                    background: 'linear-gradient(90deg, #9ca3af 0%, #e5e7eb 25%, #f3f4f6 50%, #e5e7eb 75%, #9ca3af 100%)',
                                    backgroundSize: '400% 100%',
                                    WebkitBackgroundClip: 'text',
                                    backgroundClip: 'text',
                                    WebkitTextFillColor: 'transparent',
                                  }}
                                >
                                  Matching Skills...
                                </span>
                              </>
                            ) : (
                              <>
                                <CheckCircle2 className="w-3.5 h-3.5 text-success flex-shrink-0" />
                                <span className="text-xs text-muted-foreground">
                                  Matched skills:{' '}
                                  {message.skillSelection.count > 0
                                    ? message.skillSelection.selectedSkills.join(', ')
                                    : 'None'}
                                </span>
                              </>
                            )}
                          </div>
                            {message.skillSelection.status === 'done' && (
                              <div className="flex items-center gap-2.5 flex-shrink-0">
                                {typeof message.skillSelection.durationMs === 'number' && (
                                  <span className="text-xs text-muted-foreground tabular-nums">
                                    {(message.skillSelection.durationMs / 1000).toFixed(1)}s
                                  </span>
                                )}
                                {message.skillSelection.tokens && (
                                  renderTokenUsage(
                                    message.skillSelection.tokens,
                                    `${formatTokenCount(message.skillSelection.tokens.total_tokens)} tokens`
                                  )
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Recursions */}
                      {message.recursions && message.recursions.length > 0 && (
                        <div className="space-y-2">
                          {message.recursions.filter((r) => r !== null).map((recursion) =>
                            renderRecursion(message.id, recursion, message.task_id)
                          )}
                        </div>
                      )}

                      {/* Final Answer / Question */}
                      {message.content && (
                        <div className="bg-background/50 border border-border rounded-lg p-3">
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-1.5">
                              {message.status === 'waiting_input' || (message.recursions?.length && message.recursions.filter((r) => r !== null)[message.recursions.filter((r) => r !== null).length - 1]?.action === 'CLARIFY') ? (
                                <>
                                  <MessageSquare className="w-3.5 h-3.5 text-info" />
                                  <span className="text-xs font-semibold text-foreground">QUESTION</span>
                                </>
                              ) : (
                                <>
                                  <MessageSquare className="w-3.5 h-3.5 text-success" />
                                  <span className="text-xs font-semibold text-foreground">FINAL ANSWER</span>
                                </>
                              )}
                            </div>
                            {/* REPLY button for QUESTION */}
                            {(message.status === 'waiting_input' || (message.recursions?.length && message.recursions.filter((r) => r !== null)[message.recursions.filter((r) => r !== null).length - 1]?.action === 'CLARIFY')) && message.task_id && (
                              <button
                                onClick={() => setReplyTaskId(message.task_id || null)}
                                className="text-xs text-muted-foreground hover:text-info transition-colors"
                              >
                                REPLY
                              </button>
                            )}
                          </div>
                          <div className="text-sm text-foreground pl-5 leading-relaxed">
                            {formatAnswerContent(message.content)}
                          </div>
                        </div>
                      )}

                      {/* Status */}
                      <div className="flex items-center gap-2 px-3">
                        {message.status === 'running' && (message.recursions?.length ?? 0) > 0 && (
                          <>
                            <Loader2 className="w-3.5 h-3.5 text-primary animate-spin" />
                            <span className="text-xs text-muted-foreground">Processing...</span>
                          </>
                        )}
                        {message.status === 'skill_resolving' && (
                          <>
                            <Loader2 className="w-3.5 h-3.5 text-primary animate-spin" />
                            <span
                              className="text-xs font-semibold truncate animate-thinking-wave"
                              style={{
                                background: 'linear-gradient(90deg, #9ca3af 0%, #e5e7eb 25%, #f3f4f6 50%, #e5e7eb 75%, #9ca3af 100%)',
                                backgroundSize: '400% 100%',
                                WebkitBackgroundClip: 'text',
                                backgroundClip: 'text',
                                WebkitTextFillColor: 'transparent',
                              }}
                            >
                              Matching Skills...
                            </span>
                          </>
                        )}
                        {message.status === 'completed' && (
                          <>
                            <CheckCircle2 className="w-3.5 h-3.5 text-success" />
                            <span className="text-xs text-muted-foreground">Completed</span>
                            {message.totalTokens && (
                              renderTokenUsage(
                                message.totalTokens,
                                `• Total: ${formatTokenCount(message.totalTokens.total_tokens)} tokens`,
                                "text-xs text-muted-foreground ml-2 tabular-nums whitespace-nowrap cursor-help underline decoration-dotted underline-offset-2"
                              )
                            )}
                          </>
                        )}
                        {message.status === 'error' && (
                          <>
                            <XCircle className="w-3.5 h-3.5 text-danger" />
                            <span className="text-xs text-danger">Error</span>
                          </>
                        )}
                        <span className="text-xs text-muted-foreground ml-auto">
                          {formatTimestamp(message.timestamp)}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              ))
            )
            }
            <div ref={messagesEndRef} className="h-4" />
          </div>
        </div>

        {/* Input Area */}
        <div
          className={`w-full max-w-3xl mx-auto px-4 pb-4 pt-3 transition-transform duration-100 ease-out bg-gradient-to-t from-background via-background to-transparent ${isConversationEmpty ? '-translate-y-[12vh] sm:-translate-y-[18vh]' : 'translate-y-0'
            }`}
        >
          {/* Error Banner */}
          {error && (
            <div className="px-4 py-2 mb-2 bg-danger/10 border border-danger/30 rounded-lg text-danger text-sm">
              {error}
            </div>
          )}

          {replyTaskId && (
            <div className="flex items-center justify-between text-xs mb-2 px-3 py-1.5 rounded-lg bg-muted/50 border border-border/50">
              <span className="text-foreground/70">↳ Replying to question</span>
              <button
                onClick={() => setReplyTaskId(null)}
                className="text-muted-foreground hover:text-foreground transition-colors"
                title="Cancel reply"
              >
                <XCircle className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
          <form onSubmit={handleSubmit} className="relative overflow-hidden rounded-2xl border bg-background shadow-lg focus-within:border-ring transition-all">
            <input
              ref={imageInputRef}
              type="file"
              accept="image/jpeg,image/jpg,image/png,image/webp"
              multiple
              className="hidden"
              onChange={handleFileInputChange}
            />
            <input
              ref={documentInputRef}
              type="file"
              accept=".pdf,.docx,.pptx,.xlsx,.md,.markdown"
              multiple
              className="hidden"
              onChange={handleDocumentInputChange}
            />
            {renderAttachments(pendingFiles, 'composer')}
            <Textarea
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              placeholder={replyTaskId ? "Reply to question..." : "Ask anything"}
              className="min-h-[60px] w-full resize-none border-0 p-4 shadow-none focus-visible:ring-0 focus-visible:shadow-none focus:shadow-none focus:outline-none"
              disabled={isStreaming}
            />
            <div className="flex items-center px-4 pb-3 justify-between">
              <DropdownMenu modal={false}>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full">
                    <Plus className="h-4 h-4" />
                    <span className="sr-only">Attach</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="z-[60]">
                  {supportsImageInput && (
                    <DropdownMenuItem onClick={() => imageInputRef.current?.click()}>
                      <ImagePlus className="mr-2 h-4 w-4" />
                      <span>Upload image</span>
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem onClick={() => documentInputRef.current?.click()}>
                    <Paperclip className="mr-2 h-4 w-4" />
                    <span>Upload file</span>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <div className="flex items-center gap-2">
                {hasUploadingFiles && (
                  <div className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Processing attachments...</span>
                  </div>
                )}
                {isStreaming ? (
                  <Button
                    type="button"
                    onClick={handleStop}
                    size="icon"
                    className="h-8 w-8 rounded-full bg-destructive/90 hover:bg-destructive text-destructive-foreground"
                    title="Stop execution"
                  >
                    <Square className="h-4 w-4" fill="currentColor" />
                  </Button>
                ) : (
                  <Button
                    type="submit"
                    disabled={!canSendMessage}
                    size="icon"
                    className="h-8 w-8 rounded-full"
                    title="Send message"
                  >
                    <ArrowUp className="h-4 w-4" />
                    <span className="sr-only">Send</span>
                  </Button>
                )}
              </div>
            </div>
          </form>
        </div>
      </div>
    </div >
  );
}

export default ReactChatInterface;
