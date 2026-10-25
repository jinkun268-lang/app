// UUIDv7（小写、带连字符、36 字符），满足 01 篇标识符规则。
// 用于请求追踪 X-Request-Id 与幂等键 Idempotency-Key。
export function uuidv7(): string {
  const bytes = new Uint8Array(16)
  const ms = Date.now()
  let t = ms
  // 48 位毫秒时间戳（大端）
  for (let i = 5; i >= 0; i--) {
    bytes[i] = t & 0xff
    t = Math.floor(t / 256)
  }
  fillRandom(bytes.subarray(6))
  bytes[6] = (bytes[6] & 0x0f) | 0x70 // version 7
  bytes[8] = (bytes[8] & 0x3f) | 0x80 // variant 10xx
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function fillRandom(target: Uint8Array): void {
  const c = globalThis.crypto
  if (c && typeof c.getRandomValues === 'function') {
    c.getRandomValues(target)
    return
  }
  for (let i = 0; i < target.length; i++) {
    target[i] = Math.floor(Math.random() * 256)
  }
}
