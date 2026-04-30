import { describe, expect, it } from "vitest";
import { normalizeLocalApiOrigin } from "./config";

describe("normalizeLocalApiOrigin", () => {
  it("rewrites localhost to 127.0.0.1 for consistent IPv4 connects", () => {
    expect(normalizeLocalApiOrigin("http://localhost:8000")).toBe("http://127.0.0.1:8000");
  });

  it("returns fallback when hostname cannot be parsed", () => {
    expect(normalizeLocalApiOrigin("^not-a-url")).toBe("http://127.0.0.1:8000");
  });
});
