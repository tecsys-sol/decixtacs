import * as React from "react";

import { cn } from "@/lib/utils";

export const Label = React.forwardRef<HTMLLabelElement, React.LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => (
    <label ref={ref} className={cn("text-[12.5px] font-semibold leading-none text-ink-2", className)} {...props} />
  ),
);
Label.displayName = "Label";
