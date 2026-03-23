import { describe, it, expect } from 'vitest'
import { PassportOCR } from '../../packages/passport-ocr/src/client'

describe('PassportOCR client', () => {
  it('throws if http mode has no endpoint', () => {
    expect(() => new PassportOCR({ mode: 'http' })).toThrow('endpoint is required')
  })

  it('throws if lambda mode has no functionName', () => {
    expect(() => new PassportOCR({ mode: 'lambda' })).toThrow('functionName is required')
  })

  it('creates http client with endpoint', () => {
    const client = new PassportOCR({ endpoint: 'http://localhost:8000' })
    expect(client).toBeDefined()
  })

  it('creates lambda client with functionName', () => {
    const client = new PassportOCR({ mode: 'lambda', functionName: 'my-fn' })
    expect(client).toBeDefined()
  })

  it('defaults to http mode', () => {
    const client = new PassportOCR({ endpoint: 'http://localhost:8000' })
    expect(client).toBeDefined()
  })
})
