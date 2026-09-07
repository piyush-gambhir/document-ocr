import { afterEach, describe, expect, it, vi } from 'vitest'
import { DocumentOCR } from '../../packages/passport-ocr/src/client'

const result = {
  status: 'success', documentType: 'us_driver_license', pageType: 'us_driver_license', errors: [],
  schemaVersion: 1, documentFields: { licenseNumber: 'SYNTHETIC' }, issuingCountry: 'USA',
  fieldEvidence: { licenseNumber: [{ text: 'SYNTHETIC', bbox: [[0, 0]], confidence: 0.98, source: 'pdf417' }] },
  checks: { format: true },
}
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('expanded HTTP client', () => {
  it('sends scan options as multipart fields and preserves evidence', async () => {
    const fetch = vi.fn().mockResolvedValue(response(result))
    vi.stubGlobal('fetch', fetch)
    const client = new DocumentOCR({ mode: 'http', endpoint: 'https://ocr.example' })
    const actual = await client.scan(Buffer.from('image'), { documentType: 'us_driver_license', country: 'USA', includeEvidence: false })
    const form: FormData = fetch.mock.calls[0][1].body
    expect(form.get('image')).toBeInstanceOf(Blob)
    expect(form.get('document_type')).toBe('us_driver_license')
    expect(form.get('country')).toBe('USA')
    expect(form.get('include_evidence')).toBe('false')
    expect(actual).toEqual(result)
  })

  it('refreshes IAM headers on retry and retains static token fallback', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response({ error: 'busy' }, 503)).mockResolvedValueOnce(response(result))
    vi.stubGlobal('fetch', fetch)
    const authHeaders = vi.fn().mockResolvedValueOnce({ 'x-trace': 'first' }).mockResolvedValueOnce({ authorization: 'Bearer refreshed' })
    const client = new DocumentOCR({ mode: 'http', endpoint: 'https://ocr.example/', apiKey: 'fallback', authHeaders, retries: 1 })
    await client.scan(Buffer.from('image'))
    expect(authHeaders).toHaveBeenCalledTimes(2)
    expect(authHeaders).toHaveBeenCalledWith('https://ocr.example/scan', expect.any(AbortSignal))
    expect(fetch.mock.calls[0][1].headers.get('authorization')).toBe('Bearer fallback')
    expect(fetch.mock.calls[1][1].headers.get('authorization')).toBe('Bearer refreshed')
  })

  it('applies the attempt deadline to asynchronous authentication', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const client = new DocumentOCR({ mode: 'http', endpoint: 'https://ocr.example', timeoutMs: 10, retries: 0,
      authHeaders: () => new Promise(() => {}),
    })
    await expect(client.scan(Buffer.from('image'))).rejects.toThrow('timed out')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('uploads a batch in input order using repeated images keys', async () => {
    const batch = { results: [result, { ...result, status: 'failure' }], status: 'partial', errors: [] }
    const fetch = vi.fn().mockResolvedValue(response(batch))
    vi.stubGlobal('fetch', fetch)
    const client = new DocumentOCR({ mode: 'http', endpoint: 'https://ocr.example' })
    await expect(client.scanBatch([Buffer.from('first'), Buffer.from('second')], { includeEvidence: true })).resolves.toEqual(batch)
    expect(fetch.mock.calls[0][0]).toBe('https://ocr.example/scan/batch')
    const form: FormData = fetch.mock.calls[0][1].body
    expect(await Promise.all(form.getAll('images').map((item) => (item as Blob).text()))).toEqual(['first', 'second'])
    expect(form.get('include_evidence')).toBe('true')
  })

  it('fetches the document catalog with authentication', async () => {
    const catalog = { schemaVersion: 1, documents: [], capabilities: { barcode: true, jobs: false, review: false, multipage: true } }
    const fetch = vi.fn().mockResolvedValue(response(catalog))
    vi.stubGlobal('fetch', fetch)
    const client = new DocumentOCR({ mode: 'http', endpoint: 'https://ocr.example', apiKey: 'key' })
    await expect(client.documents()).resolves.toEqual(catalog)
    expect(fetch.mock.calls[0][0]).toBe('https://ocr.example/documents')
    expect(fetch.mock.calls[0][1].body).toBeUndefined()
    expect(fetch.mock.calls[0][1].headers.get('authorization')).toBe('Bearer key')
  })

  it('returns grouped page conflicts without silently merging mismatched identities', async () => {
    const grouped = { results: [result, result], status: 'failure', errors: ['FIELD_CONFLICT'], documentFields: {},
      conflicts: [{ field: 'name', values: [{ page: 1, value: 'SYNTHETIC A' }, { page: 2, value: 'SYNTHETIC B' }] }],
    }
    const fetch = vi.fn().mockResolvedValue(response(grouped, 422))
    vi.stubGlobal('fetch', fetch)
    const client = new DocumentOCR({ mode: 'http', endpoint: 'https://ocr.example' })
    await expect(client.scanDocument([Buffer.from('front'), Buffer.from('back')], { documentType: 'us_driver_license' })).resolves.toEqual(grouped)
    expect(fetch.mock.calls[0][0]).toBe('https://ocr.example/scan/document')
    expect(fetch.mock.calls[0][1].body.getAll('images')).toHaveLength(2)
    expect(fetch).toHaveBeenCalledOnce()
  })

  it('rejects invalid local input without fetching or retrying', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const client = new DocumentOCR({ mode: 'http', endpoint: 'https://ocr.example', retries: 2 })
    await expect(client.scanBatch([])).rejects.toThrow('at least one image')
    await expect(client.scan('%%%')).rejects.toThrow('base64')
    await expect(client.scan(Buffer.from('image'), { country: '' })).rejects.toThrow('country')
    expect(fetch).not.toHaveBeenCalled()
  })
})

describe('persistent jobs', () => {
  const queued = { id: 'job-1', status: 'queued', createdAt: 1, expiresAt: 61, attempts: 0, error: null }

  it('submits grouped job options, reads completion, and deletes results', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response(queued, 202))
      .mockResolvedValueOnce(response({ ...queued, status: 'succeeded', result: { status: 'success', results: [result], errors: [] } }))
      .mockResolvedValueOnce(response({ deleted: true }))
    vi.stubGlobal('fetch', fetch)
    const client = new DocumentOCR({ mode: 'http', endpoint: 'https://ocr.example' })
    await expect(client.enqueueJob([Buffer.from('image')], { grouped: true, notify: false, includeEvidence: true })).resolves.toEqual(queued)
    const form: FormData = fetch.mock.calls[0][1].body
    expect(form.get('grouped')).toBe('true')
    expect(form.get('notify')).toBe('false')
    expect(form.get('include_evidence')).toBe('true')
    await expect(client.job('job-1')).resolves.toMatchObject({ status: 'succeeded' })
    await expect(client.deleteJob('job-1')).resolves.toEqual({ deleted: true })
    expect(fetch.mock.calls.map((call) => call[0])).toEqual(['https://ocr.example/jobs', 'https://ocr.example/jobs/job-1', 'https://ocr.example/jobs/job-1'])
    expect(fetch.mock.calls[2][1].method).toBe('DELETE')
  })

  it('does not duplicate job submission after a lost response', async () => {
    const fetch = vi.fn().mockRejectedValue(new Error('Connection reset after upload'))
    vi.stubGlobal('fetch', fetch)
    const client = new DocumentOCR({ mode: 'http', endpoint: 'https://ocr.example', retries: 3 })
    await expect(client.enqueueJob([Buffer.from('image')])).rejects.toThrow('Connection reset')
    expect(fetch).toHaveBeenCalledOnce()
    await expect(client.job('../other')).rejects.toThrow('job id')
  })
})
