import { useEffect, useRef } from "react";

import { MessageBubble } from "@/features/chat/components/MessageBubble";
import {
  fromCompletedTurn,
  fromMessageRead,
  type ChatMessageVM,
} from "@/features/chat/lib/message-view-model";
import { useChatStore, type ActiveTurn } from "@/features/chat/stores/chat-store";
import { GuardrailBanner } from "@/features/guardrail";
import { ScrollArea } from "@/shared/components/ui/scroll-area";
import type { components } from "@/shared/types/api";

type MessageRead = components["schemas"]["MessageRead"];

const PHASE_LABEL: Partial<Record<ActiveTurn["phase"], string>> = {
  connecting: "Connecting…",
  reconnecting: "Reconnecting…",
};

export function MessageList({
  history,
  activeTurn,
}: {
  history: MessageRead[];
  activeTurn: ActiveTurn | null;
}) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const completedTurns = useChatStore((s) => s.completedTurns);

  const persisted: ChatMessageVM[] = history.map(fromMessageRead);
  const sessionTurns: ChatMessageVM[] = completedTurns.map(fromCompletedTurn);

  useEffect(() => {
    viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight });
  }, [persisted.length, sessionTurns.length, activeTurn?.visibleText, activeTurn?.releasedToolResults.length]);

  const statusLabel = activeTurn ? PHASE_LABEL[activeTurn.phase] : undefined;

  return (
    <ScrollArea ref={viewportRef} className="flex-1" viewportClassName="px-4 py-4">
      <div role="log" aria-live="polite" aria-relevant="additions text" className="flex flex-col gap-4">
        {persisted.map((message) => (
          <MessageBubble key={message.id} {...message} />
        ))}
        {sessionTurns.map((message) => (
          <MessageBubble key={message.id} {...message} />
        ))}
        {activeTurn ? (
          <>
            <MessageBubble role="user" content={activeTurn.userText} />
            {activeTurn.guardrail ? <GuardrailBanner guardrail={activeTurn.guardrail} /> : null}
            {statusLabel ? (
              <p className="pl-11 text-xs text-muted-foreground">{statusLabel}</p>
            ) : (
              <MessageBubble
                role="assistant"
                content={activeTurn.visibleText}
                citations={activeTurn.citations}
                toolResults={activeTurn.releasedToolResults}
                pending
              />
            )}
          </>
        ) : null}
        {persisted.length === 0 && sessionTurns.length === 0 && !activeTurn ? (
          <p className="pt-8 text-center text-sm text-muted-foreground">
            Send a message to start the conversation.
          </p>
        ) : null}
      </div>
    </ScrollArea>
  );
}
