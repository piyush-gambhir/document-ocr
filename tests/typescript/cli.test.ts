import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { main } from '../../packages/passport-ocr/scripts/dococr.mjs'

let root: string
let source: string
let cwd: string
beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'dococr-cli-test-'))
  source = join(root, 'templates')
  cwd = join(root, 'project with spaces')
  mkdirSync(join(source, 'core'), { recursive: true })
  writeFileSync(join(source, 'core/pipeline.py'), '# synthetic source\n')
  writeFileSync(join(source, 'requirements.lock'), '# synthetic lock\n')
  for (const target of ['cloudrun', 'lambda', 'cloudflare', 'server']) {
    mkdirSync(join(source, 'deploy', target), { recursive: true })
    writeFileSync(join(source, 'deploy', target, 'deploy.sh'), '# no deployment in tests\n')
  }
})
afterEach(() => rmSync(root, { recursive: true, force: true }))
const dependencies = () => ({ cwd, templates: source, env: {}, log: vi.fn(), run: vi.fn(() => ({ status: 0 })) })

describe('hosting CLI', () => {
  it.each(['cloudrun', 'lambda', 'cloudflare', 'server'])('scaffolds a %s project without storing credentials', async (target) => {
    const deps = { ...dependencies(), env: { API_TOKEN: 'synthetic-secret' } }
    expect(await main(['init', '--target', target, '--name', 'example'], deps)).toBe(0)
    const raw = readFileSync(join(cwd, 'dococr.json'), 'utf8')
    expect(JSON.parse(raw)).toMatchObject({ version: 1, target, name: 'example', profile: 'economy', languages: ['en'] })
    expect(raw).not.toContain('synthetic-secret')
    expect(existsSync(join(cwd, 'core/pipeline.py'))).toBe(true)
    expect(existsSync(join(cwd, `deploy/${target}/deploy.sh`))).toBe(true)
    expect(deps.run).not.toHaveBeenCalled()
  })

  it('refuses overwrite before writing any templates', async () => {
    mkdirSync(cwd)
    writeFileSync(join(cwd, 'requirements.lock'), 'keep me')
    await expect(main(['init', '--target', 'server'], dependencies())).rejects.toThrow('Refusing to overwrite')
    expect(readFileSync(join(cwd, 'requirements.lock'), 'utf8')).toBe('keep me')
    expect(existsSync(join(cwd, 'core'))).toBe(false)
    expect(existsSync(join(cwd, 'dococr.json'))).toBe(false)
  })

  it('rejects malformed targets and names before filesystem writes', async () => {
    await expect(main(['init', '--target', '../../escape'], dependencies())).rejects.toThrow('supported target')
    await expect(main(['init', '--target', 'server', '--name', 'ocr; touch injected'], dependencies())).rejects.toThrow('name must')
    expect(existsSync(cwd)).toBe(false)
  })

  it('dry-run emits the chosen command without deployment or secret output', async () => {
    const deps = { ...dependencies(), env: { API_TOKEN: 'synthetic-secret' } }
    await main(['init', '--target', 'cloudrun', '--project', 'synthetic-project'], deps)
    deps.log.mockClear()
    expect(await main(['deploy', '--dry-run'], deps)).toBe(0)
    expect(JSON.parse(deps.log.mock.calls[0][0])).toMatchObject({ command: 'bash', args: ['deploy/cloudrun/deploy.sh'], cwd })
    expect(deps.run).not.toHaveBeenCalled()
    expect(JSON.stringify(deps.log.mock.calls)).not.toContain('synthetic-secret')
    await expect(main(['deploy', '--target', 'lambda'], deps)).rejects.toThrow('--target is not supported by deploy')
  })

  it('executes deployment using argv and environment without a shell command string', async () => {
    const deps = { ...dependencies(), env: { API_TOKEN: 'synthetic-secret' } }
    await main(['init', '--target', 'server', '--domain', 'ocr.example', '--profile', 'warm'], deps)
    deps.run.mockReturnValue({ status: 7 })
    expect(await main(['deploy'], deps)).toBe(7)
    expect(deps.run).toHaveBeenCalledWith('bash', ['deploy/server/deploy.sh'], expect.objectContaining({
      cwd, shell: false, env: expect.objectContaining({ API_TOKEN: 'synthetic-secret', DOMAIN: 'ocr.example', DOCUMENT_OCR_PROFILE: 'warm' }),
    }))
  })

  it('diagnoses missing commands/config without deploying', async () => {
    const deps = dependencies()
    await main(['init', '--target', 'cloudrun'], deps)
    deps.run.mockImplementation((command) => ({ status: command === 'gcloud' ? 1 : 0 }))
    deps.log.mockClear()
    expect(await main(['doctor', '--json'], deps)).toBe(1)
    const report = JSON.parse(deps.log.mock.calls[0][0])
    expect(report.checks).toContainEqual({ check: 'gcloud installed', passed: false })
    expect(report.checks).toContainEqual({ check: 'GCP_PROJECT configured', passed: false })
    expect(deps.run.mock.calls.every((call) => call[1][0] === '--version')).toBe(true)
  })

  it('checks an optional health endpoint without logging credentials', async () => {
    const deps = { ...dependencies(), env: { API_TOKEN: 'synthetic-secret' }, fetch: vi.fn().mockResolvedValue(new Response('{"status":"ok"}')) }
    await main(['init', '--target', 'server', '--domain', 'ocr.example'], deps)
    expect(await main(['doctor', '--endpoint', 'https://ocr.example/base', '--json'], deps)).toBe(0)
    expect(deps.fetch.mock.calls[0][0].href).toBe('https://ocr.example/base/health')
    expect(deps.fetch.mock.calls[0][1].headers).toEqual({ Authorization: 'Bearer synthetic-secret' })
    expect(JSON.stringify(deps.log.mock.calls)).not.toContain('synthetic-secret')
  })

  it('fails closed on unknown config fields rather than persisting secrets', async () => {
    const deps = dependencies()
    await main(['init', '--target', 'server'], deps)
    const file = join(cwd, 'dococr.json')
    writeFileSync(file, JSON.stringify({ ...JSON.parse(readFileSync(file, 'utf8')), apiToken: 'synthetic-secret' }))
    await expect(main(['deploy'], deps)).rejects.toThrow('Keep credentials in environment')
    expect(deps.run).not.toHaveBeenCalled()
  })
})
