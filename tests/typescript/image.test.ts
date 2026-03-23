import { describe, it, expect } from 'vitest'
import { normalizeToBase64 } from '../../packages/passport-ocr/src/image'

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
