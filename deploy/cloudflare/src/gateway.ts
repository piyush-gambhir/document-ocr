import { timingSafeEqual } from 'node:crypto'

export async function authorized(request: Request, token: string | undefined): Promise<boolean> {
  if (!token) return false
  const encoder = new TextEncoder()
  const [provided, expected] = await Promise.all([
    crypto.subtle.digest('SHA-256', encoder.encode(request.headers.get('Authorization') ?? '')),
    crypto.subtle.digest('SHA-256', encoder.encode(`Bearer ${token}`)),
  ])
  return timingSafeEqual(new Uint8Array(provided), new Uint8Array(expected))
}

export function instanceCount(value: string): number {
  const count = Number(value)
  if (!Number.isInteger(count) || count < 1 || count > 100) {
    throw new Error('CONTAINER_INSTANCES must be an integer from 1 to 100')
  }
  return count
}

/** Keep uploads and results streaming; only the container decodes document bytes. */
export async function gateway(
  request: Request,
  token: string | undefined,
  forward: (request: Request) => Promise<Response>,
): Promise<Response> {
  if (!token) return Response.json({ error: 'AUTH_NOT_CONFIGURED' }, { status: 503 })
  // The review shell contains no document data and accepts the bearer token in
  // its UI. Browser navigation cannot supply that header before the UI loads.
  const reviewShell = request.method === 'GET' && new URL(request.url).pathname === '/review'
  if (!reviewShell && !await authorized(request, token)) {
    return Response.json({ error: 'UNAUTHORIZED' }, { status: 401, headers: { 'WWW-Authenticate': 'Bearer' } })
  }
  try {
    const response = await forward(request)
    const headers = new Headers(response.headers)
    headers.set('Cache-Control', 'no-store')
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers })
  } catch {
    return Response.json({ error: 'OCR_CONTAINER_UNAVAILABLE' }, { status: 503, headers: { 'Cache-Control': 'no-store' } })
  }
}
