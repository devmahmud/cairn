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
    <details className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
      <summary className="cursor-pointer select-none font-medium">Trace</summary>
      <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1">
        <dt>phase</dt>
        <dd>{trace.phase}</dd>
        <dt>agent</dt>
        <dd>{trace.agent ?? "—"}</dd>
        <dt>intent</dt>
        <dd>
          {trace.decision ? (
            <span className="inline-flex items-center gap-1.5">
              {trace.decision.intent}
              <Badge variant="outline">{trace.decision.confidence.toFixed(2)}</Badge>
            </span>
          ) : (
            "—"
          )}
        </dd>
        <dt>stream id</dt>
        <dd className="font-mono">{trace.streamId ?? "—"}</dd>
      </dl>
    </details>
  );
}
