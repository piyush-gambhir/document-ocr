import { afterEach, describe, it, expect, vi } from 'vitest'
import { DocumentOCR } from '../../packages/passport-ocr/src/client'

describe('DocumentOCR client', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('throws if http mode has no endpoint', () => {
    expect(() => new DocumentOCR({ mode: 'http' })).toThrow('endpoint is required')
  })

  it('throws if lambda mode has no functionName', () => {
    expect(() => new DocumentOCR({ mode: 'lambda' })).toThrow('functionName is required')
  })

  it('creates http client with endpoint', () => {
    const client = new DocumentOCR({ mode: 'http', endpoint: 'http://localhost:8000' })
    expect(client).toBeDefined()
  })

  it('creates lambda client with functionName', () => {
    const client = new DocumentOCR({ mode: 'lambda', functionName: 'my-fn' })
    expect(client).toBeDefined()
  })

  it('defaults to local mode', () => {
    const client = new DocumentOCR()
    expect(client).toBeDefined()
  })

  it('creates local client without any options', () => {
    const client = new DocumentOCR({})
    expect(client).toBeDefined()
  })

  it('warns if endpoint is provided in local mode', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const client = new DocumentOCR({ endpoint: 'http://localhost:8000' })
    expect(client).toBeDefined()
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining('endpoint is ignored in local mode'),
    )
  })

  it('does not warn when endpoint is provided in http mode', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const client = new DocumentOCR({ mode: 'http', endpoint: 'http://localhost:8000' })
    expect(client).toBeDefined()
    expect(warnSpy).not.toHaveBeenCalled()
  })

  it('returns unsupported-page results without throwing in http mode', async () => {
    const client = new DocumentOCR({ mode: 'http', endpoint: 'http://localhost:8000' })
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        status: 'unsupported_page',
        documentType: 'passport',
        pageType: 'passport_non_biodata',
        confidence: 0.91,
        fields: null,
        mrzRaw: null,
        mrzValid: false,
        lowConfidence: false,
        unsupportedReason: 'NON_BIODATA_PAGE',
        probeText: ['name of father'],
        errors: [],
        warnings: ['NON_BIODATA_HINTS_2'],
        processingMs: 80,
      }),
    })

    vi.stubGlobal('fetch', fetchMock)
    const result = await client.scan(Buffer.from('test'))

    expect(result.status).toBe('unsupported_page')
    expect(result.pageType).toBe('passport_non_biodata')
  })
})
