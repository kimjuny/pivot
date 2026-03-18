import ChatContainer from "./ChatContainer";
import type { ChatPageProps } from "./types";

/**
 * Page-scoped entrypoint for the ReAct chat surface.
 */
function ChatPage(props: ChatPageProps) {
  return <ChatContainer {...props} />;
}

export default ChatPage;
