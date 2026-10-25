// 最小 ZIP 构建器（stored 方式，无压缩），用于 mock 导出夹具生成确定性的小型 ZIP。
// 仅开发态使用。
export interface ZipEntry {
  name: string
  bytes: Uint8Array
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256)
  for (let n = 0; n < 256; n++) {
    let c = n
    for (let k = 0; k < 8; k++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    }
    table[n] = c >>> 0
  }
  return table
})()

function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff
  for (let i = 0; i < bytes.length; i++) {
    c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8)
  }
  return (c ^ 0xffffffff) >>> 0
}

function encodeUtf8(s: string): Uint8Array {
  return new TextEncoder().encode(s)
}

export function buildZip(entries: ZipEntry[]): Uint8Array {
  const enc = new TextEncoder()
  const locals: Uint8Array[] = []
  const central: Uint8Array[] = []
  let offset = 0

  for (const entry of entries) {
    const nameBytes = enc.encode(entry.name)
    const data = entry.bytes
    const crc = crc32(data)

    // local file header
    const lfh = new DataView(new ArrayBuffer(30))
    lfh.setUint32(0, 0x04034b50, true)
    lfh.setUint16(4, 20, true) // version needed
    lfh.setUint16(6, 0x0800, true) // UTF-8 flag
    lfh.setUint16(8, 0, true) // stored
    lfh.setUint16(10, 0, true) // mod time
    lfh.setUint16(12, 0x21, true) // mod date (1980-01-01)
    lfh.setUint32(14, crc, true)
    lfh.setUint32(18, data.length, true)
    lfh.setUint32(22, data.length, true)
    lfh.setUint16(26, nameBytes.length, true)
    lfh.setUint16(28, 0, true) // extra len
    const lfhBytes = new Uint8Array(lfh.buffer)
    const local = concat([lfhBytes, nameBytes, data])
    locals.push(local)

    // central directory header
    const cdh = new DataView(new ArrayBuffer(46))
    cdh.setUint32(0, 0x02014b50, true)
    cdh.setUint16(4, 20, true) // version made by
    cdh.setUint16(6, 20, true) // version needed
    cdh.setUint16(8, 0x0800, true)
    cdh.setUint16(10, 0, true)
    cdh.setUint16(12, 0, true)
    cdh.setUint16(14, 0x21, true)
    cdh.setUint32(16, crc, true)
    cdh.setUint32(20, data.length, true)
    cdh.setUint32(24, data.length, true)
    cdh.setUint16(28, nameBytes.length, true)
    cdh.setUint16(30, 0, true)
    cdh.setUint16(32, 0, true)
    cdh.setUint16(34, 0, true)
    cdh.setUint16(36, 0, true)
    cdh.setUint32(38, 0, true)
    cdh.setUint32(42, offset, true)
    central.push(concat([new Uint8Array(cdh.buffer), nameBytes]))

    offset += local.length
  }

  const centralBytes = concat(central)
  const centralSize = centralBytes.length
  const centralOffset = offset

  const eocd = new DataView(new ArrayBuffer(22))
  eocd.setUint32(0, 0x06054b50, true)
  eocd.setUint16(4, 0, true)
  eocd.setUint16(6, 0, true)
  eocd.setUint16(8, entries.length, true)
  eocd.setUint16(10, entries.length, true)
  eocd.setUint32(12, centralSize, true)
  eocd.setUint32(16, centralOffset, true)
  eocd.setUint16(20, 0, true)

  return concat([...locals, centralBytes, new Uint8Array(eocd.buffer)])
}

function concat(parts: Uint8Array[]): Uint8Array {
  let total = 0
  for (const p of parts) total += p.length
  const out = new Uint8Array(total)
  let off = 0
  for (const p of parts) {
    out.set(p, off)
    off += p.length
  }
  return out
}

export { encodeUtf8 }
