import { afterEach, describe, it, expect } from 'vitest'
import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import { DocumentOCR } from '../../packages/passport-ocr/src/client'

// ---------------------------------------------------------------------------
// Test HTTP server harness
//
// We spin a real ephemeral node:http server and point a `mode: 'http'` client
// at it. This exercises the real fetch / FormData / AbortSignal paths rather
// than mocking globalThis.fetch, so retry, timeout and status handling are
// tested end-to-end through the SDK.
// ---------------------------------------------------------------------------

type Responder = (count: number) => {
  status: number
  body: unknown
  delayMs?: number
}

interface TestServer {
  url: string
  requestCount: () => number
  paths: string[]
  close: () => Promise<void>
}

function startServer(responder: Responder): Promise<TestServer> {
  let count = 0
  const paths: string[] = []
  const timers = new Set<ReturnType<typeof setTimeout>>()
  const server: Server = createServer((req, res) => {
    count += 1
    paths.push(req.url ?? '')
    const thisCount = count
    // Drain the request body (multipart form upload) so the socket frees up.
    req.resume()
    req.on('end', () => {
      const { status, body, delayMs = 0 } = responder(thisCount)
      const send = () => {
        res.writeHead(status, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify(body))
      }
      if (delayMs > 0) timers.add(setTimeout(send, delayMs))
      else send()
    })
  })

  return new Promise((resolve, reject) => {
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as AddressInfo
      resolve({
        url: `http://127.0.0.1:${port}`,
        requestCount: () => count,
        paths,
        close: () =>
          new Promise<void>((res) => {
            for (const timer of timers) clearTimeout(timer)
            server.closeAllConnections?.()
            server.close(() => res())
          }),
      })
    })
  })
}

function successBody(overrides: Record<string, unknown> = {}) {
  return {
    status: 'success',
    documentType: 'passport',
    pageType: 'passport_biodata',
    confidence: 0.9,
    fields: {
      surname: 'KUMAR',
      givenNames: 'RAJ',
      fullName: 'RAJ KUMAR',
      passportNumber: 'J1234567',
      nationality: 'IND',
      dateOfBirth: '1990-05-20',
      sex: 'M',
      expiryDate: '2030-05-20',
      issueDate: null,
      placeOfBirth: null,
      countryCode: 'IND',
    },
    mrzRaw: null,
    mrzValid: true,
    lowConfidence: false,
    unsupportedReason: null,
    identifierValid: null,
    missingRequiredFields: [],
    backPageFields: null,
    panFields: null,
    aadhaarFields: null,
    drivingLicenceFields: null,
    voterIdFields: null,
    nregaJobCardFields: null,
    nprLetterFields: null,
    probeText: [],
    errors: [],
    warnings: [],
    processingMs: 120,
    ...overrides,
  }
}

describe('DocumentOCR.scan (http mode, real server)', () => {
  let servers: TestServer[] = []

  afterEach(async () => {
    await Promise.all(servers.map((s) => s.close()))
    servers = []
  })

  async function withServer(responder: Responder): Promise<TestServer> {
    const s = await startServer(responder)
    servers.push(s)
    return s
  }

  it('returns the parsed scan result on success', async () => {
    const server = await withServer(() => ({ status: 200, body: successBody() }))
    const client = new DocumentOCR({ mode: 'http', endpoint: server.url })

    const result = await client.scan(Buffer.from('fake-image-bytes'))

    expect(result.status).toBe('success')
    expect(result.documentType).toBe('passport')
    expect(result.fields?.passportNumber).toBe('J1234567')
    // Non-passport blocks are present and null on a passport result.
    expect(result.panFields).toBeNull()
    expect(result.aadhaarFields).toBeNull()
    expect(server.requestCount()).toBe(1)
  })

  it('returns a non-passport (PAN) document result', async () => {
    const panBody = successBody({
      documentType: 'pan',
      pageType: 'pan',
      fields: null,
      mrzValid: false,
      panFields: {
        panNumber: 'ABCPE1234F',
        name: 'ROHIT SHARMA',
        fatherName: 'MOHAN SHARMA',
        dateOfBirth: '15/08/1985',
      },
    })
    const server = await withServer(() => ({ status: 200, body: panBody }))
    const client = new DocumentOCR({ mode: 'http', endpoint: server.url })

    const result = await client.scan(Buffer.from('fake-image-bytes'))

    expect(result.status).toBe('success')
    expect(result.documentType).toBe('pan')
    expect(result.panFields?.panNumber).toBe('ABCPE1234F')
    expect(result.panFields?.name).toBe('ROHIT SHARMA')
    expect(result.fields).toBeNull()
  })

  it('returns nested NREGA member fields', async () => {
    const nregaBody = successBody({
      documentType: 'nrega_job_card',
      pageType: 'nrega_job_card',
      fields: null,
      mrzValid: false,
      identifierValid: true,
      nregaJobCardFields: {
        jobCardNumber: 'RJ-27-001-002-0008147/00',
        headOfHousehold: 'SYNTHETIC PERSON',
        category: 'SC',
        registrationDate: '14/03/2019',
        validityFrom: '01/04/2019',
        validityTo: '31/03/2024',
        address: null,
        village: 'SYNTHETIC VILLAGE',
        gramPanchayat: 'SYNTHETIC PANCHAYAT',
        block: null,
        district: 'SYNTHETIC DISTRICT',
        state: 'SYNTHETIC STATE',
        bplStatus: true,
        familyId: null,
        members: [
          {
            serialNumber: '1',
            name: 'SYNTHETIC PERSON',
            fatherOrHusbandName: null,
            gender: 'FEMALE',
            age: 39,
          },
        ],
      },
    })
    const server = await withServer(() => ({ status: 200, body: nregaBody }))
    const client = new DocumentOCR({ mode: 'http', endpoint: server.url })

    const result = await client.scan(Buffer.from('fake-image-bytes'))

    expect(result.documentType).toBe('nrega_job_card')
    expect(result.identifierValid).toBe(true)
    expect(result.nregaJobCardFields?.members[0]?.age).toBe(39)
  })

  it('retries on 5xx and then succeeds', async () => {
    // First attempt → 503, second attempt → 200.
    const server = await withServer((count) =>
      count === 1
        ? { status: 503, body: { error: 'TEMPORARILY_UNAVAILABLE' } }
        : { status: 200, body: successBody() },
    )
    const client = new DocumentOCR({ mode: 'http', endpoint: server.url, retries: 2 })

    const result = await client.scan(Buffer.from('fake-image-bytes'))

    expect(result.status).toBe('success')
    expect(server.requestCount()).toBe(2)
  })

  it('returns the failure body on 422 without throwing or retrying', async () => {
    const server = await withServer(() => ({
      status: 422,
      body: successBody({
        status: 'failure',
        mrzValid: false,
        errors: ['LOW_CONFIDENCE_EXTRACTION'],
      }),
    }))
    const client = new DocumentOCR({ mode: 'http', endpoint: server.url, retries: 2 })

    const result = await client.scan(Buffer.from('fake-image-bytes'))

    expect(result.status).toBe('failure')
    expect(result.errors).toContain('LOW_CONFIDENCE_EXTRACTION')
    // 422 is a definitive answer — the SDK must not retry it.
    expect(server.requestCount()).toBe(1)
  })

  it.each([400, 401, 403, 404, 413])('does not retry a definitive %i rejection', async (status) => {
    const server = await withServer(() => ({
      status,
      body: { error: 'INVALID_CONTENT_TYPE' },
    }))
    const client = new DocumentOCR({ mode: 'http', endpoint: server.url, retries: 2 })

    await expect(client.scan(Buffer.from('fake-image-bytes'))).rejects.toThrow(
      'INVALID_CONTENT_TYPE',
    )
    expect(server.requestCount()).toBe(1)
  })

  it.each([408, 429, 503])('retries transient %i errors regardless of message text', async (status) => {
    const server = await withServer((count) => count === 1
      ? { status, body: { error: 'upstream request 400422 is unavailable' } }
      : { status: 200, body: successBody() })
    const client = new DocumentOCR({ mode: 'http', endpoint: server.url, retries: 1 })

    await expect(client.scan(Buffer.from('image'))).resolves.toMatchObject({ status: 'success' })
    expect(server.requestCount()).toBe(2)
  })

  it('rejects transport validation errors on 422 instead of returning them as scan results', async () => {
    const server = await withServer(() => ({ status: 422, body: { detail: 'Missing image' } }))
    const client = new DocumentOCR({ mode: 'http', endpoint: server.url })

    await expect(client.scan(Buffer.from('image'))).rejects.toThrow('Missing image')
    expect(server.requestCount()).toBe(1)
  })

  it('accepts an endpoint with a trailing slash', async () => {
    const server = await withServer(() => ({ status: 200, body: successBody() }))
    const client = new DocumentOCR({ mode: 'http', endpoint: `${server.url}/` })

    await client.scan(Buffer.from('image'))
    expect(server.paths).toEqual(['/scan'])
  })

  it('applies the scan timeout to remote image downloads', async () => {
    const server = await withServer(() => ({ status: 200, body: successBody(), delayMs: 500 }))
    const client = new DocumentOCR({ mode: 'http', endpoint: server.url, retries: 0, timeoutMs: 50 })

    await expect(client.scan(`${server.url}/image.jpg`)).rejects.toThrow(/timed out/)
    expect(server.paths).toEqual(['/image.jpg'])
  })

  it('aborts via timeout and rejects when the server is too slow', async () => {
    // Server responds well after the client timeout → the per-attempt
    // AbortController fires and fetch rejects.
    const server = await withServer(() => ({
      status: 200,
      body: successBody(),
      delayMs: 500,
    }))
    const client = new DocumentOCR({
      mode: 'http',
      endpoint: server.url,
      retries: 0,
      timeoutMs: 50,
    })

    await expect(client.scan(Buffer.from('fake-image-bytes'))).rejects.toThrow()
  })
})
