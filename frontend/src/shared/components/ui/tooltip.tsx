import * as React from "react";
import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip";

import { cn } from "@/shared/lib/utils";

const TooltipProvider = TooltipPrimitive.Provider;

export interface TooltipProps {
  content: React.ReactNode;
  children: React.ReactElement;
  className?: string;
}

function Tooltip({ content, children, className }: TooltipProps) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger render={children} className={className} />
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Positioner sideOffset={6}>
          <TooltipPrimitive.Popup
            className={cn(
              "z-50 max-w-xs rounded-md border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-md",
            )}
          >
            {content}
          </TooltipPrimitive.Popup>
        </TooltipPrimitive.Positioner>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export { Tooltip, TooltipProvider };
