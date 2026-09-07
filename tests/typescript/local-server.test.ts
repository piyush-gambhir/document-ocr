import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'
import { LocalServer } from '../../packages/passport-ocr/src/local-server'

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }))
vi.mock('node:child_process', () => ({ spawn }))
vi.mock('node:fs', async (importOriginal) => ({
  ...await importOriginal<typeof import('node:fs')>(),
  existsSync: () => true,
}))

function childProcess() {
  return Object.assign(new EventEmitter(), {
    stdout: new PassThrough(),
    stderr: new PassThrough(),
    exitCode: null as number | null,
    signalCode: null as string | null,
    kill: vi.fn(function (this: EventEmitter & { signalCode: string | null }, signal: string) {
      this.signalCode = signal
      queueMicrotask(() => this.emit('exit', null, signal))
      return true
    }),
  })
}

describe('LocalServer lifecycle', () => {
  let server: LocalServer
  let child: ReturnType<typeof childProcess>
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    child = childProcess()
    spawn.mockReturnValue(child)
    fetchMock = vi.fn().mockImplementation(async () => Response.json({ status: 'ready' }))
    vi.stubGlobal('fetch', fetchMock)
    server = new LocalServer()
  })

  afterEach(async () => {
    await server.stop()
    vi.restoreAllMocks()
    vi.clearAllMocks()
    vi.unstubAllGlobals()
  })

  it('shares startup across concurrent calls and waits for model readiness', async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ status: 'loading' }, { status: 503 }))

    const [first, second] = await Promise.all([server.ensureRunning(), server.ensureRunning()])

    expect(first).toBe(second)
    expect(spawn).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock).toHaveBeenLastCalledWith(`${first}/ready`, expect.any(Object))
  })

  it('stops the child and rejects when model initialization fails', async () => {
    fetchMock.mockResolvedValueOnce(Response.json({
      status: 'model_init_failed', error: 'MODEL_INIT_FAILED: unavailable model',
    }, { status: 503 }))

    await expect(server.ensureRunning()).rejects.toThrow('MODEL_INIT_FAILED: unavailable model')

    expect(child.kill).toHaveBeenCalledWith('SIGTERM')
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('removes process cleanup listeners after stopping without intercepting host signals', async () => {
    const exits = process.listenerCount('exit')
    const sigints = process.listenerCount('SIGINT')
    const sigterms = process.listenerCount('SIGTERM')
    await server.ensureRunning()
    expect(process.listenerCount('exit')).toBe(exits + 1)

    await server.stop()

    expect(process.listenerCount('exit')).toBe(exits)
    expect(process.listenerCount('SIGINT')).toBe(sigints)
    expect(process.listenerCount('SIGTERM')).toBe(sigterms)
    expect(child.kill).toHaveBeenCalledOnce()
  })

  it('handles spawn errors and allows the next startup to succeed', async () => {
    spawn.mockImplementationOnce(() => {
      queueMicrotask(() => child.emit('error', new Error('spawn ENOENT')))
      return child
    })

    await expect(server.ensureRunning()).rejects.toThrow('spawn ENOENT')
    child = childProcess()
    spawn.mockReturnValue(child)

    await expect(server.ensureRunning()).resolves.toMatch(/^http:\/\/127\.0\.0\.1:/)
    expect(spawn).toHaveBeenCalledTimes(2)
  })

  it('cancels a pending readiness request when the child exits', async () => {
    let probeSignal: AbortSignal | undefined
    let started!: () => void
    const probing = new Promise<void>((resolve) => { started = resolve })
    fetchMock.mockImplementationOnce((_url, { signal }: { signal: AbortSignal }) => {
      probeSignal = signal
      started()
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }))
    })
    const startup = server.ensureRunning()
    const rejection = expect(startup).rejects.toThrow('Python server exited')
    await probing

    child.emit('exit', 1, null)

    await rejection
    expect(probeSignal?.aborted).toBe(true)
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('does not spawn a process if stopped while selecting a port', async () => {
    const startup = server.ensureRunning()
    const rejection = expect(startup).rejects.toThrow('local server stopped')

    await server.stop()
    await rejection

    expect(spawn).not.toHaveBeenCalled()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
