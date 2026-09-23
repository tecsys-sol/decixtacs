"use client";

import * as React from "react";

import { errorMessage } from "@/lib/api";

export type ToastVariant = "default" | "success" | "error" | "warning";

export interface ToastItem {
  id: string;
  title: string;
  description?: string;
  variant: ToastVariant;
  open: boolean;
  duration?: number;
}

type Listener = (toasts: ToastItem[]) => void;

const MAX_TOASTS = 4;
let toasts: ToastItem[] = [];
const listeners = new Set<Listener>();
let counter = 0;

function emit() {
  listeners.forEach((l) => l(toasts));
}

export function dismissToast(id: string) {
  toasts = toasts.map((t) => (t.id === id ? { ...t, open: false } : t));
  emit();
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id);
    emit();
  }, 300);
}

export function toast(input: { title: string; description?: string; variant?: ToastVariant; duration?: number }) {
  counter = (counter + 1) % Number.MAX_SAFE_INTEGER;
  const item: ToastItem = { id: `t${counter}`, variant: "default", open: true, ...input };
  toasts = [item, ...toasts].slice(0, MAX_TOASTS);
  emit();
  return item.id;
}

toast.success = (title: string, description?: string) => toast({ title, description, variant: "success" });
toast.error = (title: string, err?: unknown) =>
  toast({ title, description: err === undefined ? undefined : errorMessage(err), variant: "error", duration: 8000 });
toast.warning = (title: string, description?: string) => toast({ title, description, variant: "warning" });

export function useToasts(): ToastItem[] {
  const [state, setState] = React.useState<ToastItem[]>(toasts);
  React.useEffect(() => {
    listeners.add(setState);
    return () => {
      listeners.delete(setState);
    };
  }, []);
  return state;
}
