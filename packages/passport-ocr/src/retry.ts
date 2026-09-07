import { HttpError, InputValidationError } from './errors'

export interface RetryOptions {
  retries: number
  timeoutMs: number
}

export function validateRetryOptions({ retries, timeoutMs }: RetryOptions): void {
  if (!Number.isInteger(retries) || retries < 0) {
    throw new RangeError('retries must be a non-negative integer')
  }
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > 2_147_483_647) {
    throw new RangeError('timeoutMs must be between 0 and 2147483647 milliseconds (exclusive of 0)')
  }
}

export async function withRetry<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  options: RetryOptions,
): Promise<T> {
  validateRetryOptions(options)
  const { retries, timeoutMs } = options
  let lastError: Error | undefined

  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController()
    let timeout: ReturnType<typeof setTimeout> | undefined
    const deadline = new Promise<never>((_, reject) => {
      timeout = setTimeout(() => {
        const error = new Error(`OCR request timed out after ${timeoutMs}ms`)
        error.name = 'TimeoutError'
        reject(error)
        controller.abort(error)
      }, timeoutMs)
    })

    try {
      return await Promise.race([fn(controller.signal), deadline])
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err))

      if (lastError instanceof InputValidationError || (lastError instanceof HttpError && !lastError.retryable)) {
        throw lastError
      }

    } finally {
      clearTimeout(timeout)
    }

    if (attempt < retries) {
      // Exponential backoff: 500ms, 1s, 2s...
      const delay = Math.min(500 * Math.pow(2, attempt), 5000)
      await new Promise((r) => setTimeout(r, delay))
    }
  }

  throw lastError ?? new Error('All retries exhausted')
}
