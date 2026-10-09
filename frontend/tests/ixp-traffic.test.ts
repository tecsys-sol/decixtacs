import { describe, expect, it } from "vitest";

import { formatRate } from "@/components/ixp/traffic";

describe("formatRate", () => {
  it("scales bits and packets per second", () => {
    expect(formatRate(0)).toBe("0 b/s");
    expect(formatRate(950)).toBe("950 b/s");
    expect(formatRate(1_234_000)).toBe("1.2 Mb/s");
    expect(formatRate(443_000_000_000)).toBe("443 Gb/s");
    expect(formatRate(2_500, "pkts")).toBe("2.5 kpps");
    expect(formatRate(null)).toBe("—");
  });
});
