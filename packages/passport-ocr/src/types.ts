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

export type DocumentStatus = 'success' | 'unsupported_page' | 'failure'
export type DocumentType = 'passport' | 'unknown'
export type PageType = 'passport_biodata' | 'passport_non_biodata' | 'unknown'
export type UnsupportedReason = 'NON_BIODATA_PAGE' | 'UNSUPPORTED_DOCUMENT'

export interface BaseDocumentScanResult {
  status: DocumentStatus
  documentType: DocumentType
  pageType: PageType
  confidence: number // 0.0 - 1.0
  lowConfidence: boolean
  mrzRaw: [string, string] | null
  mrzValid: boolean
  unsupportedReason: UnsupportedReason | null
  probeText: string[]
  errors: string[]
  warnings: string[]
  processingMs: number
}

export interface SuccessfulDocumentScanResult extends BaseDocumentScanResult {
  status: 'success'
  documentType: 'passport'
  pageType: 'passport_biodata'
  fields: PassportFields
}

export interface UnsupportedPageDocumentScanResult extends BaseDocumentScanResult {
  status: 'unsupported_page'
  fields: null
  unsupportedReason: UnsupportedReason
}

export interface FailedDocumentScanResult extends BaseDocumentScanResult {
  status: 'failure'
  fields: PassportFields | null
}

export type DocumentScanResult =
  | SuccessfulDocumentScanResult
  | UnsupportedPageDocumentScanResult
  | FailedDocumentScanResult

export type PassportScanResult = DocumentScanResult

export type ImageInput = File | Blob | Buffer | ArrayBuffer | string // string = base64 or URL

export type ClientMode = 'local' | 'http' | 'lambda'

export interface DocumentOCROptions {
  mode?: ClientMode // default: 'local'
  endpoint?: string // required for mode: 'http'
  functionName?: string // required for mode: 'lambda'
  timeoutMs?: number // default: 30000
  retries?: number // default: 2
  apiKey?: string // optional bearer token for http mode
}

export type PassportOCROptions = DocumentOCROptions
