import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
} from "react";
import { toast } from "sonner";

import {
  deleteChatFile,
  getLLMById,
  type FileUploadSource,
  uploadChatFile,
} from "@/utils/api";
import {
  getChatThinkingModes,
  getDefaultChatThinkingMode,
  llmHasThinkingSelector,
  type ChatThinkingMode,
} from "@/utils/llmThinking";

import type { PendingUploadItem } from "../types";
import { getUniqueClipboardFiles, toChatAttachment } from "../utils/chatData";

/**
 * Owns attachment queue state so the chat container can stay focused on conversation flow.
 */
export function useChatUploads(primaryLlmId?: number) {
  const [pendingFiles, setPendingFiles] = useState<PendingUploadItem[]>([]);
  const [supportsImageInput, setSupportsImageInput] = useState<boolean>(false);
  const [supportsThinkingSelector, setSupportsThinkingSelector] =
    useState<boolean>(false);
  const [thinkingModes, setThinkingModes] = useState<ChatThinkingMode[]>([]);
  const [defaultThinkingMode, setDefaultThinkingMode] =
    useState<ChatThinkingMode>("fast");
  const imageInputRef = useRef<HTMLInputElement>(null);
  const documentInputRef = useRef<HTMLInputElement>(null);
  const uploadControllersRef = useRef<Map<string, AbortController>>(new Map());
  const pendingFilesRef = useRef<PendingUploadItem[]>([]);

  /**
   * Resolves primary model capabilities so unavailable upload paths never appear as affordances.
   */
  useEffect(() => {
    let isCancelled = false;

    if (!primaryLlmId) {
      setSupportsImageInput(false);
      setSupportsThinkingSelector(false);
      setThinkingModes([]);
      setDefaultThinkingMode("fast");
      return () => {
        isCancelled = true;
      };
    }

    setSupportsImageInput(false);
    setSupportsThinkingSelector(false);
    setThinkingModes([]);
    setDefaultThinkingMode("fast");

    const loadPrimaryLlm = async () => {
      try {
        const llm = await getLLMById(primaryLlmId);
        if (!isCancelled) {
          setSupportsImageInput(llm.image_input);
          setSupportsThinkingSelector(llmHasThinkingSelector(llm));
          setThinkingModes(getChatThinkingModes(llm));
          setDefaultThinkingMode(getDefaultChatThinkingMode(llm));
        }
      } catch (error) {
        if (!isCancelled) {
          console.error("Failed to load primary LLM capabilities:", error);
          setSupportsImageInput(false);
          setSupportsThinkingSelector(false);
          setThinkingModes([]);
          setDefaultThinkingMode("fast");
        }
      }
    };

    void loadPrimaryLlm();

    return () => {
      isCancelled = true;
    };
  }, [primaryLlmId]);

  useEffect(() => {
    pendingFilesRef.current = pendingFiles;
  }, [pendingFiles]);

  /**
   * Aborts inflight uploads and releases preview URLs when the chat surface unmounts.
   */
  useEffect(
    () => () => {
      uploadControllersRef.current.forEach((controller) => controller.abort());
      uploadControllersRef.current.clear();
      pendingFilesRef.current.forEach((item) => {
        if (item.previewUrl) {
          URL.revokeObjectURL(item.previewUrl);
        }
      });
    },
    [],
  );

  /**
   * Filters image uploads when the selected primary model cannot consume them.
   */
  const partitionFilesByImageCapability = useCallback(
    (files: File[]) => {
      const acceptedFiles: File[] = [];
      let blockedImageCount = 0;

      files.forEach((file) => {
        if (file.type.startsWith("image/") && !supportsImageInput) {
          blockedImageCount += 1;
          return;
        }
        acceptedFiles.push(file);
      });

      return { acceptedFiles, blockedImageCount };
    },
    [supportsImageInput],
  );

  /**
   * Starts upload work for newly queued files while preserving local previews.
   */
  const enqueueFiles = useCallback(
    (files: File[], source: FileUploadSource) => {
      files.forEach((file) => {
        const clientId = `${source}-${crypto.randomUUID()}`;
        const isPreviewableImage = file.type.startsWith("image/");
        const previewUrl = isPreviewableImage
          ? URL.createObjectURL(file)
          : undefined;
        const initialItem: PendingUploadItem = {
          clientId,
          fileId: "",
          kind: isPreviewableImage ? "image" : "document",
          originalName: file.name,
          mimeType: file.type || "application/octet-stream",
          format: "",
          extension: file.name.split(".").pop()?.toLowerCase() || "",
          width: 0,
          height: 0,
          sizeBytes: file.size,
          previewUrl,
          source,
          status: "uploading",
        };

        setPendingFiles((previous) => [...previous, initialItem]);

        const controller = new AbortController();
        uploadControllersRef.current.set(clientId, controller);

        const uploadFile = async () => {
          try {
            const uploadedFile = await uploadChatFile(
              file,
              source,
              controller.signal,
            );
            setPendingFiles((previous) =>
              previous.map((item) =>
                item.clientId === clientId
                  ? {
                      ...item,
                      ...toChatAttachment(uploadedFile, previewUrl),
                      status: "ready",
                    }
                  : item,
              ),
            );
          } catch (error) {
            if (controller.signal.aborted) {
              return;
            }

            const errorMessage =
              error instanceof Error ? error.message : "Failed to upload file";
            setPendingFiles((previous) =>
              previous.map((item) =>
                item.clientId === clientId
                  ? {
                      ...item,
                      status: "error",
                      errorMessage,
                    }
                  : item,
              ),
            );
          } finally {
            uploadControllersRef.current.delete(clientId);
          }
        };

        void uploadFile();
      });
    },
    [],
  );

  /**
   * Removes one queue item and also cleans up any temporary backend file created for it.
   */
  const removePendingFile = useCallback(
    async (clientId: string) => {
      const target = pendingFilesRef.current.find((item) => item.clientId === clientId);
      if (!target) {
        return;
      }

      const controller = uploadControllersRef.current.get(clientId);
      if (controller) {
        controller.abort();
        uploadControllersRef.current.delete(clientId);
      }

      setPendingFiles((previous) =>
        previous.filter((item) => item.clientId !== clientId),
      );

      if (target.previewUrl) {
        URL.revokeObjectURL(target.previewUrl);
      }

      if (target.status === "ready") {
        try {
          await deleteChatFile(target.fileId);
        } catch (error) {
          console.error("Failed to delete pending chat file:", error);
        }
      }
    },
    [],
  );

  /**
   * Clears the whole queue when the user changes chat context before sending attachments.
   */
  const clearPendingFiles = useCallback(async () => {
    const filesToClear = [...pendingFilesRef.current];

    await Promise.all(
      filesToClear.map(async (file) => {
        const controller = uploadControllersRef.current.get(file.clientId);
        if (controller) {
          controller.abort();
          uploadControllersRef.current.delete(file.clientId);
        }

        if (file.previewUrl) {
          URL.revokeObjectURL(file.previewUrl);
        }

        if (file.status === "ready") {
          try {
            await deleteChatFile(file.fileId);
          } catch (error) {
            console.error("Failed to delete queued chat file:", error);
          }
        }
      }),
    );

    setPendingFiles([]);
  }, []);

  /**
   * Drops sent attachments from the composer while preserving preview URLs in the sent message.
   */
  const discardReadyPendingFiles = useCallback(() => {
    setPendingFiles((previous) =>
      previous.filter((item) => item.status !== "ready"),
    );
  }, []);

  /**
   * Handles image picker selection from the composer menu.
   */
  const handleFileInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const selectedFiles = Array.from(event.target.files ?? []);
      const { acceptedFiles, blockedImageCount } =
        partitionFilesByImageCapability(selectedFiles);

      if (blockedImageCount > 0) {
        toast.error("The primary LLM does not accept image input.");
      }
      if (acceptedFiles.length > 0) {
        enqueueFiles(acceptedFiles, "local");
      }

      event.target.value = "";
    },
    [enqueueFiles, partitionFilesByImageCapability],
  );

  /**
   * Handles document picker selection from the composer menu.
   */
  const handleDocumentInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const selectedFiles = Array.from(event.target.files ?? []);
      if (selectedFiles.length > 0) {
        enqueueFiles(selectedFiles, "local");
      }

      event.target.value = "";
    },
    [enqueueFiles],
  );

  /**
   * Accepts pasted files from the clipboard and routes them through the same queue.
   */
  const handlePaste = useCallback(
    (event: ClipboardEvent<HTMLTextAreaElement>) => {
      const filesToUpload = getUniqueClipboardFiles(event.clipboardData);
      if (filesToUpload.length === 0) {
        return;
      }

      const { acceptedFiles, blockedImageCount } =
        partitionFilesByImageCapability(filesToUpload);
      if (acceptedFiles.length === 0) {
        if (blockedImageCount > 0) {
          toast.error("The primary LLM does not accept image input.");
        }
        return;
      }

      event.preventDefault();
      if (blockedImageCount > 0) {
        toast.error("The primary LLM does not accept image input.");
      }
      enqueueFiles(acceptedFiles, "clipboard");
    },
    [enqueueFiles, partitionFilesByImageCapability],
  );

  const readyPendingFiles = pendingFiles.filter(
    (item) => item.status === "ready" && item.fileId,
  );
  const hasUploadingFiles = pendingFiles.some(
    (item) => item.status === "uploading",
  );

  return {
    pendingFiles,
    readyPendingFiles,
    hasUploadingFiles,
    supportsImageInput,
    supportsThinkingSelector,
    thinkingModes,
    defaultThinkingMode,
    imageInputRef,
    documentInputRef,
    removePendingFile,
    clearPendingFiles,
    discardReadyPendingFiles,
    handleFileInputChange,
    handleDocumentInputChange,
    handlePaste,
  };
}
