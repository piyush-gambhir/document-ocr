/** Bundle only canonical source/templates, never local credentials or build output. */
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, lstatSync, writeFileSync } from 'node:fs'
import { dirname, extname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const packageDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repo = resolve(packageDir, '../..')
const destination = join(packageDir, 'hosting')
const extensions = new Set(['.py', '.html', '.toml', '.yaml', '.yml', '.json', '.jsonc', '.ts', '.js', '.mjs', '.sh', '.tf', '.hcl', '.md'])
const names = new Set(['Dockerfile', 'Dockerfile.lambda', 'Caddyfile', 'requirements.lock', 'terraform.tfvars.example', 'LICENSE', '.dockerignore', '.gitignore'])
const excluded = new Set(['node_modules', '__pycache__', '.terraform', '.wrangler', '.aws-sam', 'dist'])

function allowed(source) {
  const name = source.split('/').at(-1)
  if (excluded.has(name) || name.startsWith('.env')) return false
  const details = lstatSync(source)
  if (details.isSymbolicLink()) return false
  if (details.isDirectory()) return !name.startsWith('.')
  return names.has(name) || (!name.startsWith('.') && extensions.has(extname(name)))
}

rmSync(destination, { recursive: true, force: true })
mkdirSync(destination, { recursive: true })
for (const name of ['core', 'deploy', 'infra']) {
  if (existsSync(join(repo, name))) cpSync(join(repo, name), join(destination, name), { recursive: true, filter: allowed })
}
for (const name of ['pyproject.toml', 'requirements.lock', 'README.md', 'HOSTING.md', 'FEATURES.md', 'LICENSE', '.dockerignore', '.gcloudignore']) {
  if (existsSync(join(repo, name))) cpSync(join(repo, name), join(destination, name))
}
// A scaffolding build context must never upload a developer's credentials or data.
if (!existsSync(join(destination, '.dockerignore'))) {
  writeFileSync(join(destination, '.dockerignore'), '**\n!core/\n!core/**\n!deploy/\n!deploy/docker/\n!deploy/docker/server.py\n!deploy/lambda/\n!deploy/lambda/handler.py\n!requirements.lock\n**/__pycache__\n')
}
writeFileSync(join(destination, '.gitignore'), '.env*\n*.pem\n*.key\n*.tfvars\n*.tfstate*\n.venv/\n**/node_modules/\n**/__pycache__/\n**/.terraform/\n**/.wrangler/\n**/.aws-sam/\nbenchmark-data/\nsample-passports/\n')
console.log(`[sync-hosting] Bundled ${readdirSync(destination).length} source/template entries`)
