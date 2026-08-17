// Cairn frontend — guardrail verdict banner (BLUEPRINT.md §4.1, §3.12, §8
// step 8). Renders a `GuardrailEvent` (`action`/`message`, §3.12) as-is --
// `action` badge colors stay on the conventional warning/destructive hues
// regardless of brand palette, the same way the shared `Badge` component's
// `success`/`warning`/`destructive` variants are pinned to those tokens.

import { AlertTriangle, ShieldAlert } from "lucide-react";

import { Badge } from "@/shared/components/ui/badge";
import { cn } from "@/shared/lib/utils";
import type { GuardrailEvent } from "@/shared/types/sse-events";

export function GuardrailBanner({ guardrail }: { guardrail: GuardrailEvent }) {
  const isRefusal = guardrail.action === "refuse";

  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-2 rounded-md border px-3 py-2 text-sm",
        isRefusal
          ? "border-destructive/30 bg-destructive/10 text-destructive"
          : "border-warning/30 bg-warning/10 text-warning-foreground",
      )}
    >
      {isRefusal ? (
        <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      ) : (
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      )}
      <div className="flex flex-col gap-1">
        <Badge variant={isRefusal ? "destructive" : "warning"} className="w-fit">
          {guardrail.action}
        </Badge>
        <span>{guardrail.message}</span>
      </div>
    </div>
  );
}
