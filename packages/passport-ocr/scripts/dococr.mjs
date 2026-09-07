#!/usr/bin/env node
import { spawnSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const templates = resolve(dirname(fileURLToPath(import.meta.url)), '../hosting')
const targets = ['cloudrun', 'lambda', 'cloudflare', 'server']
const usage = `Usage:
  document-ocr init --target cloudrun|lambda|cloudflare|server [--directory DIR]
    [--name NAME] [--profile economy|warm] [--languages en,devanagari]
    [--project PROJECT] [--region REGION] [--image IMAGE_URI] [--domain DOMAIN]
    [--bucket BUCKET] [--prefix uploads/]
  document-ocr doctor [--directory DIR] [--endpoint URL] [--json]
  document-ocr deploy [--directory DIR] [--dry-run]

init writes dococr.json and source/templates; existing files are never replaced.
Credentials and API_TOKEN come from your environment, never dococr.json.
Run doctor before deploying; deploy executes the target's bundled wrapper.`

function parse(args) {
  const [command, ...rest] = args
  const options = {}
  const booleans = new Set(['dry-run', 'json', 'help'])
  const values = new Set(['target', 'directory', 'name', 'profile', 'languages', 'project', 'region', 'image', 'domain', 'bucket', 'prefix', 'endpoint'])
  for (let i = 0; i < rest.length; i++) {
    const token = rest[i]
    if (!token.startsWith('--')) throw new Error(`Unexpected argument: ${token}`)
    const key = token.slice(2)
    if (booleans.has(key)) options[key] = true
    else if (values.has(key) && rest[i + 1] && !rest[i + 1].startsWith('--')) options[key] = rest[++i]
    else throw new Error(`Unknown option or missing value: ${token}`)
  }
  return { command, options }
}

function validate(config) {
  if (!config || config.version !== 1 || !targets.includes(config.target)) throw new Error('Invalid dococr.json: version 1 and a supported target are required')
  if (!/^[a-z][a-z0-9-]{0,39}$/.test(config.name)) throw new Error('name must start with a lowercase letter and contain at most 40 lowercase letters, digits, or hyphens')
  if (!['economy', 'warm'].includes(config.profile)) throw new Error('profile must be economy or warm')
  if (!Array.isArray(config.languages) || config.languages.length < 1 || config.languages.length > 4
      || config.languages.some((language) => !['en', 'latin', 'devanagari', 'ka', 'ta', 'te'].includes(language))
      || new Set(config.languages).size !== config.languages.length) throw new Error('languages must list one to four unique supported OCR languages')
  const allowed = new Set(['version', 'target', 'name', 'profile', 'languages', 'project', 'region', 'image', 'domain', 'bucket', 'prefix', 'endpoint'])
  for (const key of Object.keys(config)) {
    if (!allowed.has(key)) throw new Error(`Unknown dococr.json field: ${key}. Keep credentials in environment variables.`)
    if (['project', 'region', 'image', 'domain', 'bucket', 'prefix', 'endpoint'].includes(key)
        && (typeof config[key] !== 'string' || !config[key].trim())) throw new Error(`${key} must be a non-empty string`)
  }
  return config
}

function environment(config, env) {
  const result = { ...env, DOCUMENT_OCR_NAME: config.name, DOCUMENT_OCR_PROFILE: config.profile, DOCUMENT_OCR_KYC_LANGS: config.languages.join(',') }
  const mapping = { project: 'GCP_PROJECT', image: 'IMAGE_URI', domain: 'DOMAIN', bucket: 'DOCUMENT_OCR_S3_BUCKET', prefix: 'DOCUMENT_OCR_S3_PREFIX' }
  for (const [key, variable] of Object.entries(mapping)) if (config[key]) result[variable] = config[key]
  if (config.region) result[config.target === 'lambda' ? 'AWS_REGION' : 'GCP_REGION'] = config.region
  return result
}

function invocation(config) {
  return config.target === 'cloudflare'
    ? { command: 'npm', args: ['--prefix', 'deploy/cloudflare', 'run', 'deploy'] }
    : { command: 'bash', args: [`deploy/${config.target}/deploy.sh`] }
}

function run(command, args, options) {
  const result = spawnSync(command, args, options)
  return { status: result.status ?? 1, error: result.error?.message }
}

/** Injectable command runner keeps CLI tests local and never deploys infrastructure. */
export async function main(args = process.argv.slice(2), dependencies = {}) {
  const log = dependencies.log ?? console.log
  const execute = dependencies.run ?? run
  const env = dependencies.env ?? process.env
  const parsed = parse(args)
  const { command, options } = parsed
  if (!command || command === '--help' || command === 'help' || options.help) { log(usage); return 0 }
  if (!['init', 'doctor', 'deploy'].includes(command)) throw new Error(`Unknown command: ${command}`)
  const acceptedOptions = {
    init: ['target', 'directory', 'name', 'profile', 'languages', 'project', 'region', 'image', 'domain', 'bucket', 'prefix'],
    doctor: ['directory', 'endpoint', 'json'],
    deploy: ['directory', 'dry-run'],
  }[command]
  for (const key of Object.keys(options)) {
    if (!acceptedOptions.includes(key)) throw new Error(`--${key} is not supported by ${command}`)
  }
  const cwd = resolve(dependencies.cwd ?? process.cwd(), options.directory ?? '.')
  const configFile = join(cwd, 'dococr.json')

  if (command === 'init') {
    const config = validate({
      version: 1, target: options.target, name: options.name ?? 'document-ocr', profile: options.profile ?? 'economy',
      languages: (options.languages ?? 'en').split(','),
      ...Object.fromEntries(['project', 'region', 'image', 'domain', 'bucket', 'prefix'].filter((key) => options[key]).map((key) => [key, options[key]])),
    })
    const source = dependencies.templates ?? templates
    if (!existsSync(join(source, `deploy/${config.target}/deploy.sh`))) throw new Error('Hosting templates are missing; install a built document-ocr package')
    const entries = readdirSync(source)
    const collisions = ['dococr.json', ...entries].filter((name) => existsSync(join(cwd, name)))
    if (collisions.length) throw new Error(`Refusing to overwrite existing paths: ${collisions.join(', ')}`)
    mkdirSync(cwd, { recursive: true })
    for (const name of entries) cpSync(join(source, name), join(cwd, name), { recursive: true, errorOnExist: true, force: false })
    writeFileSync(configFile, `${JSON.stringify(config, null, 2)}\n`, { flag: 'wx' })
    log(`Initialized ${config.target} in ${cwd}. Configure credentials, then run document-ocr doctor.`)
    return 0
  }

  if (!existsSync(configFile)) throw new Error('dococr.json is missing; run document-ocr init --target TARGET first')
  const config = validate(JSON.parse(readFileSync(configFile, 'utf8')))
  const effectiveEnv = environment(config, env)
  const selected = invocation(config)
  const wrapper = join(cwd, `deploy/${config.target}/deploy.sh`)
  if (!existsSync(wrapper)) throw new Error(`Missing deployment wrapper: deploy/${config.target}/deploy.sh`)
  if (command === 'deploy') {
    if (options['dry-run']) { log(JSON.stringify({ ...selected, cwd, target: config.target, name: config.name, profile: config.profile }, null, 2)); return 0 }
    const result = execute(selected.command, selected.args, { cwd, env: effectiveEnv, stdio: 'inherit', shell: false })
    if (result.error) throw new Error(result.error)
    return result.status ?? 1
  }

  const requirements = {
    cloudrun: ['bash', 'gcloud', 'python3'],
    lambda: ['bash', 'aws', 'sam', ...(effectiveEnv.IMAGE_URI ? [] : ['docker'])],
    cloudflare: ['bash', 'node', 'npm', ...(effectiveEnv.IMAGE_URI ? [] : ['docker'])],
    server: ['bash', 'docker'],
  }[config.target]
  const checks = requirements.map((tool) => {
    const result = execute(tool, ['--version'], { cwd, env: effectiveEnv, stdio: 'pipe', encoding: 'utf8', timeout: 10000, shell: false })
    return { check: `${tool} installed`, passed: result.status === 0 }
  })
  if (config.target === 'server') {
    const compose = execute('docker', ['compose', 'version'], { cwd, env: effectiveEnv, stdio: 'pipe', timeout: 10000, shell: false })
    checks.push({ check: 'Docker Compose installed', passed: compose.status === 0 })
    checks.push({ check: 'DOMAIN configured', passed: Boolean(effectiveEnv.DOMAIN) })
    checks.push({ check: 'API_TOKEN configured in environment', passed: Boolean(effectiveEnv.API_TOKEN) })
  }
  if (config.target === 'cloudrun') checks.push({ check: 'GCP_PROJECT configured', passed: Boolean(effectiveEnv.GCP_PROJECT) })
  if (!effectiveEnv.IMAGE_URI) checks.push({ check: 'Source and locked runtime bundled', passed: existsSync(join(cwd, 'core/pipeline.py')) && existsSync(join(cwd, 'requirements.lock')) })
  const endpoint = options.endpoint ?? config.endpoint
  if (endpoint) {
    const url = new URL(endpoint)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('endpoint must be an HTTP(S) URL without credentials')
    url.pathname = `${url.pathname.replace(/\/+$/, '')}/health`
    try {
      const response = await (dependencies.fetch ?? fetch)(url, { signal: AbortSignal.timeout(10000), headers: effectiveEnv.API_TOKEN ? { Authorization: `Bearer ${effectiveEnv.API_TOKEN}` } : {} })
      const health = await response.json()
      checks.push({ check: 'Endpoint healthy', passed: response.ok && health.status === 'ok' })
    } catch { checks.push({ check: 'Endpoint healthy', passed: false }) }
  }
  const passed = checks.every((check) => check.passed)
  if (options.json) log(JSON.stringify({ passed, target: config.target, checks }, null, 2))
  else for (const check of checks) log(`${check.passed ? 'OK' : 'FAIL'} ${check.check}`)
  return passed ? 0 : 1
}

if (process.argv[1] && existsSync(process.argv[1]) && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then((status) => { process.exitCode = status }).catch((error) => {
    console.error(`document-ocr: ${error.message}`)
    process.exitCode = 1
  })
}
