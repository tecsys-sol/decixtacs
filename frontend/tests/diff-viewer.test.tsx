import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { intraline, toInlineRows } from "@/components/diff/diff-utils";
import { DiffViewer } from "@/components/diff/diff-viewer";
import type { DiffOut } from "@/lib/types";

const diff: DiffOut = {
  old_rev: "1111111111aaaaaaaaaa",
  new_rev: "2222222222bbbbbbbbbb",
  unified: [
    "--- edge01@1111111111",
    "+++ edge01@2222222222",
    "@@ -1,4 +1,4 @@",
    " set system host-name edge01",
    "-set protocols bgp group IX neighbor 192.0.2.1 peer-as 64500",
    "+set protocols bgp group IX neighbor 192.0.2.1 peer-as 64501",
    "-set snmp community public",
    "+set system ntp server 192.0.2.123",
    "",
  ].join("\n"),
  side_by_side: [
    { type: "equal", left_no: 1, left: "set system host-name edge01", right_no: 1, right: "set system host-name edge01" },
    {
      type: "modified",
      left_no: 2,
      left: "set protocols bgp group IX neighbor 192.0.2.1 peer-as 64500",
      right_no: 2,
      right: "set protocols bgp group IX neighbor 192.0.2.1 peer-as 64501",
    },
    { type: "removed", left_no: 3, left: "set snmp community public", right_no: null, right: null },
    { type: "added", left_no: null, left: null, right_no: 3, right: "set system ntp server 192.0.2.123" },
    { type: "skip", count: 42 },
    { type: "equal", left_no: 46, left: "commit", right_no: 46, right: "commit" },
  ],
  added: 2,
  removed: 2,
  risk: {
    score: 40,
    level: "high",
    findings: ["BGP neighbour removed: set protocols bgp group IX neighbor 192.0.2.1 peer-as 64500"],
    summary: "2 line(s) added, 2 removed; most changes in protocols (2)",
  },
};

describe("diff utils", () => {
  it("flattens modified rows into an old/new pair for the inline view", () => {
    const rows = toInlineRows(diff.side_by_side);
    expect(rows.map((r) => r.type)).toEqual(["equal", "modified-old", "modified-new", "removed", "added", "skip", "equal"]);
    expect(rows[1]).toMatchObject({ oldNo: 2, newNo: null });
    expect(rows[2]).toMatchObject({ oldNo: null, newNo: 2 });
    expect(rows[5].count).toBe(42);
  });

  it("isolates the changed part of a modified line", () => {
    const { a, b } = intraline("peer-as 64500", "peer-as 64501");
    expect(a).toEqual(["peer-as 6450", "0", ""]);
    expect(b).toEqual(["peer-as 6450", "1", ""]);
  });
});

describe("<DiffViewer />", () => {
  it("renders side-by-side rows with type markers, stats and the risk report", () => {
    render(<DiffViewer diff={diff} mode="split" />);

    const table = screen.getByTestId("diff-split");
    const rows = within(table).getAllByRole("row");
    expect(rows.map((r) => r.getAttribute("data-type"))).toEqual(["equal", "modified", "removed", "added", "skip", "equal"]);

    // colours: added = green, removed = red, modified = amber
    const added = rows[3].querySelectorAll("td")[3];
    expect(added.className).toContain("bg-diff-add-bg");
    const removed = rows[2].querySelectorAll("td")[1];
    expect(removed.className).toContain("bg-diff-del-bg");
    const modified = rows[1].querySelectorAll("td")[1];
    expect(modified.className).toContain("bg-diff-mod-bg");
    // intraline emphasis on the changed character
    expect(within(rows[1]).getAllByText("1", { selector: "mark" })).toHaveLength(1);

    expect(screen.getByText(/42 unchanged lines/)).toBeInTheDocument();
    expect(screen.getByTestId("diff-added")).toHaveTextContent("+2");
    expect(screen.getByTestId("diff-removed")).toHaveTextContent("−2");

    const risk = screen.getByTestId("risk-panel");
    expect(risk).toHaveTextContent("Risk 40 · high");
    expect(risk).toHaveTextContent("BGP neighbour removed");
    expect(risk).toHaveTextContent(diff.risk.summary);
  });

  it("switches between inline and unified modes", () => {
    render(<DiffViewer diff={diff} />);

    fireEvent.click(screen.getByRole("radio", { name: /inline/i }));
    const inline = screen.getByTestId("diff-inline");
    const types = within(inline)
      .getAllByRole("row")
      .map((r) => r.getAttribute("data-type"));
    expect(types).toEqual(["equal", "modified-old", "modified-new", "removed", "added", "skip", "equal"]);

    fireEvent.click(screen.getByRole("radio", { name: /unified/i }));
    const unified = screen.getByTestId("diff-unified");
    const lines = Array.from(unified.children).map((c) => c.getAttribute("data-type"));
    expect(lines).toEqual(["meta", "meta", "hunk", "context", "removed", "added", "removed", "added"]);
    expect(screen.getByRole("radio", { name: /unified/i })).toHaveAttribute("aria-checked", "true");
    // the chosen mode is remembered for the next diff
    expect(window.localStorage.getItem("nom.diff.mode")).toBe("unified");
  });

  it("shows an explicit message for identical revisions", () => {
    render(<DiffViewer diff={{ ...diff, added: 0, removed: 0, side_by_side: [] }} showRisk={false} />);
    expect(screen.getByText(/identical/)).toBeInTheDocument();
    expect(screen.queryByTestId("risk-panel")).not.toBeInTheDocument();
  });
});
