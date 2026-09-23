"use client";

import * as React from "react";

import { Input } from "@/components/ui/input";
import { useDebounce } from "@/hooks/use-debounce";
import { useOnChange } from "@/hooks/use-reset";

/** Text input that commits its value (debounced) to an external store such as URL state. */
export function TextFilter({
  value,
  onCommit,
  delay = 350,
  ...props
}: Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & {
  value: string;
  onCommit: (v: string) => void;
  delay?: number;
}) {
  const [local, setLocal] = React.useState(value);
  // external resets (e.g. "clear filters") win over the local draft
  useOnChange(value, (v) => setLocal(v));
  const debounced = useDebounce(local, delay);
  const commit = React.useRef(onCommit);
  React.useEffect(() => {
    commit.current = onCommit;
  });
  const external = React.useRef(value);
  React.useEffect(() => {
    external.current = value;
  }, [value]);

  React.useEffect(() => {
    if (debounced !== external.current) commit.current(debounced);
  }, [debounced]);

  return <Input value={local} onChange={(e) => setLocal(e.target.value)} {...props} />;
}
