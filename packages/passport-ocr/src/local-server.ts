import { type ChildProcess, spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// Resolve package directory — works for both ESM and CJS builds
function resolvePackageDir(): string {
  // In ESM context, use import.meta.url
  // In CJS context, use __dirname
  try {
    // @ts-ignore — import.meta.url is only available in ESM
    if (typeof import.meta?.url === 'string') {
      // dist/index.js -> package root
      return join(dirname(fileURLToPath(import.meta.url)), '..')
    }
  } catch {
    // fallback
  }
  // CJS fallback: __dirname is dist/, go up one level
  if (typeof __dirname === 'string') {
    return join(__dirname, '..')
  }
  throw new Error('Cannot resolve passport-ocr package directory')
}

const HEALTH_POLL_INTERVAL_MS = 500
const HEALTH_TIMEOUT_MS = 120_000 // 120s for first-time model download

/**
 * Finds a free port by briefly binding to port 0.
 */
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

/**
 * Manages a local Python FastAPI server for passport OCR.
 *
 * Uses a module-level singleton so multiple PassportOCR instances
 * share a single server process.
 */
export class LocalServer {
  private process: ChildProcess | null = null
  private port: number = 0
  private ready: Promise<string> | null = null
  private stopped: boolean = false

  /**
   * Ensure the local Python server is running and return its endpoint URL.
   */
  async ensureRunning(): Promise<string> {
    // If already starting or running, return the existing promise
    if (this.ready) {
      return this.ready
    }

    this.stopped = false
    this.ready = this._start()

    // If start fails, clear the promise so we can retry
    this.ready.catch(() => {
      this.ready = null
    })

    return this.ready
  }

  private async _start(): Promise<string> {
    const packageDir = resolvePackageDir()
    const pythonDir = join(packageDir, 'python')
    const venvDir = join(packageDir, '.venv')

    // Check that setup was completed
    const markerFile = join(venvDir, '.setup-complete')
    if (!existsSync(markerFile)) {
      throw new Error(
        'passport-ocr: Python environment not set up. ' +
          'Run "npm rebuild passport-ocr" or ensure Python 3.12+ and uv are installed. ' +
          'Check that the postinstall script ran successfully.',
      )
    }

    // Find the venv python executable
    const isWindows = process.platform === 'win32'
    const pythonExe = isWindows
      ? join(venvDir, 'Scripts', 'python.exe')
      : join(venvDir, 'bin', 'python')

    if (!existsSync(pythonExe)) {
      throw new Error(
        `passport-ocr: Python executable not found at ${pythonExe}. ` +
          'Run "npm rebuild passport-ocr" to re-create the virtual environment.',
      )
    }

    // Find a free port
    this.port = await findFreePort()
    const endpoint = `http://127.0.0.1:${this.port}`

    // Spawn the uvicorn server
    const args = [
      '-m',
      'uvicorn',
      'server:app',
      '--host',
      '127.0.0.1',
      '--port',
      String(this.port),
      '--log-level',
      'warning',
    ]

    this.process = spawn(pythonExe, args, {
      cwd: pythonDir,
      env: {
        ...process.env,
        PYTHONPATH: pythonDir,
        // Suppress paddle logging noise
        GLOG_minloglevel: '2',
      },
      stdio: ['pipe', 'pipe', 'pipe'],
      // Detach on Windows to avoid blocking
      detached: isWindows,
    })

    // Collect stderr for error reporting
    let stderr = ''
    this.process.stderr?.on('data', (chunk: Buffer) => {
      stderr += chunk.toString()
      // Keep only the last 2KB for error messages
      if (stderr.length > 2048) {
        stderr = stderr.slice(-2048)
      }
    })

    // Handle unexpected exit
    const exitPromise = new Promise<never>((_, reject) => {
      this.process!.on('exit', (code, signal) => {
        if (!this.stopped) {
          this.ready = null
          this.process = null
          reject(
            new Error(
              `passport-ocr: Python server exited unexpectedly (code=${code}, signal=${signal}).\n${stderr}`,
            ),
          )
        }
      })
    })

    // Register cleanup handler
    const cleanup = () => {
      this.stop()
    }
    process.on('exit', cleanup)
    process.on('SIGINT', cleanup)
    process.on('SIGTERM', cleanup)

    // Wait for the server to be ready
    const healthPromise = this._waitForHealth(endpoint)

    // Race between health check succeeding and process dying
    const result = await Promise.race([healthPromise, exitPromise])
    return result
  }

  private async _waitForHealth(endpoint: string): Promise<string> {
    const healthUrl = `${endpoint}/health`
    const startTime = Date.now()

    while (Date.now() - startTime < HEALTH_TIMEOUT_MS) {
      try {
        const res = await fetch(healthUrl, {
          signal: AbortSignal.timeout(2000),
        })
        if (res.ok) {
          return endpoint
        }
      } catch {
        // Server not ready yet, keep polling
      }

      await new Promise((r) => setTimeout(r, HEALTH_POLL_INTERVAL_MS))
    }

    // Timed out
    this.stop()
    throw new Error(
      `passport-ocr: Python server did not become ready within ${HEALTH_TIMEOUT_MS / 1000}s. ` +
        'This might happen on first run while models are being downloaded.',
    )
  }

  /**
   * Stop the local Python server if running.
   */
  async stop(): Promise<void> {
    this.stopped = true

    if (this.process) {
      const proc = this.process
      this.process = null
      this.ready = null

      try {
        // Try graceful shutdown first
        proc.kill('SIGTERM')

        // Force kill after 5s
        const forceKill = setTimeout(() => {
          try {
            proc.kill('SIGKILL')
          } catch {
            // already dead
          }
        }, 5000)

        // Wait for exit
        await new Promise<void>((resolve) => {
          proc.on('exit', () => {
            clearTimeout(forceKill)
            resolve()
          })
          // Resolve anyway after force kill timeout
          setTimeout(resolve, 6000)
        })
      } catch {
        // Process already dead
      }
    }
  }
}

// Module-level singleton — shared across all PassportOCR instances
let _instance: LocalServer | null = null

export function getLocalServer(): LocalServer {
  if (!_instance) {
    _instance = new LocalServer()
  }
  return _instance
}
