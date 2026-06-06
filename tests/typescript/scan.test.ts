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
  close: () => Promise<void>
}

function startServer(responder: Responder): Promise<TestServer> {
  let count = 0
  const server: Server = createServer((req, res) => {
    count += 1
    const thisCount = count
    // Drain the request body (multipart form upload) so the socket frees up.
    req.resume()
    req.on('end', () => {
      const { status, body, delayMs = 0 } = responder(thisCount)
      const send = () => {
        res.writeHead(status, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify(body))
      }
      if (delayMs > 0) setTimeout(send, delayMs)
      else send()
    })
  })

  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as AddressInfo
      resolve({
        url: `http://127.0.0.1:${port}`,
        requestCount: () => count,
        close: () =>
          new Promise<void>((res) => {
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
    backPageFields: null,
    panFields: null,
    aadhaarFields: null,
    drivingLicenceFields: null,
    voterIdFields: null,
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
    if (result.documentType === 'pan') {
      expect(result.panFields?.panNumber).toBe('ABCPE1234F')
      expect(result.panFields?.name).toBe('ROHIT SHARMA')
    }
    expect(result.fields).toBeNull()
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

  it('throws the server error message on 400', async () => {
    const server = await withServer(() => ({
      status: 400,
      body: { error: 'INVALID_CONTENT_TYPE' },
    }))
    const client = new DocumentOCR({ mode: 'http', endpoint: server.url, retries: 0 })

    await expect(client.scan(Buffer.from('fake-image-bytes'))).rejects.toThrow(
      'INVALID_CONTENT_TYPE',
    )
    expect(server.requestCount()).toBe(1)
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
