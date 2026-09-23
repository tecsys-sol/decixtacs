import { render, screen } from "@testing-library/react";
import { Server } from "lucide-react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "@/components/common/empty-state";

describe("<EmptyState />", () => {
  it("renders the illustration, title, description and action", () => {
    render(<EmptyState icon={Server} title="No devices yet" description="Add a device to start backing it up." action={<button type="button">Add device</button>} />);
    const root = screen.getByTestId("empty-state");
    expect(screen.getByText("No devices yet")).toBeInTheDocument();
    expect(screen.getByText(/Add a device/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add device" })).toBeInTheDocument();
    // decorative line-art scene with animated strokes, hidden from assistive tech
    const svg = root.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg!.closest("[aria-hidden]")).not.toBeNull();
    expect(root.querySelector(".flow")).not.toBeNull();
    expect(root.querySelector(".floaty")).not.toBeNull();
  });

  it("uses the success scene and compact spacing when asked", () => {
    render(<EmptyState title="All rules passed" art="success" compact />);
    const root = screen.getByTestId("empty-state");
    expect(root.className).toContain("py-4");
    expect(root.querySelector(".bg-success-soft")).not.toBeNull();
  });
});
