import { StoneStack } from "@/features/chat/components/StoneStack";
import { cn } from "@/shared/lib/utils";

export interface ThinkingIndicatorProps {
  label?: string;
  reducedMotion?: boolean;
  className?: string;
}

export function ThinkingIndicator({ label = "Thinking", reducedMotion = false, className }: ThinkingIndicatorProps) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)} role="status">
      <StoneStack size="sm" animate={!reducedMotion} breathing={!reducedMotion} />
      <span className="text-xs text-muted-foreground">{label}</span>
    </span>
  );
}
