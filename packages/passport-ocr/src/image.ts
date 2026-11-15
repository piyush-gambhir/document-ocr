import type { ImageInput } from './types'
import { HttpError, InputValidationError } from './errors'

function isHttpUrl(input: string): boolean {
  return /^https?:\/\//i.test(input)
}

async function fetchImage(url: string, signal?: AbortSignal): Promise<Response> {
  const res = await fetch(url, { signal })
  if (!res.ok) {
    await res.body?.cancel()
    throw new HttpError(res.status, `Failed to fetch image from URL: ${res.status}`)
  }
  return res
}




export async function normalizeToBase64(input: ImageInput, signal?: AbortSignal): Promise<string> {

  if (typeof input === 'string' && !isHttpUrl(input)) {
    validateBase64(input)
    return input
  }


  if (typeof input === 'string' && isHttpUrl(input)) {
    const res = await fetchImage(input, signal)
    const buf = await res.arrayBuffer()
    return arrayBufferToBase64(buf)
  }


  if (typeof Buffer !== 'undefined' && Buffer.isBuffer(input)) {
    return input.toString('base64')
  }


  if (input instanceof ArrayBuffer) {
    return arrayBufferToBase64(input)
  }


  if (typeof Blob !== 'undefined' && input instanceof Blob) {
    const buf = await input.arrayBuffer()
    return arrayBufferToBase64(buf)
  }

  throw new InputValidationError('Unsupported image input type')
}




export async function normalizeToBlob(input: ImageInput, signal?: AbortSignal): Promise<Blob> {

  if (typeof Blob !== 'undefined' && input instanceof Blob) {
    if (input.type.startsWith('image/') || input.type === 'application/pdf') return input
    const header = new Uint8Array(await input.slice(0, 16).arrayBuffer())
    return new Blob([input], { type: mediaType(header) })
  }






  if (typeof Buffer !== 'undefined' && Buffer.isBuffer(input)) {
    const copy = new Uint8Array(input)
    return new Blob([copy], { type: mediaType(copy) })
  }


  if (input instanceof ArrayBuffer) {
    return new Blob([input], { type: mediaType(new Uint8Array(input)) })
  }


  if (typeof input === 'string' && isHttpUrl(input)) {
    const res = await fetchImage(input, signal)
    return normalizeToBlob(await res.blob(), signal)
  }


  if (typeof input === 'string') {
    validateBase64(input)
    const binary = atob(input)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i)
    }
    return new Blob([bytes], { type: mediaType(bytes) })
  }

  throw new InputValidationError('Unsupported image input type')
}

function validateBase64(value: string): void {
  if (!value || !/^[A-Za-z0-9+/]*={0,2}$/.test(value) || value.length % 4 === 1
      || (value.includes('=') && value.length % 4 !== 0)) {
    throw new InputValidationError('Image string must be base64 or an HTTP(S) URL')
  }
}

function mediaType(bytes: Uint8Array): string {
  const header = String.fromCharCode(...bytes.subarray(0, 16))
  if (header.startsWith('%PDF-')) return 'application/pdf'
  if (header.startsWith('\x89PNG\r\n\x1a\n')) return 'image/png'
  if (header.startsWith('GIF87a') || header.startsWith('GIF89a')) return 'image/gif'
  if (header.startsWith('II*\x00') || header.startsWith('MM\x00*')) return 'image/tiff'
  if (header.startsWith('RIFF') && header.slice(8, 12) === 'WEBP') return 'image/webp'
  if (header.startsWith('BM')) return 'image/bmp'
  if (header.slice(4, 8) === 'ftyp') return header.slice(8, 12) === 'avif' ? 'image/avif' : 'image/heif'


  return 'image/jpeg'
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  if (typeof Buffer !== 'undefined') {
    return Buffer.from(buffer).toString('base64')
  }

  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary)
}
