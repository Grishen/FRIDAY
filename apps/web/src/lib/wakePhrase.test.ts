import { describe, expect, it } from "vitest";

import { stripFridayWakePrefix } from "./wakePhrase";

describe("stripFridayWakePrefix", () => {
  it("drops relaxed wake cues", () => {
    expect(stripFridayWakePrefix("Friday, what's next")).toBe("what's next");
    expect(stripFridayWakePrefix("Friday: remind me")).toBe("remind me");
    expect(stripFridayWakePrefix("friday reminders today")).toBe("reminders today");
  });

  it("leaves unrelated speech alone", () => {
    expect(stripFridayWakePrefix("tell me jokes")).toBe("tell me jokes");
  });
});
