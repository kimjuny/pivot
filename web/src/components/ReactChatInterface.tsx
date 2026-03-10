import ChatPage from "@/pages/chat/ChatPage";
import type { ReactChatInterfaceProps } from "@/pages/chat/types";

/**
 * Backward-compatible entrypoint that now delegates to the page-scoped chat module.
 */
function ReactChatInterface(props: ReactChatInterfaceProps) {
  return <ChatPage {...props} />;
}

export default ReactChatInterface;
