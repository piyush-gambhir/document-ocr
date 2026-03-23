#!/usr/bin/env node

/**
 * postinstall script for passport-ocr
 *
 * Sets up a Python virtual environment and installs dependencies
 * required for local passport OCR processing.
 *
 * Exits 0 even on failure — errors will surface on first scan() call.
 */

import { execSync, execFileSync } from 'node:child_process'
import { existsSync, writeFileSync, mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const packageDir = join(__dirname, '..')
const pythonDir = join(packageDir, 'python')
const venvDir = join(packageDir, '.venv')
const markerFile = join(venvDir, '.setup-complete')

function log(msg) {
  process.stderr.write(`[passport-ocr] ${msg}\n`)
}

function findPython() {
  const candidates = process.platform === 'win32'
    ? ['python3', 'python', 'py -3']
    : ['python3', 'python']

  for (const cmd of candidates) {
    try {
      const version = execSync(`${cmd} --version 2>&1`, {
        encoding: 'utf-8',
        timeout: 10000,
      }).trim()

      // Parse version — need 3.12+
      const match = version.match(/Python (\d+)\.(\d+)/)
      if (match) {
        const major = parseInt(match[1], 10)
        const minor = parseInt(match[2], 10)
        if (major === 3 && minor >= 12) {
          log(`Found ${version} via "${cmd}"`)
          return cmd
        }
        log(`${version} found but need Python 3.12+ (skipping)`)
      }
    } catch {
      // command not found, try next
    }
  }

  return null
}

function findUv() {
  try {
    const version = execSync('uv --version 2>&1', {
      encoding: 'utf-8',
      timeout: 10000,
    }).trim()
    log(`Found ${version}`)
    return true
  } catch {
    return false
  }
}

function run(cmd, opts = {}) {
  log(`> ${cmd}`)
  execSync(cmd, {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
    timeout: 300000, // 5 minutes
    ...opts,
  })
}

async function main() {
  // Skip if already set up
  if (existsSync(markerFile)) {
    log('Python environment already set up (found .venv/.setup-complete)')
    return
  }

  // Skip if explicitly opted out
  if (process.env.PASSPORT_OCR_SKIP_PYTHON === '1') {
    log('Skipping Python setup (PASSPORT_OCR_SKIP_PYTHON=1)')
    return
  }

  // Check that python/ directory exists (it should be bundled)
  if (!existsSync(pythonDir)) {
    log('Warning: python/ directory not found in package. Local mode will not work.')
    return
  }

  // 1. Find Python 3.12+
  const pythonCmd = findPython()
  if (!pythonCmd) {
    log('Warning: Python 3.12+ not found. Local mode requires Python 3.12+.')
    log('Install Python 3.12+ and re-run: npm rebuild passport-ocr')
    return
  }

  // 2. Find or check for uv
  const hasUv = findUv()
  if (!hasUv) {
    log('Warning: uv not found. Install it for faster setup:')
    log('  curl -LsSf https://astral.sh/uv/install.sh | sh')
    log('Falling back to pip...')
  }

  // 3. Create venv
  if (!existsSync(venvDir)) {
    log('Creating virtual environment...')
    try {
      run(`${pythonCmd} -m venv "${venvDir}"`)
    } catch (err) {
      log(`Warning: Failed to create venv: ${err.message}`)
      return
    }
  }

  // Determine venv python path
  const venvPython = process.platform === 'win32'
    ? join(venvDir, 'Scripts', 'python.exe')
    : join(venvDir, 'bin', 'python')

  if (!existsSync(venvPython)) {
    log(`Warning: venv python not found at ${venvPython}`)
    return
  }

  // 4. Install dependencies
  log('Installing Python dependencies (this may take a few minutes on first install)...')
  try {
    if (hasUv) {
      // Use uv for fast installs
      run(`uv pip install --python "${venvPython}" -e "${pythonDir}"`)
    } else {
      // Fallback to pip
      run(`"${venvPython}" -m pip install --upgrade pip`)
      run(`"${venvPython}" -m pip install -e "${pythonDir}"`)
    }
  } catch (err) {
    log(`Warning: Failed to install Python dependencies: ${err.message}`)
    log('You can retry later: npm rebuild passport-ocr')
    return
  }

  // 5. Mark as complete
  try {
    writeFileSync(markerFile, new Date().toISOString())
    log('Python environment setup complete.')
  } catch (err) {
    log(`Warning: Could not write marker file: ${err.message}`)
  }
}

main().catch((err) => {
  log(`Warning: Setup failed: ${err.message}`)
  // Always exit 0 — don't block npm install
  process.exit(0)
})
