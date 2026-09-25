/**
 * UUID generator that works in both secure (HTTPS) and non-secure (HTTP LAN)
 * contexts. crypto.randomUUID() is only available on HTTPS; this falls back
 * to a Math.random()-based RFC 4122 v4 UUID for plain-HTTP dev access.
 */
export function generateUUID(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}
