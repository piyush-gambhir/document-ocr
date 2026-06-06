import { describe, it, expect } from 'vitest'
import {
  normalizeToBase64,
  normalizeToBlob,
} from '../../packages/passport-ocr/src/image'

describe('normalizeToBase64', () => {
  it('passes through base64 string', async () => {
    const input = 'SGVsbG8gV29ybGQ='
    const result = await normalizeToBase64(input)
    expect(result).toBe(input)
  })

  it('converts Buffer to base64', async () => {
    const buf = Buffer.from('Hello World')
    const result = await normalizeToBase64(buf)
    expect(result).toBe(buf.toString('base64'))
  })

  it('converts ArrayBuffer to base64', async () => {
    const buf = Buffer.from('Hello World')
    const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength)
    const result = await normalizeToBase64(ab)
    expect(result).toBe(buf.toString('base64'))
  })
})

describe('normalizeToBlob', () => {
  async function blobBytes(blob: Blob): Promise<Uint8Array> {
    return new Uint8Array(await blob.arrayBuffer())
  }

  it('passes a Blob through unchanged', async () => {
    const input = new Blob([new Uint8Array([1, 2, 3])])
    const result = await normalizeToBlob(input)
    expect(result).toBe(input)
  })

  it('converts a Buffer to a Blob preserving bytes', async () => {
    const buf = Buffer.from('Hello World')
    const blob = await normalizeToBlob(buf)
    expect(blob).toBeInstanceOf(Blob)
    expect(await blobBytes(blob)).toEqual(new Uint8Array(buf))
    expect(blob.type).toBe('image/jpeg')
  })

  it('converts a Buffer slice using the correct byte offset', async () => {
    // A Buffer that is a view into a larger ArrayBuffer must copy only its
    // own window, not the whole backing buffer.
    const backing = Buffer.from('XXXXHello WorldYYYY')
    const view = backing.subarray(4, 15) // "Hello World"
    const blob = await normalizeToBlob(view)
    expect(Buffer.from(await blob.arrayBuffer()).toString()).toBe('Hello World')
  })

  it('converts an ArrayBuffer to a Blob', async () => {
    const buf = Buffer.from('payload')
    const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength)
    const blob = await normalizeToBlob(ab)
    expect(await blobBytes(blob)).toEqual(new Uint8Array(buf))
  })

  it('decodes a base64 string to a Blob', async () => {
    const base64 = Buffer.from('Hello World').toString('base64')
    const blob = await normalizeToBlob(base64)
    expect(Buffer.from(await blob.arrayBuffer()).toString()).toBe('Hello World')
  })

  it('throws on an unsupported input type', async () => {
    // @ts-expect-error — deliberately passing an unsupported type
    await expect(normalizeToBlob(42)).rejects.toThrow('Unsupported image input type')
  })
})
