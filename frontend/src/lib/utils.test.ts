import { describe, expect, it } from "vitest";
import { cn } from "./utils";

describe("cn", () => {
  it("keeps the last conflicting Tailwind utility", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
  });

  it("combines conditional classes without adding false values", () => {
    expect(cn("text-sm", false && "hidden")).toBe("text-sm");
  });
});
