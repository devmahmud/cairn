import { useEffect } from "react";
import { useParams } from "react-router";

import { ChatInput } from "@/features/chat/components/ChatInput";
import { ConversationSidebar } from "@/features/chat/components/ConversationSidebar";
import { MessageList } from "@/features/chat/components/MessageList";
import { useInvalidateMessages, useMessages } from "@/features/chat/hooks/use-conversations";
import { useStreamingChat } from "@/features/chat/hooks/use-streaming-chat";
import { useChatStore } from "@/features/chat/stores/chat-store";
import { DebugPanel } from "@/features/debug";

function useReducedMotionSync(): void {
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    useChatStore.getState().setReducedMotion(query.matches);
    const listener = (event: MediaQueryListEvent): void => {
      useChatStore.getState().setReducedMotion(event.matches);
    };
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }, []);
}

export function ChatContainer() {
  const params = useParams<{ conversationId?: string }>();
  const conversationId = params.conversationId ?? null;

  const { data: history = [] } = useMessages(conversationId);
  const activeTurn = useChatStore((s) => s.activeTurn);
  const lastError = useChatStore((s) => s.lastError);
  const resetForConversation = useChatStore((s) => s.resetForConversation);
  const { sendMessage, stopStreaming } = useStreamingChat(conversationId);
  const invalidateMessages = useInvalidateMessages();

  useReducedMotionSync();

  useEffect(() => {
    resetForConversation();
    // Invalidate on cleanup (navigating away), not on message_end -- avoids racing the backend's post-stream persist commit.
    return () => {
      if (conversationId) void invalidateMessages(conversationId);
    };
  }, [conversationId, resetForConversation, invalidateMessages]);

  const isBusy = activeTurn !== null;

  return (
    <div className="flex h-dvh">
      <ConversationSidebar activeConversationId={conversationId} />
      <div className="flex min-w-0 flex-1 flex-col">
        {conversationId ? (
          <>
            <div className="border-b p-3">
              <DebugPanel
                trace={{
                  agent: activeTurn?.agent ?? null,
                  decision: activeTurn?.decision ?? null,
                  streamId: activeTurn?.streamId ?? null,
                  phase: activeTurn?.phase ?? "idle",
                }}
              />
            </div>
            <MessageList history={history} activeTurn={activeTurn} />
            {lastError ? (
              <p role="alert" className="px-4 pb-2 text-sm text-destructive">
                {lastError.message}
              </p>
            ) : null}
            <ChatInput disabled={isBusy} streaming={isBusy} onSend={sendMessage} onStop={stopStreaming} />
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
            Select a conversation or start a new one.
          </div>
        )}
      </div>
    </div>
  );
}
