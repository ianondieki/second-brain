import { createHmac } from "node:crypto";

// RFC 6238 TOTP (HMAC-SHA1, 30 s steps) computed in the test from the key shown on screen, as an authenticator
// app would. Test-only: the product never computes codes in the browser.

const BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

/** RFC 4648 base32 (no padding required, spaces and case ignored). */
export function base32Decode(input: string): Buffer {
  const clean = input.replace(/[\s=]/g, "").toUpperCase();
  let bits = 0;
  let value = 0;
  const bytes: number[] = [];
  for (const char of clean) {
    const index = BASE32.indexOf(char);
    if (index < 0) throw new Error(`not base32: ${char}`);
    value = (value << 5) | index;
    bits += 5;
    if (bits >= 8) {
      bytes.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return Buffer.from(bytes);
}

export interface TotpOptions {
  /** Unix time in milliseconds (default: now). */
  time?: number;
  /** Whole 30-second steps to move forward (1 = the next window). */
  offset?: number;
  digits?: number;
  step?: number;
}

export function totp(secret: string, { time = Date.now(), offset = 0, digits = 6, step = 30 }: TotpOptions = {}) {
  const counter = Math.floor(time / 1000 / step) + offset;
  const message = Buffer.alloc(8);
  message.writeBigUInt64BE(BigInt(counter));
  const mac = createHmac("sha1", base32Decode(secret)).update(message).digest();
  const at = mac[mac.length - 1] & 0x0f;
  const binary = ((mac[at] & 0x7f) << 24) | (mac[at + 1] << 16) | (mac[at + 2] << 8) | mac[at + 3];
  return String(binary % 10 ** digits).padStart(digits, "0");
}
