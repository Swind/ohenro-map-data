import { describe, expect, it, vi } from "vitest";
import { uuidv4 } from "./uuid";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("uuidv4", () => {
  it("delegates to native crypto.randomUUID when available", () => {
    const native = vi.fn(() => "native-uuid");
    const original = crypto.randomUUID;
    // @ts-expect-error replacing native for the delegation test
    crypto.randomUUID = native;
    try {
      expect(uuidv4()).toBe("native-uuid");
      expect(native).toHaveBeenCalledTimes(1);
    } finally {
      crypto.randomUUID = original;
    }
  });

  it("falls back to getRandomValues with canonical RFC 4122 v4 shape", () => {
    const original = crypto.randomUUID;
    // @ts-expect-error removing native for the fallback test
    crypto.randomUUID = undefined;
    const getRandomValues = vi.fn((array: Uint8Array) => {
      // Native getRandomValues fills the passed buffer in place. 16
      // deterministic bytes -> version/variant bits are set by uuidv4.
      for (let i = 0; i < 16; i++) array[i] = i;
      return array;
    });
    const originalGetRandomValues = crypto.getRandomValues;
    // @ts-expect-error replacing getRandomValues for the deterministic test
    crypto.getRandomValues = getRandomValues;

    try {
      const uuid = uuidv4();
      expect(uuid).toMatch(UUID_RE);
      // Deterministic input (0..15) -> fully deterministic output.
      expect(uuid).toBe("00010203-0405-4607-8809-0a0b0c0d0e0f");
      expect(getRandomValues).toHaveBeenCalledTimes(1);
    } finally {
      crypto.randomUUID = original;
      crypto.getRandomValues = originalGetRandomValues;
    }
  });
});