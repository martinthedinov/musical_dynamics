// Thin wrapper that uses pako in the browser and node:zlib under Node — output is interoperable
// with Python's zlib (raw deflate is identical across all three).
import pako from "pako";

export function deflate(data) {
  return pako.deflate(data, { level: 9 });
}
export function inflate(data) {
  return pako.inflate(data);
}
