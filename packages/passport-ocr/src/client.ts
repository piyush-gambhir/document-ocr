import type {
  BatchScanResult, DocumentCatalog, DocumentOCROptions, DocumentScanResult, DocumentScanGroupResult,
  ImageInput, ScanOptions, S3ImageInput, JobOptions, OCRJob,
} from './types'
import { normalizeToBase64, normalizeToBlob } from './image'
import { validateRetryOptions, withRetry } from './retry'
import { HttpError, InputValidationError } from './errors'
import { getLocalServer } from './local-server'

const MAX_LAMBDA_PAYLOAD_BYTES = 6 * 1024 * 1024

export class DocumentOCR {
  private mode: 'local' | 'http' | 'lambda'
  private endpoint?: string
  private functionName?: string
  private timeoutMs: number
  private retries: number
  private apiKey?: string
  private authHeaders?: DocumentOCROptions['authHeaders']

  constructor(options: DocumentOCROptions = {}) {
    this.mode = options.mode ?? 'local'
    this.endpoint = options.endpoint
    this.functionName = options.functionName
    this.timeoutMs = options.timeoutMs ?? 30000
    this.retries = options.retries ?? 2
    this.apiKey = options.apiKey
    this.authHeaders = options.authHeaders
    validateRetryOptions({ retries: this.retries, timeoutMs: this.timeoutMs })
    if (this.mode === 'http' && !this.endpoint) throw new Error('endpoint is required for http mode')
    if (this.mode === 'lambda' && !this.functionName) throw new Error('functionName is required for lambda mode')
    if (this.mode === 'local' && this.endpoint) {
      console.warn('document-ocr: endpoint is ignored in local mode. ' +
        'Use mode: "http" if you want to connect to an external server.')
    }
  }

  async scan(image: ImageInput, options: ScanOptions = {}): Promise<DocumentScanResult> {
    const parameters = scanParameters(options)
    return this.retry(async (signal) => {
      if (this.mode === 'lambda') {
        const base64 = await normalizeToBase64(image, signal)
        return this.invokeLambda({ image_base64: base64, ...parameters }, signal)
      }
      const form = new FormData()
      form.append('image', await normalizeToBlob(image, signal), 'document')
      appendParameters(form, parameters)
      const { status, data } = await this.request('/scan', signal, { method: 'POST', body: form })
      return parseScanResponse(status, data)
    })
  }

  async scanBatch(images: ImageInput[], options: ScanOptions = {}): Promise<BatchScanResult> {
    return this.uploadMany('/scan/batch', images, options)
  }

  async scanDocument(images: ImageInput[], options: ScanOptions = {}): Promise<DocumentScanGroupResult> {
    return this.uploadMany('/scan/document', images, options) as Promise<DocumentScanGroupResult>
  }

  private async uploadMany(path: string, images: ImageInput[], options: ScanOptions): Promise<BatchScanResult> {
    this.requireHttp(path === '/scan/batch' ? 'scanBatch' : 'scanDocument')
    if (!Array.isArray(images) || images.length === 0) throw new InputValidationError('scanBatch requires at least one image')
    const parameters = scanParameters(options)
    return this.retry(async (signal) => {
      const form = new FormData()
      for (const [index, image] of images.entries()) {
        form.append('images', await normalizeToBlob(image, signal), `document-${index}`)
      }
      appendParameters(form, parameters)
      const { status, data } = await this.request(path, signal, { method: 'POST', body: form })
      const body = asObject(data)
      const valid = body !== null && ['success', 'partial', 'failure'].includes(String(body.status))
        && Array.isArray(body.results) && body.results.every(isScanResult) && Array.isArray(body.errors)
      checkStatus(status, data, status === 422 && valid)
      if (!valid) throw new Error('Invalid OCR response: expected a batch scan result')
      if (path === '/scan/document' && (!asObject(body.documentFields) || !Array.isArray(body.conflicts))) {
        throw new Error('Invalid OCR response: expected grouped document fields and conflicts')
      }
      return data as BatchScanResult
    })
  }

  async documents(): Promise<DocumentCatalog> {
    this.requireHttp('documents')
    return this.retry(async (signal) => {
      const { status, data } = await this.request('/documents', signal)
      checkStatus(status, data)
      const body = asObject(data)
      if (!body || typeof body.schemaVersion !== 'number' || !Array.isArray(body.documents) || !asObject(body.capabilities)) {
        throw new Error('Invalid OCR response: expected a document catalog')
      }
      return data as DocumentCatalog
    })
  }

  async enqueueJob(images: ImageInput[], options: JobOptions = {}): Promise<OCRJob> {
    this.requireHttp('enqueueJob')
    if (!Array.isArray(images) || images.length === 0) throw new InputValidationError('enqueueJob requires at least one image')
    const parameters = scanParameters(options)
    for (const key of ['grouped', 'notify'] as const) {
      if (options[key] !== undefined) {
        if (typeof options[key] !== 'boolean') throw new InputValidationError(`${key} must be boolean`)
        parameters[key] = options[key]
      }
    }
    // Submission creates persistent work. Do not retry it automatically without
    // server-side idempotency: a lost response could otherwise enqueue twice.
    return withRetry(async (signal) => {
      const form = new FormData()
      for (const [index, image] of images.entries()) form.append('images', await normalizeToBlob(image, signal), `document-${index}`)
      appendParameters(form, parameters)
      const { status, data } = await this.request('/jobs', signal, { method: 'POST', body: form })
      checkStatus(status, data)
      return parseJob(data)
    }, { retries: 0, timeoutMs: this.timeoutMs })
  }

  async job(id: string): Promise<OCRJob> {
    this.requireHttp('job')
    const path = jobPath(id)
    return this.retry(async (signal) => {
      const { status, data } = await this.request(path, signal)
      checkStatus(status, data)
      return parseJob(data)
    })
  }

  async deleteJob(id: string): Promise<{ deleted: true }> {
    this.requireHttp('deleteJob')
    const path = jobPath(id)
    return this.retry(async (signal) => {
      const { status, data } = await this.request(path, signal, { method: 'DELETE' })
      checkStatus(status, data)
      if (asObject(data)?.deleted !== true) throw new Error('Invalid OCR response: expected deletion confirmation')
      return { deleted: true }
    })
  }

  async scanS3(image: S3ImageInput, options: ScanOptions = {}): Promise<DocumentScanResult> {
    if (this.mode !== 'lambda') throw new InputValidationError('scanS3 is available only in lambda mode')
    if (!image || typeof image.bucket !== 'string' || !image.bucket.trim()
        || typeof image.key !== 'string' || !image.key.trim()
        || (image.versionId !== undefined && (typeof image.versionId !== 'string' || !image.versionId))) {
      throw new InputValidationError('scanS3 requires bucket, key, and an optional non-empty versionId')
    }
    const parameters = scanParameters(options)
    const s3 = { bucket: image.bucket, key: image.key, ...(image.versionId === undefined ? {} : { version_id: image.versionId }) }
    return this.retry((signal) => this.invokeLambda({ s3, ...parameters }, signal))
  }

  async stop(): Promise<void> {
    if (this.mode === 'local') await getLocalServer().stop()
  }

  private requireHttp(method: string): void {
    if (this.mode === 'lambda') throw new InputValidationError(`${method} requires local or http mode`)
  }

  private retry<T>(operation: (signal: AbortSignal) => Promise<T>): Promise<T> {
    return withRetry(operation, { retries: this.retries, timeoutMs: this.timeoutMs })
  }

  private async request(path: string, signal: AbortSignal, init: RequestInit = {}): Promise<{ status: number, data: unknown }> {
    const endpoint = this.mode === 'local' ? await getLocalServer().ensureRunning() : this.endpoint!
    const url = `${endpoint.replace(/\/+$/, '')}${path}`
    signal.throwIfAborted()
    const headers = new Headers(this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : {})
    if (this.authHeaders) {
      new Headers(await this.authHeaders(url, signal)).forEach((value, key) => headers.set(key, value))
    }
    signal.throwIfAborted()
    const response = await fetch(url, { ...init, headers, signal })
    const data: unknown = await response.json().catch(() => null)
    return { status: response.status, data }
  }

  private async invokeLambda(event: Record<string, unknown>, signal: AbortSignal): Promise<DocumentScanResult> {
    const payload = JSON.stringify(event)
    if (new TextEncoder().encode(payload).byteLength > MAX_LAMBDA_PAYLOAD_BYTES) {
      throw new InputValidationError('Lambda payload exceeds 6 MiB; upload the image to S3 and use scanS3()')
    }
    signal.throwIfAborted()
    const { LambdaClient, InvokeCommand } = await import('@aws-sdk/client-lambda')
    signal.throwIfAborted()
    const client = new LambdaClient({})
    const command = new InvokeCommand({ FunctionName: this.functionName, Payload: payload })
    try {
      const response = await client.send(command, { abortSignal: signal })
      if (response.FunctionError) throw new Error(`Lambda invocation failed: ${response.FunctionError}`)
      const result = JSON.parse(new TextDecoder().decode(response.Payload))
      if (typeof result?.statusCode === 'number') {
        let body: unknown = result.body
        if (typeof body === 'string') {
          try { body = JSON.parse(body) } catch { body = null }
        }
        return parseScanResponse(result.statusCode, body)
      }
      return parseScanResponse(200, result)
    } finally {
      client.destroy()
    }
  }
}

function scanParameters(options: ScanOptions): Record<string, string | boolean> {
  if (!options || typeof options !== 'object') throw new InputValidationError('scan options must be an object')
  const result: Record<string, string | boolean> = {}
  for (const [key, wireKey] of [['documentType', 'document_type'], ['country', 'country']] as const) {
    const value = options[key]
    if (value !== undefined) {
      if (typeof value !== 'string' || !value.trim()) throw new InputValidationError(`${key} must be a non-empty string`)
      result[wireKey] = value
    }
  }
  if (options.includeEvidence !== undefined) {
    if (typeof options.includeEvidence !== 'boolean') throw new InputValidationError('includeEvidence must be boolean')
    result.include_evidence = options.includeEvidence
  }
  return result
}

function appendParameters(form: FormData, parameters: Record<string, string | boolean>): void {
  for (const [key, value] of Object.entries(parameters)) form.append(key, String(value))
}

function jobPath(id: string): string {
  if (typeof id !== 'string' || !/^[A-Za-z0-9_-]+$/.test(id)) throw new InputValidationError('job id must contain letters, digits, hyphens, or underscores')
  return `/jobs/${encodeURIComponent(id)}`
}

function parseJob(data: unknown): OCRJob {
  const body = asObject(data)
  if (!body || typeof body.id !== 'string' || !['queued', 'running', 'succeeded', 'failed'].includes(String(body.status))
      || typeof body.createdAt !== 'number' || typeof body.expiresAt !== 'number' || typeof body.attempts !== 'number'
      || (body.error !== null && typeof body.error !== 'string')) throw new Error('Invalid OCR response: expected a job')
  return data as OCRJob
}

function asObject(data: unknown): Record<string, unknown> | null {
  return data !== null && typeof data === 'object' && !Array.isArray(data) ? data as Record<string, unknown> : null
}

function isScanResult(data: unknown): boolean {
  const body = asObject(data)
  return body !== null && ['success', 'failure', 'unsupported_page'].includes(String(body.status))
    && typeof body.documentType === 'string' && typeof body.pageType === 'string' && Array.isArray(body.errors)
}

function checkStatus(status: number, data: unknown, allow422 = false): void {
  if ((status >= 200 && status < 300) || allow422) return
  const body = asObject(data)
  const message = typeof body?.error === 'string' ? body.error
    : typeof body?.detail === 'string' ? body.detail : `OCR request failed: ${status}`
  throw new HttpError(status, message)
}

function parseScanResponse(status: number, data: unknown): DocumentScanResult {
  const valid = isScanResult(data)
  checkStatus(status, data, status === 422 && valid)
  if (!valid) throw new Error('Invalid OCR response: expected a document scan result')
  return data as DocumentScanResult
}

export const PassportOCR = DocumentOCR
