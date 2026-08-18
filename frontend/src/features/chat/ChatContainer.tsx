// Cairn frontend — the chat feature's top-level view (BLUEPRINT.md §4.1,
// §4.2, §8 step 8). Wires the streaming hook, the feature store, and
// TanStack Query's persisted history together; everything else in this
// feature is a presentational consumer of what this component assembles.

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
    // Cleanup runs with the *previous* render's `conversationId`, right
    // before this effect re-runs for a new one (or on unmount) -- i.e.
    // exactly when we're navigating away from a conversation, and its
    // `useMessages` query observer has already gone inactive (§4.3:
    // completed turns before now live only in `completedTurns`, a
    // client-only store `resetForConversation` above just wiped -- see
    // `chat-store.ts`'s module docstring). Marking the REST cache stale
    // here, not on every `message_end`, avoids racing `_persist_reply`
    // (which commits *after* the SSE stream already finished) and avoids
    // an unnecessary refetch while still viewing the conversation, since
    // `completedTurns` already renders the just-finished turn locally.
    // Invalidating an inactive query only marks it stale (no immediate
    // network call); the next mount that observes it will refetch, so a
    // conversation revisited within `gcTime` shows the full transcript
    // instead of the pre-turn snapshot the `staleTime: Infinity` cache
    // would otherwise still be serving.
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
