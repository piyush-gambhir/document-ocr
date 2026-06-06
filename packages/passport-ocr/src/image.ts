import type { ImageInput } from './types'

/**
 * Normalise any supported image input to a base64 string.
 */
export async function normalizeToBase64(input: ImageInput): Promise<string> {
  // Already a base64 string
  if (typeof input === 'string' && !input.startsWith('http')) {
    return input
  }

  // URL — fetch first
  if (typeof input === 'string' && input.startsWith('http')) {
    const res = await fetch(input)
    if (!res.ok) throw new Error(`Failed to fetch image from URL: ${res.status}`)
    const buf = await res.arrayBuffer()
    return arrayBufferToBase64(buf)
  }

  // Buffer (Node.js)
  if (typeof Buffer !== 'undefined' && Buffer.isBuffer(input)) {
    return input.toString('base64')
  }

  // ArrayBuffer
  if (input instanceof ArrayBuffer) {
    return arrayBufferToBase64(input)
  }

  // Blob / File
  if (typeof Blob !== 'undefined' && input instanceof Blob) {
    const buf = await input.arrayBuffer()
    return arrayBufferToBase64(buf)
  }

  throw new Error('Unsupported image input type')
}

/**
 * Normalise any supported image input to a Blob for FormData upload.
 */
export async function normalizeToBlob(input: ImageInput): Promise<Blob> {
  // Blob / File
  if (typeof Blob !== 'undefined' && input instanceof Blob) {
    return input
  }

  // Buffer (Node.js) — copy to a fresh ArrayBuffer-backed Uint8Array. This
  // avoids ReadableStream issues in Node 24+, only copies the Buffer's own
  // window (respecting byteOffset/byteLength on a subarray view), and yields a
  // BlobPart typed over ArrayBuffer (not the SharedArrayBuffer-inclusive
  // ArrayBufferLike that `input.buffer` widens to).
  if (typeof Buffer !== 'undefined' && Buffer.isBuffer(input)) {
    const copy = new Uint8Array(input)
    return new Blob([copy], { type: 'image/jpeg' })
  }

  // ArrayBuffer
  if (input instanceof ArrayBuffer) {
    return new Blob([input])
  }

  // URL — fetch
  if (typeof input === 'string' && input.startsWith('http')) {
    const res = await fetch(input)
    if (!res.ok) throw new Error(`Failed to fetch image from URL: ${res.status}`)
    return res.blob()
  }

  // Base64 string
  if (typeof input === 'string') {
    const binary = atob(input)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i)
    }
    return new Blob([bytes])
  }

  throw new Error('Unsupported image input type')
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  if (typeof Buffer !== 'undefined') {
    return Buffer.from(buffer).toString('base64')
  }
  // Browser
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary)
}
