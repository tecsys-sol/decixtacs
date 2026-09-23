import Link from "next/link";
import { Compass } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="rounded-2xl border bg-card px-6 py-4">
        <EmptyState
          icon={Compass}
          art="search"
          title="Page not found"
          description="The page you are looking for does not exist or has moved."
          action={
            <Link href="/dashboard" className="inline-flex h-10 items-center rounded-md bg-primary px-4 text-[13px] font-bold text-primary-foreground shadow-brand hover:bg-primary-hover">
              Go to dashboard
            </Link>
          }
        />
      </div>
    </div>
  );
}
