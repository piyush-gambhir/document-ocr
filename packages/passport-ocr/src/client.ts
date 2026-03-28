import type { DocumentOCROptions, DocumentScanResult, ImageInput } from './types'
import { normalizeToBase64, normalizeToBlob } from './image'
import { withRetry } from './retry'
import { getLocalServer } from './local-server'

export class DocumentOCR {
  private mode: 'local' | 'http' | 'lambda'
  private endpoint?: string
  private functionName?: string
  private timeoutMs: number
  private retries: number
  private apiKey?: string

  constructor(options: DocumentOCROptions = {}) {
    this.mode = options.mode ?? 'local'
    this.endpoint = options.endpoint
    this.functionName = options.functionName
    this.timeoutMs = options.timeoutMs ?? 30000
    this.retries = options.retries ?? 2
    this.apiKey = options.apiKey

    if (this.mode === 'http' && !this.endpoint) {
      throw new Error('endpoint is required for http mode')
    }
    if (this.mode === 'lambda' && !this.functionName) {
      throw new Error('functionName is required for lambda mode')
    }
    if (this.mode === 'local' && this.endpoint) {
      console.warn(
        'document-ocr: endpoint is ignored in local mode. ' +
          'Use mode: "http" if you want to connect to an external server.',
      )
    }
  }

  async scan(image: ImageInput): Promise<DocumentScanResult> {
    return withRetry(
      (signal) => {
        if (this.mode === 'lambda') {
          return this.invokeLambda(image, signal)
        }
        if (this.mode === 'local') {
          return this.invokeLocal(image, signal)
        }
        return this.invokeHttp(image, signal)
      },
      { retries: this.retries, timeoutMs: this.timeoutMs },
    )
  }

  async stop(): Promise<void> {
    if (this.mode === 'local') {
      await getLocalServer().stop()
    }
  }

  private async invokeLocal(image: ImageInput, signal: AbortSignal): Promise<DocumentScanResult> {
    const server = getLocalServer()
    const endpoint = await server.ensureRunning()
    return this.invokeHttpWithEndpoint(endpoint, image, signal)
  }

  private async invokeHttp(image: ImageInput, signal: AbortSignal): Promise<DocumentScanResult> {
    return this.invokeHttpWithEndpoint(this.endpoint!, image, signal)
  }

  private async invokeHttpWithEndpoint(
    endpoint: string,
    image: ImageInput,
    signal: AbortSignal,
  ): Promise<DocumentScanResult> {
    const blob = await normalizeToBlob(image)
    const form = new FormData()
    form.append('image', blob, 'passport.jpg')

    const headers: Record<string, string> = {}
    if (this.apiKey) {
      headers['Authorization'] = `Bearer ${this.apiKey}`
    }

    const res = await fetch(`${endpoint}/scan`, {
      method: 'POST',
      body: form,
      headers,
      signal,
    })

    const data = await res.json()

    if (res.status === 400) {
      throw new Error(data.error || `Bad request: ${res.status}`)
    }

    if (res.status === 422 || res.ok) {
      return data as DocumentScanResult
    }

    throw new Error(data.error || `Server error: ${res.status}`)
  }

  private async invokeLambda(image: ImageInput, signal: AbortSignal): Promise<DocumentScanResult> {
    const { LambdaClient, InvokeCommand } = await import('@aws-sdk/client-lambda')

    const base64 = await normalizeToBase64(image)
    const client = new LambdaClient({})

    const command = new InvokeCommand({
      FunctionName: this.functionName,
      Payload: JSON.stringify({ image_base64: base64 }),
    })

    const abortHandler = () => client.destroy()
    signal.addEventListener('abort', abortHandler, { once: true })

    try {
      const response = await client.send(command)
      const payload = new TextDecoder().decode(response.Payload)
      const result = JSON.parse(payload)

      if (result.statusCode && result.body) {
        const body = JSON.parse(result.body)
        if (result.statusCode === 400) {
          throw new Error(body.error || `Bad request: ${result.statusCode}`)
        }
        return body as DocumentScanResult
      }

      return result as DocumentScanResult
    } finally {
      signal.removeEventListener('abort', abortHandler)
    }
  }
}

export const PassportOCR = DocumentOCR
