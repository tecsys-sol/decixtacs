import * as React from "react";

import { cn } from "@/lib/utils";

export interface CheckboxProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type" | "onChange"> {
  onCheckedChange?: (checked: boolean) => void;
  label?: React.ReactNode;
}

export const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, onCheckedChange, label, id, ...props }, ref) => {
    const autoId = React.useId();
    const inputId = id ?? autoId;
    const box = (
      <input
        id={inputId}
        ref={ref}
        type="checkbox"
        className={cn("h-4 w-4 shrink-0 cursor-pointer rounded border-input accent-[hsl(var(--primary))]", className)}
        onChange={(e) => onCheckedChange?.(e.target.checked)}
        {...props}
      />
    );
    if (!label) return box;
    return (
      <label htmlFor={inputId} className="inline-flex cursor-pointer select-none items-center gap-2 text-sm">
        {box}
        <span>{label}</span>
      </label>
    );
  },
);
Checkbox.displayName = "Checkbox";
