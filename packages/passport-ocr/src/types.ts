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

export interface BackPageFields {
  fatherName: string | null
  motherName: string | null
  spouseName: string | null
  address: string | null
  pincode: string | null
  city: string | null
  state: string | null
  fileNumber: string | null
  oldPassportNumber: string | null
  oldPassportDateOfIssue: string | null
  oldPassportPlaceOfIssue: string | null
}

export interface PanFields {
  panNumber: string | null
  name: string | null
  fatherName: string | null
  dateOfBirth: string | null
}

export interface AadhaarFields {
  aadhaarNumber: string | null // grouped 'XXXX XXXX XXXX'
  name: string | null
  dateOfBirth: string | null
  yearOfBirth: string | null
  gender: string | null
  address: string | null
  pincode: string | null
  checksumValid: boolean
  aadhaarMasked: boolean // true when only a masked 'XXXX XXXX 9012' form was found
  aadhaarLast4: string | null
  vid: string | null // 16-digit Virtual ID, grouped, if present
}

export interface DrivingLicenceFields {
  dlNumber: string | null
  name: string | null
  dateOfBirth: string | null
  issueDate: string | null
  validityDate: string | null // non-transport (NT) / primary validity
  address: string | null
  relationName: string | null
  bloodGroup: string | null
  classOfVehicle: string | null // comma-joined COV tokens (MCWG, LMV, ...)
  validityDateTransport: string | null // transport (TR) validity, if present
}

export interface VoterIdFields {
  epicNumber: string | null
  name: string | null
  relationName: string | null
  relationType: string | null // 'father' | 'husband' | 'mother' | null
  gender: string | null
  dateOfBirth: string | null
  age: string | null
}

export interface NregaMember {
  serialNumber: string | null
  name: string | null
  fatherOrHusbandName: string | null
  gender: 'MALE' | 'FEMALE' | 'TRANSGENDER' | null
  age: number | null
}

export interface NregaJobCardFields {
  jobCardNumber: string | null
  headOfHousehold: string | null
  category: string | null
  registrationDate: string | null
  validityFrom: string | null
  validityTo: string | null
  address: string | null
  village: string | null
  gramPanchayat: string | null
  block: string | null
  district: string | null
  state: string | null
  bplStatus: boolean | null
  familyId: string | null
  members: NregaMember[]
}

export interface NprLetterFields {
  referenceNumber: string | null
  name: string | null
  address: string | null
  pincode: string | null
  issueDate: string | null
}

export type DocumentStatus = 'success' | 'unsupported_page' | 'failure'
export type DocumentType =
  | 'passport'
  | 'pan'
  | 'aadhaar'
  | 'driving_licence'
  | 'voter_id'
  | 'nrega_job_card'
  | 'npr_letter'
  | 'us_driver_license'
  | 'us_state_id'
  | 'passport_card'
  | 'us_green_card'
  | 'us_ead'
  | 'visa'
  | 'us_i94'
  | 'us_w9'
  | 'unknown'
export type PageType = DocumentType | 'passport_biodata' | 'passport_non_biodata'
export type UnsupportedReason = 'UNSUPPORTED_DOCUMENT'

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }

export interface FieldEvidence {
  text: string
  bbox: number[][]
  source: 'ocr' | 'pdf_text' | 'mrz' | 'pdf417' | 'qr'
  confidence: number
  page?: number
}

export interface BaseDocumentScanResult {
  schemaVersion?: number
  documentFields?: Record<string, JsonValue> | null
  issuingCountry?: string | null
  issuingRegion?: string | null
  fieldEvidence?: Record<string, FieldEvidence[]>
  imageSize?: [number, number] | null // [width, height] in evidence coordinates
  checks?: Record<string, boolean | string | null>
  status: DocumentStatus
  documentType: DocumentType
  pageType: PageType
  confidence: number // 0.0 - 1.0
  lowConfidence: boolean
  mrzRaw: [string, string] | null
  mrzValid: boolean
  unsupportedReason: UnsupportedReason | null
  identifierValid: boolean | null // offline checksum/format validation only; not authenticity
  missingRequiredFields: string[]
  backPageFields: BackPageFields | null
  // Per-document field blocks — null unless documentType matches:
  // a passport result has all blocks null, a PAN result populates `panFields`, etc.
  panFields: PanFields | null
  aadhaarFields: AadhaarFields | null
  drivingLicenceFields: DrivingLicenceFields | null
  voterIdFields: VoterIdFields | null
  nregaJobCardFields: NregaJobCardFields | null
  nprLetterFields: NprLetterFields | null
  probeText: string[]
  errors: string[]
  warnings: string[]
  processingMs: number
}

export interface SuccessfulDocumentScanResult extends BaseDocumentScanResult {
  status: 'success'
  fields: PassportFields | null // populated for passport biodata; null otherwise
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
  apiKey?: string // optional bearer token for HTTP mode
  // Called on every HTTP attempt so short-lived IAM tokens can be refreshed.
  // Returned headers override apiKey, which remains the fallback.
  authHeaders?: (url: string, signal?: AbortSignal) => HeadersInit | Promise<HeadersInit>
}

export type PassportOCROptions = DocumentOCROptions

export interface ScanOptions {
  documentType?: string
  country?: string
  includeEvidence?: boolean
}

export interface BatchScanResult {
  results: DocumentScanResult[]
  status: 'success' | 'partial' | 'failure'
  errors: string[]
}

export interface DocumentScanGroupResult extends BatchScanResult {
  documentFields: Record<string, JsonValue>
  conflicts: Array<{
    field: string
    values: Array<{ page: number; value: JsonValue }>
  }>
}

export interface JobOptions extends ScanOptions {
  grouped?: boolean
  notify?: boolean
}

export interface OCRJob {
  id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  createdAt: number
  expiresAt: number
  attempts: number
  error: string | null
  result?: BatchScanResult | DocumentScanGroupResult
}

export interface S3ImageInput {
  bucket: string
  key: string
  versionId?: string
}

export interface DocumentDefinition {
  documentType: DocumentType
  label: string
  countries: string[]
  fields: string[]
  requiredFields: string[]
  requiredFieldsByVariant?: Record<string, string[]>
  requirementAlternatives?: Record<string, string[][]>
  sources: string[]
  experimental: boolean
}

export interface DocumentCatalog {
  schemaVersion: number
  documents: DocumentDefinition[]
  capabilities: {
    barcode: boolean
    jobs: boolean
    review: boolean
    multipage: boolean
  }
}
