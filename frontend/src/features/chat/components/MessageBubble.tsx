import { Bot, User } from "lucide-react";

import { ToolArtifactCard } from "@/features/tool-artifact";
import { Avatar, AvatarFallback } from "@/shared/components/ui/avatar";
import { Tooltip } from "@/shared/components/ui/tooltip";
import { cn } from "@/shared/lib/utils";
import type { Citation, ToolResultEvent } from "@/shared/types/sse-events";

function CitationChip({ citation }: { citation: Citation }) {
  return (
    <Tooltip
      content={
        <span>
          {citation.source ?? citation.documentId}
          {" · score "}
          {citation.score.toFixed(2)}
        </span>
      }
    >
      <span className="inline-flex size-5 items-center justify-center rounded-full border bg-muted text-[10px] font-medium hover:bg-accent">
        {citation.index}
      </span>
    </Tooltip>
  );
}

export interface MessageBubbleProps {
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  citations?: Citation[];
  toolResults?: ToolResultEvent[];
  pending?: boolean;
}

export function MessageBubble({ role, content, citations = [], toolResults = [], pending }: MessageBubbleProps) {
  const isUser = role === "user";

  return (
    <div
      className={cn("flex items-start gap-3", isUser && "flex-row-reverse")}
      data-testid={`chat-message-${role}`}
      data-pending={pending ? "true" : undefined}
    >
      <Avatar>
        <AvatarFallback>{isUser ? <User className="size-4" /> : <Bot className="size-4" />}</AvatarFallback>
      </Avatar>
      <div className={cn("flex max-w-[75%] flex-col gap-2", isUser && "items-end")}>
        <div
          className={cn(
            "rounded-lg px-3 py-2 text-sm whitespace-pre-wrap",
            isUser ? "bg-primary text-primary-foreground" : "bg-muted text-foreground",
          )}
        >
          {content}
          {pending ? (
            <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-current align-text-bottom" />
          ) : null}
        </div>
        {toolResults.map((toolResult, i) => (
          <ToolArtifactCard key={`${toolResult.toolName}-${i}`} toolResult={toolResult} />
        ))}
        {citations.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {citations.map((citation) => (
              <CitationChip key={citation.index} citation={citation} />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
