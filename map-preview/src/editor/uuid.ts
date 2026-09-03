/**
 * Shared UUID v4 helper.
 *
 * Uses the native `crypto.randomUUID()` when available (secure contexts /
 * modern browsers) and falls back to `crypto.getRandomValues()` otherwise.
 * The fallback still emits RFC 4122 version 4 / variant 1 bits and canonical
 * lowercase hyphenated text, so callers always get a well-formed UUID v4.
 */

const HEX = "0123456789abcdef";

function randomBytes(count: number): Uint8Array {
  const bytes = new Uint8Array(count);
  crypto.getRandomValues(bytes);
  return bytes;
}

/**
 * Formats a 16-byte array as canonical lowercase RFC 4122 UUID text.
 * Byte layout mirrors `crypto.randomUUID()` output (mixed-endian fields).
 */
function format(bytes: Uint8Array): string {
  const parts = [
    hex(bytes[0]) + hex(bytes[1]) + hex(bytes[2]) + hex(bytes[3]),
    hex(bytes[4]) + hex(bytes[5]),
    hex(bytes[6]) + hex(bytes[7]),
    hex(bytes[8]) + hex(bytes[9]),
    hex(bytes[10]) + hex(bytes[11]) + hex(bytes[12]) + hex(bytes[13]) + hex(bytes[14]) + hex(bytes[15]),
  ];
  return parts.join("-");
}

function hex(byte: number): string {
  return HEX[byte >> 4] + HEX[byte & 0x0f];
}

/**
 * Returns a new RFC 4122 version 4 UUID as lowercase hyphenated text.
 */
export function uuidv4(): string {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  const bytes = randomBytes(16);
  // Version 4 (RFC 4122): bits 48-51 = 0b0100.
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  // Variant 1 (RFC 4122): bits 64-65 = 0b10.
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  return format(bytes);
}