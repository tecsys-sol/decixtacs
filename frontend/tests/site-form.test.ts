import { describe, expect, it } from "vitest";

import { slugify } from "@/components/devices/site-form-dialog";

describe("slugify (site form)", () => {
  it("derives API-safe slugs from site names", () => {
    expect(slugify("Frankfurt 1")).toBe("frankfurt-1");
    expect(slugify("  DE-CIX / Düsseldorf  ")).toBe("de-cix-dusseldorf");
    expect(slugify("---")).toBe("");
    expect(slugify("x".repeat(80))).toHaveLength(64);
  });
});
