import { cn } from "@/shared/lib/utils";

export interface StoneStackProps {
  size?: "sm" | "lg";
  animate?: boolean;
  breathing?: boolean;
  className?: string;
}

const SIZES = {
  sm: [
    { w: 15, h: 7 },
    { w: 11, h: 6 },
    { w: 7, h: 5.5 },
  ],
  lg: [
    { w: 52, h: 22 },
    { w: 38, h: 18 },
    { w: 20, h: 15 },
  ],
} as const;

const TONE = ["bg-muted-foreground/30", "bg-lichen/70", "bg-primary"];

export function StoneStack({ size = "sm", animate = true, breathing = false, className }: StoneStackProps) {
  const stones = SIZES[size];
  const gap = size === "sm" ? -2 : -5;

  return (
    <span className={cn("cairn-stack", className)} aria-hidden="true">
      {stones.map((stone, i) => (
        <span
          key={i}
          data-stone={i + 1}
          className={cn(
            "cairn-stone",
            TONE[i],
            animate && "cairn-stone-enter",
            breathing && i === stones.length - 1 && "cairn-stone-breathe",
          )}
          style={{
            width: stone.w,
            height: stone.h,
            marginTop: i === 0 ? 0 : gap,
          }}
        />
      ))}
    </span>
  );
}
