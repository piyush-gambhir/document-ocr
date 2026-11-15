import { type ChildProcess, spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'


function resolvePackageDir(): string {


  try {
    if (typeof import.meta?.url === 'string') {

      return join(dirname(fileURLToPath(import.meta.url)), '..')
    }
  } catch {

  }

  if (typeof __dirname === 'string') {
    return join(__dirname, '..')
  }
  throw new Error('Cannot resolve document-ocr package directory')
}

const HEALTH_POLL_INTERVAL_MS = 500
const HEALTH_TIMEOUT_MS = 120_000




function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer()
    srv.listen(0, '127.0.0.1', () => {
      const addr = srv.address()
      if (addr && typeof addr === 'object') {
        const port = addr.port
        srv.close(() => resolve(port))
      } else {
        srv.close(() => reject(new Error('Could not determine free port')))
      }
    })
    srv.on('error', reject)
  })
}







export class LocalServer {
  private process: ChildProcess | null = null
  private ready: Promise<string> | null = null
  private startupAbort: AbortController | null = null
  private cleanupHandler: (() => void) | null = null




  async ensureRunning(): Promise<string> {

    if (this.ready) {
      return this.ready
    }

    const controller = new AbortController()
    this.startupAbort = controller
    const ready = this._start(controller)
    this.ready = ready


    ready.catch(() => {
      if (this.ready === ready) this.ready = null
    })

    return ready
  }

  private async _start(controller: AbortController): Promise<string> {
    const packageDir = resolvePackageDir()
    const pythonDir = join(packageDir, 'python')
    const venvDir = join(packageDir, '.venv')


    const markerFile = join(venvDir, '.setup-complete')
    if (!existsSync(markerFile)) {
      throw new Error(
        'document-ocr: Python environment not set up. ' +
          'Run "npm rebuild document-ocr" or ensure Python 3.14 and uv are installed. ' +
          'Check that the postinstall script ran successfully.',
      )
    }


    const isWindows = process.platform === 'win32'
    const pythonExe = isWindows
      ? join(venvDir, 'Scripts', 'python.exe')
      : join(venvDir, 'bin', 'python')

    if (!existsSync(pythonExe)) {
      throw new Error(
        `document-ocr: Python executable not found at ${pythonExe}. ` +
          'Run "npm rebuild document-ocr" to re-create the virtual environment.',
      )
    }


    const port = await findFreePort()
    controller.signal.throwIfAborted()
    const endpoint = `http://127.0.0.1:${port}`


    const args = [
      '-m',
      'uvicorn',
      'server:app',
      '--host',
      '127.0.0.1',
      '--port',
      String(port),
      '--log-level',
      'warning',
    ]

    const child = spawn(pythonExe, args, {
      cwd: pythonDir,
      env: {
        ...process.env,
        PYTHONPATH: pythonDir,
        PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK: 'True',

        GLOG_minloglevel: '2',
      },
      stdio: ['ignore', 'pipe', 'pipe'],

      detached: isWindows,
    })
    this.process = child


    let processLogs = ''
    const appendLogs = (chunk: Buffer) => {
      processLogs += chunk.toString()
      if (processLogs.length > 4096) {
        processLogs = processLogs.slice(-4096)
      }
    }

    child.stdout?.on('data', appendLogs)
    child.stderr?.on('data', appendLogs)

    const cleanup = () => child.kill('SIGTERM')
    this.cleanupHandler = cleanup
    process.once('exit', cleanup)


    const exitPromise = new Promise<never>((_, reject) => {
      const failed = (error: Error) => {
        process.removeListener('exit', cleanup)
        if (this.cleanupHandler === cleanup) this.cleanupHandler = null
        if (this.process === child) {
          this.ready = null
          this.process = null
        }
        controller.abort(error)
        reject(error)
      }
      child.once('error', failed)
      child.once('exit', (code, signal) => failed(new Error(
        `document-ocr: Python server exited (code=${code}, signal=${signal}).\n${processLogs}`,
      )))
    })

    try {
      return await Promise.race([this._waitForReady(endpoint, controller.signal), exitPromise])
    } catch (error) {
      if (this.process === child) await this.stop()
      throw error
    } finally {
      if (controller.signal.aborted) process.removeListener('exit', cleanup)
    }
  }

  private async _waitForReady(endpoint: string, signal?: AbortSignal): Promise<string> {
    const readinessUrl = `${endpoint}/ready`
    const startTime = Date.now()

    while (Date.now() - startTime < HEALTH_TIMEOUT_MS) {
      signal?.throwIfAborted()
      let terminalFailure: string | null = null
      const probeController = new AbortController()
      const cancelProbe = () => probeController.abort(signal?.reason)
      signal?.addEventListener('abort', cancelProbe, { once: true })
      const timeout = setTimeout(() => probeController.abort(), 2000)
      try {
        const res = await fetch(readinessUrl, {
          signal: probeController.signal,
        })
        const body = (await res.json().catch(() => null)) as {
          status?: unknown
          error?: unknown
        } | null
        signal?.throwIfAborted()
        if (res.ok && body?.status === 'ready') {
          return endpoint
        }
        if (body?.status === 'model_init_failed') {
          const detail =
            typeof body.error === 'string'
              ? body.error.replace(/\s+/g, ' ').slice(0, 500)
              : 'configured OCR model initialization failed'
          terminalFailure = detail
        }
      } catch {
        signal?.throwIfAborted()

      } finally {
        clearTimeout(timeout)
        signal?.removeEventListener('abort', cancelProbe)
      }

      if (terminalFailure) {
        throw new Error(
          `document-ocr: OCR model initialization failed: ${terminalFailure}`,
        )
      }

      await delay(HEALTH_POLL_INTERVAL_MS, undefined, { signal })
    }


    throw new Error(
      `document-ocr: Python server did not become ready within ${HEALTH_TIMEOUT_MS / 1000}s. ` +
        'This might happen on first run while models are being downloaded.',
    )
  }




  async stop(): Promise<void> {
    if (this.cleanupHandler) {
      process.removeListener('exit', this.cleanupHandler)
      this.cleanupHandler = null
    }
    this.startupAbort?.abort(new Error('document-ocr: local server stopped'))
    this.startupAbort = null
    this.ready = null

    if (this.process) {
      const proc = this.process
      this.process = null
      if (proc.exitCode !== null || proc.signalCode !== null) return
      await new Promise<void>((resolve) => {
        const done = () => {
          clearTimeout(forceKill)
          clearTimeout(deadline)
          proc.removeListener('exit', done)
          proc.removeListener('error', done)
          resolve()
        }
        const forceKill = setTimeout(() => {
          try { proc.kill('SIGKILL') } catch { done() }
        }, 5000)
        const deadline = setTimeout(done, 6000)
        proc.once('exit', done)
        proc.once('error', done)
        try {
          if (!proc.kill('SIGTERM')) done()
        } catch {
          done()
        }
      })
    }
  }
}


let _instance: LocalServer | null = null

export function getLocalServer(): LocalServer {
  if (!_instance) {
    _instance = new LocalServer()
  }
  return _instance
}
