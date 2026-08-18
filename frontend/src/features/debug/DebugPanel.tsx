import { Badge } from "@/shared/components/ui/badge";
import type { DecisionEvent } from "@/shared/types/sse-events";

export interface DebugTrace {
  agent: string | null;
  decision: DecisionEvent | null;
  streamId: string | null;
  phase: string;
}

export function DebugPanel({ trace }: { trace: DebugTrace }) {
  return (
    <details className="rounded-lg border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
      <summary className="cursor-pointer text-foreground/70 font-medium select-none">Trace</summary>
      <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 font-mono">
        <dt>phase</dt>
        <dd>{trace.phase}</dd>
        <dt>agent</dt>
        <dd>{trace.agent ?? "—"}</dd>
        <dt>intent</dt>
        <dd>
          {trace.decision ? (
            <span className="inline-flex items-center gap-1.5">
              {trace.decision.intent}
              <Badge variant="outline" className="font-mono">
                {trace.decision.confidence.toFixed(2)}
              </Badge>
            </span>
          ) : (
            "—"
          )}
        </dd>
        <dt>stream id</dt>
        <dd>{trace.streamId ?? "—"}</dd>
      </dl>
    </details>
  );
}
