import { describe, expect, it, vi } from 'vitest'
import { gateway, instanceCount } from '../src/gateway'

describe('OCR gateway', () => {
  it('loads only the public review shell before a browser supplies its token', async () => {
    const forward = vi.fn(async () => new Response('<html>Token entry</html>'))
    const response = await gateway(new Request('https://ocr.test/review'), 'correct', forward)
    expect(response.status).toBe(200)
    expect(response.headers.get('Cache-Control')).toBe('no-store')
    expect(forward).toHaveBeenCalledOnce()
    for (const [path, method] of [['/review', 'POST'], ['/preview', 'POST'], ['/documents', 'GET'], ['/jobs/id', 'GET']]) {
      const denied = await gateway(new Request(`https://ocr.test${path}`, { method }), 'correct', forward)
      expect(denied.status).toBe(401)
    }
    expect(forward).toHaveBeenCalledOnce()
  })

  it('rejects a missing server secret without starting a container', async () => {
    const forward = vi.fn()
    const response = await gateway(new Request('https://ocr.test/scan'), undefined, forward)
    expect(response.status).toBe(503)
    expect(forward).not.toHaveBeenCalled()
  })

  it.each([null, 'Bearer wrong', 'Basic correct'])('rejects invalid credentials (%s) before routing', async (authorization) => {
    const headers = authorization ? { Authorization: authorization } : {}
    const forward = vi.fn()
    const response = await gateway(new Request('https://ocr.test/scan', { headers }), 'correct', forward)
    expect(response.status).toBe(401)
    expect(forward).not.toHaveBeenCalled()
  })

  it('forwards authenticated multipart requests and preserves partial-result status', async () => {
    const form = new FormData()
    form.append('image', new Blob(['synthetic'], { type: 'image/png' }), 'image.png')
    const request = new Request('https://ocr.test/scan/document?type=pan', {
      method: 'POST', headers: { Authorization: 'Bearer correct' }, body: form,
    })
    const forward = vi.fn(async (received: Request) => {
      expect(received).toBe(request)
      expect((await received.formData()).get('image')).toBeInstanceOf(Blob)
      return Response.json({ status: 'failure' }, { status: 422 })
    })
    const response = await gateway(request, 'correct', forward)
    expect(response.status).toBe(422)
    expect(response.headers.get('Cache-Control')).toBe('no-store')
    expect(await response.json()).toEqual({ status: 'failure' })
  })

  it('returns a retryable error when container startup fails', async () => {
    const request = new Request('https://ocr.test/ready', { headers: { Authorization: 'Bearer correct' } })
    const response = await gateway(request, 'correct', async () => { throw new Error('unavailable') })
    expect(response.status).toBe(503)
  })

  it.each(['0', '-1', '1.5', 'NaN', '101'])('rejects invalid pool size %s', (value) => {
    expect(() => instanceCount(value)).toThrow('CONTAINER_INSTANCES')
  })
})
