"use client";

import { useState } from "react";

/**
 * Run `onChange` (typically a batch of state resets) during render whenever `value` changes.
 * This is React's recommended alternative to resetting state in an effect
 * (https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes).
 */
export function useOnChange<T>(value: T, onChange: (value: T) => void) {
  const [prev, setPrev] = useState(value);
  if (!Object.is(prev, value)) {
    setPrev(value);
    onChange(value);
  }
}

/** Reset form state each time a dialog opens. */
export function useOnOpen(open: boolean, reset: () => void) {
  useOnChange(open, (o) => {
    if (o) reset();
  });
}

/**
 * Returns `value`, or the last non-null value it had. Lets dialogs keep rendering their content
 * while the close animation runs after the driving state was cleared.
 */
export function useLastDefined<T>(value: T | null | undefined): T | null | undefined {
  const [last, setLast] = useState(value);
  if (value !== null && value !== undefined && !Object.is(value, last)) setLast(value);
  return value ?? last;
}
