import * as React from "react";
import { ScrollArea as ScrollAreaPrimitive } from "@base-ui/react/scroll-area";

import { cn } from "@/shared/lib/utils";

const ScrollArea = React.forwardRef<
  React.ComponentRef<typeof ScrollAreaPrimitive.Viewport>,
  React.ComponentProps<typeof ScrollAreaPrimitive.Root> & {
    viewportClassName?: string;
  }
>(({ className, viewportClassName, children, ...props }, ref) => (
  <ScrollAreaPrimitive.Root data-slot="scroll-area" className={cn("relative", className)} {...props}>
    <ScrollAreaPrimitive.Viewport
      ref={ref}
      data-slot="scroll-area-viewport"
      className={cn("size-full overscroll-contain focus:outline-none", viewportClassName)}
    >
      {children}
    </ScrollAreaPrimitive.Viewport>
    <ScrollAreaPrimitive.Scrollbar
      data-slot="scroll-area-scrollbar"
      orientation="vertical"
      className="m-1 flex w-1.5 justify-center rounded-full opacity-0 transition-opacity data-[hovering]:opacity-100 data-[scrolling]:opacity-100"
    >
      <ScrollAreaPrimitive.Thumb
        data-slot="scroll-area-thumb"
        className="w-full rounded-full bg-border"
      />
    </ScrollAreaPrimitive.Scrollbar>
  </ScrollAreaPrimitive.Root>
));
ScrollArea.displayName = "ScrollArea";

export { ScrollArea };
