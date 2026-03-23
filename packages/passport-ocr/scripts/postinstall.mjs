#!/usr/bin/env node

/**
 * postinstall script for passport-ocr
 *
 * Sets up a Python virtual environment and installs dependencies
 * required for local passport OCR processing.
 *
 * Uses uv to install a compatible Python version (3.12) if the system
 * Python is too new or missing. PaddleOCR requires Python <= 3.13.
 *
 * Exits 0 even on failure — errors will surface on first scan() call.
 */

import { execSync } from 'node:child_process'
import { existsSync, writeFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const packageDir = join(__dirname, '..')
const pythonDir = join(packageDir, 'python')
const venvDir = join(packageDir, '.venv')
const markerFile = join(venvDir, '.setup-complete')

// PaddleOCR max supported Python version
const TARGET_PYTHON = '3.12'

function log(msg) {
  process.stderr.write(`[passport-ocr] ${msg}\n`)
}

function run(cmd, opts = {}) {
  log(`> ${cmd}`)
  return execSync(cmd, {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
    timeout: 600000, // 10 minutes (PaddleOCR install is large)
    ...opts,
  })
}

function hasUv() {
  try {
    const version = execSync('uv --version 2>&1', { encoding: 'utf-8', timeout: 10000 }).trim()
    log(`Found ${version}`)
    return true
  } catch {
    return false
  }
}

function findCompatiblePython() {
  /**
   * Find a Python that PaddleOCR supports (3.12 or 3.13).
   * Check versioned commands first, then generic ones.
   */
  const candidates = process.platform === 'win32'
    ? ['python3.12', 'python3.13', 'python3', 'python']
    : ['python3.12', 'python3.13', 'python3', 'python']

  for (const cmd of candidates) {
    try {
      const version = execSync(`${cmd} --version 2>&1`, { encoding: 'utf-8', timeout: 10000 }).trim()
      const match = version.match(/Python (\d+)\.(\d+)/)
      if (match) {
        const major = parseInt(match[1], 10)
        const minor = parseInt(match[2], 10)
        if (major === 3 && minor >= 12 && minor <= 13) {
          log(`Found compatible ${version} via "${cmd}"`)
          return cmd
        }
      }
    } catch { /* not found */ }
  }
  return null
}

async function main() {
  // Skip if already set up
  if (existsSync(markerFile)) {
    log('Python environment already set up.')
    return
  }

  if (process.env.PASSPORT_OCR_SKIP_PYTHON === '1') {
    log('Skipping Python setup (PASSPORT_OCR_SKIP_PYTHON=1)')
    return
  }

  if (!existsSync(pythonDir)) {
    log('Warning: python/ directory not found. Local mode will not work.')
    return
  }

  const uvAvailable = hasUv()

  // Strategy 1: Use uv to create venv with a pinned Python version
  // uv can auto-download Python 3.12 even if the system only has 3.14
  if (uvAvailable && !existsSync(venvDir)) {
    log(`Creating virtual environment with Python ${TARGET_PYTHON} via uv...`)
    try {
      run(`uv venv --python ${TARGET_PYTHON} "${venvDir}"`)
      log('Installing Python dependencies...')
      const venvPython = process.platform === 'win32'
        ? join(venvDir, 'Scripts', 'python.exe')
        : join(venvDir, 'bin', 'python')
      run(`uv pip install --python "${venvPython}" -e "${pythonDir}"`)
      writeFileSync(markerFile, new Date().toISOString())
      log('Setup complete.')
      return
    } catch (err) {
      log(`uv setup failed: ${err.message?.split('\n')[0]}`)
      log('Trying fallback...')
      // Clean up failed venv
      try { execSync(`rm -rf "${venvDir}"`, { timeout: 10000 }) } catch {}
    }
  }

  // Strategy 2: Use a compatible system Python directly
  const pythonCmd = findCompatiblePython()
  if (pythonCmd) {
    if (!existsSync(venvDir)) {
      log(`Creating virtual environment with ${pythonCmd}...`)
      try {
        run(`${pythonCmd} -m venv "${venvDir}"`)
      } catch (err) {
        log(`Warning: Failed to create venv: ${err.message?.split('\n')[0]}`)
        return
      }
    }

    const venvPython = process.platform === 'win32'
      ? join(venvDir, 'Scripts', 'python.exe')
      : join(venvDir, 'bin', 'python')

    if (!existsSync(venvPython)) {
      log(`Warning: venv python not found at ${venvPython}`)
      return
    }

    log('Installing Python dependencies...')
    try {
      if (uvAvailable) {
        run(`uv pip install --python "${venvPython}" -e "${pythonDir}"`)
      } else {
        run(`"${venvPython}" -m pip install --upgrade pip`)
        run(`"${venvPython}" -m pip install -e "${pythonDir}"`)
      }
    } catch (err) {
      log(`Warning: Failed to install dependencies: ${err.message?.split('\n')[0]}`)
      log('Retry with: npm rebuild passport-ocr')
      return
    }

    writeFileSync(markerFile, new Date().toISOString())
    log('Setup complete.')
    return
  }

  // Strategy 3: Nothing worked
  log('Warning: Could not set up Python environment.')
  log(`PaddleOCR requires Python 3.12-3.13. Your system Python may be too new (3.14+).`)
  if (!uvAvailable) {
    log('Install uv to auto-download a compatible Python:')
    log('  curl -LsSf https://astral.sh/uv/install.sh | sh')
  }
  log('Then retry: npm rebuild passport-ocr')
}

main().catch((err) => {
  log(`Warning: Setup failed: ${err.message}`)
  process.exit(0)
})
