import { cn } from "@/shared/lib/utils";

export interface WordmarkProps {
  size?: "sm" | "lg";
  className?: string;
}

export function Wordmark({ size = "sm", className }: WordmarkProps) {
  const iconSize = size === "sm" ? 20 : 28;

  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <svg
        width={iconSize}
        height={iconSize}
        viewBox="0 0 48 48"
        fill="none"
        aria-hidden="true"
        className="shrink-0"
      >
        <ellipse cx="24" cy="34" rx="15" ry="6.5" className="fill-muted-foreground/70" transform="rotate(-3 24 34)" />
        <ellipse cx="24" cy="23" rx="11" ry="5.5" className="fill-lichen/80" transform="rotate(4 24 23)" />
        <ellipse cx="23" cy="13" rx="6.5" ry="5" className="fill-primary" transform="rotate(-2 23 13)" />
      </svg>
      <span
        className={cn(
          "font-display font-semibold tracking-tight text-foreground",
          size === "sm" ? "text-base" : "text-xl",
        )}
      >
        Cairn
      </span>
    </span>
  );
}
