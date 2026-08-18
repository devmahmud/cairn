import { useEffect, useState } from "react";
import { Menu } from "lucide-react";
import { useParams } from "react-router";

import { ChatInput } from "@/features/chat/components/ChatInput";
import { ConversationSidebar } from "@/features/chat/components/ConversationSidebar";
import { MessageList } from "@/features/chat/components/MessageList";
import { StoneStack } from "@/features/chat/components/StoneStack";
import { useInvalidateMessages, useMessages } from "@/features/chat/hooks/use-conversations";
import { useStreamingChat } from "@/features/chat/hooks/use-streaming-chat";
import { useChatStore } from "@/features/chat/stores/chat-store";
import { DebugPanel } from "@/features/debug";
import { Button } from "@/shared/components/ui/button";
import { Wordmark } from "@/shared/components/Wordmark";

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
  const reducedMotion = useChatStore((s) => s.reducedMotion);
  const resetForConversation = useChatStore((s) => s.resetForConversation);
  const { sendMessage, stopStreaming } = useStreamingChat(conversationId);
  const invalidateMessages = useInvalidateMessages();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [renderedConversationId, setRenderedConversationId] = useState(conversationId);

  useReducedMotionSync();

  if (conversationId !== renderedConversationId) {
    setRenderedConversationId(conversationId);
    setSidebarOpen(false);
  }

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
      <ConversationSidebar
        activeConversationId={conversationId}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b p-3 sm:hidden">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open conversations"
          >
            <Menu className="size-5" />
          </Button>
          <Wordmark />
        </div>
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
          <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
            <StoneStack size="lg" animate={!reducedMotion} />
            <div className="flex flex-col gap-1">
              <p className="font-display text-lg font-semibold text-foreground">Choose your way</p>
              <p className="text-sm text-muted-foreground">Select a conversation, or start a new one.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
