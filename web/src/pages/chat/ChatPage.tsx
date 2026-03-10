import ChatContainer from "./ChatContainer";
import type { ReactChatInterfaceProps } from "./types";

/**
 * Page-scoped entrypoint for the ReAct chat surface.
 */
function ChatPage(props: ReactChatInterfaceProps) {
  return <ChatContainer {...props} />;
}

export default ChatPage;
