"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { artForPath, HeaderIllustration, type HeaderArt } from "@/components/illustrations";
import { useDesign } from "@/hooks/use-design";
import { cn } from "@/lib/utils";

/** Title with one word set in the italic brand accent (Meridian's editorial headline style). */
function AccentTitle({ title, accent }: { title: string; accent: string }) {
  const i = title.toLowerCase().indexOf(accent.toLowerCase());
  if (i < 0) return <>{title}</>;
  return (
    <>
      {title.slice(0, i)}
      <em className="font-display italic text-primary">{title.slice(i, i + accent.length)}</em>
      {title.slice(i + accent.length)}
    </>
  );
}

/**
 * Page header. Aurora: breadcrumb trail, then a card holding a line-art illustration (picked from
 * the route unless overridden), the title, a description and the page actions. Meridian: an
 * editorial header straight on the page — large serif title (optionally with an italic accent
 * word), description, the Meridian motif for the route and pill actions.
 */
export function PageHeader({
  title,
  description,
  actions,
  breadcrumbs,
  art,
  illustration,
  children,
  className,
  accent,
}: {
  title: React.ReactNode;
  /** Meridian: a word of a string title to set in italic brand colour */
  accent?: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumbs?: { label: string; href?: string }[];
  /** header illustration; defaults to the one for the current route, `false` hides it */
  art?: HeaderArt | false;
  /** custom illustration node (overrides `art`) */
  illustration?: React.ReactNode;
  /** extra content below the description (badges, meta) */
  children?: React.ReactNode;
  className?: string;
}) {
  const pathname = usePathname() ?? "";
  const docTitle = typeof title === "string" ? title : breadcrumbs?.length ? breadcrumbs[breadcrumbs.length - 1].label : null;
  React.useEffect(() => {
    if (docTitle) document.title = `${docTitle} · NetworkOps Manager`;
  }, [docTitle]);
  const chosen = art === false ? null : (art ?? artForPath(pathname));
  const { design } = useDesign();

  if (design === "meridian") {
    return (
      <div className={cn("mb-6 flex flex-col gap-2", className)}>
        {breadcrumbs?.length ? (
          <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
            {breadcrumbs.map((b, i) => (
              <span key={`${b.label}-${i}`} className="flex items-center gap-2">
                {b.href ? (
                  <Link href={b.href} className="font-semibold text-primary hover:text-primary-hover hover:underline">
                    {i === 0 ? "← " : ""}
                    {b.label}
                  </Link>
                ) : (
                  <span className="font-semibold text-ink-3" aria-current="page">
                    {b.label}
                  </span>
                )}
                {i < breadcrumbs.length - 1 ? <span aria-hidden>/</span> : null}
              </span>
            ))}
          </nav>
        ) : null}
        <section className="rise flex flex-col gap-4 sm:flex-row sm:items-end sm:gap-6">
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <h1 className="min-w-0 break-words font-display text-[32px] font-semibold leading-[1.08] tracking-[-0.025em] sm:text-[42px]">
              {typeof title === "string" && accent ? <AccentTitle title={title} accent={accent} /> : title}
            </h1>
            {description ? <div className="max-w-[760px] text-[15px] leading-relaxed text-ink-3">{description}</div> : null}
            {children}
          </div>
          {illustration ?? (chosen ? <HeaderIllustration art={chosen} className="hidden h-[84px] w-[150px] shrink-0 lg:block" /> : null)}
          {actions ? <div className="flex flex-wrap items-center gap-2.5 sm:justify-end">{actions}</div> : null}
        </section>
      </div>
    );
  }

  return (
    <div className={cn("mb-5 flex flex-col gap-3", className)}>
      {breadcrumbs?.length ? (
        <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
          {breadcrumbs.map((b, i) => (
            <span key={`${b.label}-${i}`} className="flex items-center gap-2">
              {b.href ? (
                <Link href={b.href} className="font-semibold text-accent-foreground hover:text-primary-hover hover:underline">
                  {b.label}
                </Link>
              ) : (
                <span className="font-bold text-foreground" aria-current="page">
                  {b.label}
                </span>
              )}
              {i < breadcrumbs.length - 1 ? <span aria-hidden>/</span> : null}
            </span>
          ))}
        </nav>
      ) : null}
      <section className="rise relative flex flex-col gap-4 overflow-hidden rounded-2xl border bg-card px-5 py-5 sm:flex-row sm:items-center sm:gap-6 sm:px-6">
        {illustration ?? (chosen ? <HeaderIllustration art={chosen} className="hidden h-[84px] w-[150px] shrink-0 md:block" /> : null)}
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <h1 className="min-w-0 break-words font-display text-2xl font-bold tracking-[-0.02em] sm:text-[26px]">{title}</h1>
          {description ? <div className="text-[13.5px] leading-relaxed text-ink-3">{description}</div> : null}
          {children}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2.5 sm:justify-end">{actions}</div> : null}
      </section>
    </div>
  );
}
