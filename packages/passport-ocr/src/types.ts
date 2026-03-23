export interface PassportFields {
  surname: string | null
  givenNames: string | null
  fullName: string | null
  passportNumber: string | null
  nationality: string | null
  dateOfBirth: string | null // ISO 8601
  sex: 'M' | 'F' | 'X' | null
  expiryDate: string | null // ISO 8601
  issueDate: string | null
  placeOfBirth: string | null
  countryCode: string | null // ISO 3166-1 alpha-3
}

export interface PassportScanResult {
  success: boolean
  confidence: number // 0.0 - 1.0
  lowConfidence: boolean
  fields: PassportFields
  mrzRaw: [string, string] | null
  mrzValid: boolean
  errors: string[]
  warnings: string[]
  processingMs: number
}

export type ImageInput = File | Blob | Buffer | ArrayBuffer | string // string = base64 or URL

export type ClientMode = 'http' | 'lambda'

export interface PassportOCROptions {
  mode?: ClientMode // default: 'http'
  endpoint?: string // required for mode: 'http'
  functionName?: string // required for mode: 'lambda'
  timeoutMs?: number // default: 30000
  retries?: number // default: 2
  apiKey?: string // optional bearer token for http mode
}
