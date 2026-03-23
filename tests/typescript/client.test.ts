import { describe, it, expect, vi } from 'vitest'
import { PassportOCR } from '../../packages/passport-ocr/src/client'

describe('PassportOCR client', () => {
  it('throws if http mode has no endpoint', () => {
    expect(() => new PassportOCR({ mode: 'http' })).toThrow('endpoint is required')
  })

  it('throws if lambda mode has no functionName', () => {
    expect(() => new PassportOCR({ mode: 'lambda' })).toThrow('functionName is required')
  })

  it('creates http client with endpoint', () => {
    const client = new PassportOCR({ mode: 'http', endpoint: 'http://localhost:8000' })
    expect(client).toBeDefined()
  })

  it('creates lambda client with functionName', () => {
    const client = new PassportOCR({ mode: 'lambda', functionName: 'my-fn' })
    expect(client).toBeDefined()
  })

  it('defaults to local mode', () => {
    const client = new PassportOCR()
    expect(client).toBeDefined()
  })

  it('creates local client without any options', () => {
    const client = new PassportOCR({})
    expect(client).toBeDefined()
  })

  it('warns if endpoint is provided in local mode', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const client = new PassportOCR({ endpoint: 'http://localhost:8000' })
    expect(client).toBeDefined()
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining('endpoint is ignored in local mode'),
    )
    warnSpy.mockRestore()
  })

  it('does not warn when endpoint is provided in http mode', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const client = new PassportOCR({ mode: 'http', endpoint: 'http://localhost:8000' })
    expect(client).toBeDefined()
    expect(warnSpy).not.toHaveBeenCalled()
    warnSpy.mockRestore()
  })
})
