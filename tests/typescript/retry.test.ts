import { afterEach, describe, expect, it, vi } from 'vitest'
import { withRetry } from '../../packages/passport-ocr/src/retry'

describe('retry deadlines', () => {
  afterEach(() => vi.useRealTimers())

  it('times out even when an operation never responds to cancellation', async () => {
    vi.useFakeTimers()
    let signal: AbortSignal | undefined
    const result = withRetry((attemptSignal) => {
      signal = attemptSignal
      return new Promise(() => {})
    }, { retries: 0, timeoutMs: 100 })
    const rejection = expect(result).rejects.toMatchObject({ name: 'TimeoutError' })

    await vi.advanceTimersByTimeAsync(100)
    await rejection
    expect(signal?.aborted).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('clears the deadline after a successful attempt', async () => {
    vi.useFakeTimers()
    await expect(withRetry(async () => 'done', { retries: 2, timeoutMs: 100 })).resolves.toBe('done')
    expect(vi.getTimerCount()).toBe(0)
  })
})
