import { describe, expect, it } from "vitest";

import { chunkXttsEnglish } from "./coquiTextChunks";

describe("chunkXttsEnglish", () => {
  it("splits oversize blobs", () => {
    const bits = chunkXttsEnglish("a ".repeat(200), 80);
    expect(bits.every((b) => b.length <= 80)).toBe(true);
    expect(bits.join(" ").replace(/\s+/g, " ").trim()).toContain("a a");
  });

  it("keeps short text single", () => {
    expect(chunkXttsEnglish("Hello there.")).toEqual(["Hello there."]);
  });
});
