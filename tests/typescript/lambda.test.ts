import { afterEach, describe, expect, it, vi } from 'vitest'
import { DocumentOCR } from '../../packages/passport-ocr/src/client'

const { send, destroy } = vi.hoisted(() => ({ send: vi.fn(), destroy: vi.fn() }))
vi.mock('../../packages/passport-ocr/node_modules/@aws-sdk/client-lambda', () => ({
  LambdaClient: class { send = send; destroy = destroy },
  InvokeCommand: class { constructor(readonly input: unknown) {} },
}))

const result = { status: 'success', documentType: 'passport', pageType: 'passport_biodata', errors: [] }
function payload(body: unknown) { return new TextEncoder().encode(JSON.stringify(body)) }

describe('Lambda invocation', () => {
  afterEach(() => vi.clearAllMocks())

  it.each([result, { statusCode: 200, body: JSON.stringify(result) }])('returns scan results and releases the AWS client', async (body) => {
    send.mockResolvedValueOnce({ Payload: payload(body) })
    const client = new DocumentOCR({ mode: 'lambda', functionName: 'ocr', retries: 0 })

    await expect(client.scan(Buffer.from('image'))).resolves.toEqual(result)
    expect(send).toHaveBeenCalledWith(expect.anything(), { abortSignal: expect.any(AbortSignal) })
    expect(destroy).toHaveBeenCalledOnce()
  })

  it('rejects function errors and releases the AWS client', async () => {
    send.mockResolvedValueOnce({ FunctionError: 'Unhandled', Payload: payload({ errorMessage: 'crash' }) })
    const client = new DocumentOCR({ mode: 'lambda', functionName: 'ocr', retries: 0 })

    await expect(client.scan(Buffer.from('image'))).rejects.toThrow('Lambda invocation failed: Unhandled')
    expect(destroy).toHaveBeenCalledOnce()
  })

  it('does not return or retry an API Gateway authentication error', async () => {
    send.mockResolvedValue({ Payload: payload({ statusCode: 401, body: JSON.stringify({ error: 'Unauthorized' }) }) })
    const client = new DocumentOCR({ mode: 'lambda', functionName: 'ocr', retries: 2 })

    await expect(client.scan(Buffer.from('image'))).rejects.toThrow('Unauthorized')
    expect(send).toHaveBeenCalledOnce()
    expect(destroy).toHaveBeenCalledOnce()
  })

  it('destroys the AWS client when send rejects', async () => {
    send.mockRejectedValueOnce(new Error('Connection reset'))
    const client = new DocumentOCR({ mode: 'lambda', functionName: 'ocr', retries: 0 })

    await expect(client.scan(Buffer.from('image'))).rejects.toThrow('Connection reset')
    expect(destroy).toHaveBeenCalledOnce()
  })

  it('preserves an HTTP rejection even if its body is not JSON', async () => {
    send.mockResolvedValue({ Payload: payload({ statusCode: 403, body: '<html>Forbidden</html>' }) })
    const client = new DocumentOCR({ mode: 'lambda', functionName: 'ocr', retries: 2 })

    await expect(client.scan(Buffer.from('image'))).rejects.toThrow('OCR request failed: 403')
    expect(send).toHaveBeenCalledOnce()
  })
})

describe('Lambda S3 and payload limits', () => {
  afterEach(() => vi.clearAllMocks())

  it('sends a versioned S3 reference and scan options', async () => {
    send.mockResolvedValueOnce({ Payload: payload(result) })
    const client = new DocumentOCR({ mode: 'lambda', functionName: 'ocr', retries: 0 })
    await client.scanS3({ bucket: 'private-documents', key: 'incoming/synthetic.png', versionId: 'version-1' }, {
      documentType: 'us_w9', country: 'USA', includeEvidence: false,
    })
    const command = send.mock.calls[0][0]
    expect(JSON.parse(command.input.Payload)).toEqual({
      s3: { bucket: 'private-documents', key: 'incoming/synthetic.png', version_id: 'version-1' },
      document_type: 'us_w9', country: 'USA', include_evidence: false,
    })
  })

  it('accepts a serialized payload at exactly 6 MiB', async () => {
    send.mockResolvedValueOnce({ Payload: payload(result) })
    const client = new DocumentOCR({ mode: 'lambda', functionName: 'ocr', retries: 0 })
    // Keep base64 valid while padding the options to reach the exact byte limit.
    const base64 = 'A'.repeat(6 * 1024 * 1024 - 40)
    const options = { country: 'A'.repeat(8) }
    expect(Buffer.byteLength(JSON.stringify({ image_base64: base64, country: options.country }))).toBe(6 * 1024 * 1024)
    await expect(client.scan(base64, options)).resolves.toEqual(result)
    expect(send).toHaveBeenCalledOnce()
  })

  it('counts JSON and UTF-8 overhead and never invokes AWS for oversized requests', async () => {
    const client = new DocumentOCR({ mode: 'lambda', functionName: 'ocr', retries: 2 })
    const base64 = 'A'.repeat(6 * 1024 * 1024 - 40)
    await expect(client.scan(base64, { country: '界'.repeat(3) })).rejects.toThrow('exceeds 6 MiB')
    expect(send).not.toHaveBeenCalled()
    expect(destroy).not.toHaveBeenCalled()
  })

  it('rejects unsupported mode operations and malformed references locally', async () => {
    const client = new DocumentOCR({ mode: 'lambda', functionName: 'ocr' })
    await expect(client.scanBatch([Buffer.from('image')])).rejects.toThrow('requires local or http')
    await expect(client.documents()).rejects.toThrow('requires local or http')
    await expect(client.scanS3({ bucket: '', key: 'synthetic' })).rejects.toThrow('requires bucket')
    expect(send).not.toHaveBeenCalled()
  })
})
