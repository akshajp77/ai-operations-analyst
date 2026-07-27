"use client"

import * as React from "react"
import { Progress as ProgressPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

function Progress({
  className,
  value,
  ...props
}: React.ComponentProps<typeof ProgressPrimitive.Root>) {
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      className={cn(
        "relative h-2 w-full overflow-hidden rounded-full bg-primary/20",
        className
      )}
      // DIVERGES FROM UPSTREAM (expect a hit from `npx shadcn diff`).
      // Upstream destructures `value` for the indicator transform and never
      // forwards it, so Radix falls back to its indeterminate state: the bar
      // animates for sighted users while a screen reader is told only that
      // something is in progress, with no aria-valuenow and no completion.
      // For a component whose entire job is reporting progress, that is a
      // defect rather than a style preference.
      value={value}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        className="h-full w-full flex-1 bg-primary transition-all"
        style={{ transform: `translateX(-${100 - (value || 0)}%)` }}
      />
    </ProgressPrimitive.Root>
  )
}

export { Progress }
