export interface RetryOptions {
  retries: number
  timeoutMs: number
}

export async function withRetry<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  options: RetryOptions,
): Promise<T> {
  const { retries, timeoutMs } = options
  let lastError: Error | undefined

  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), timeoutMs)

    try {
      const result = await fn(controller.signal)
      clearTimeout(timeout)
      return result
    } catch (err) {
      clearTimeout(timeout)
      lastError = err instanceof Error ? err : new Error(String(err))

      // Don't retry on client errors (4xx)
      if (lastError.message.includes('400') || lastError.message.includes('422')) {
        throw lastError
      }

      if (attempt < retries) {
        // Exponential backoff: 500ms, 1s, 2s...
        const delay = Math.min(500 * Math.pow(2, attempt), 5000)
        await new Promise((r) => setTimeout(r, delay))
      }
    }
  }

  throw lastError ?? new Error('All retries exhausted')
}
