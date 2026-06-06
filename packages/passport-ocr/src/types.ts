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

export type DocumentStatus = 'success' | 'unsupported_page' | 'failure'
export type DocumentType =
  | 'passport'
  | 'pan'
  | 'aadhaar'
  | 'driving_licence'
  | 'voter_id'
  | 'unknown'
export type PageType =
  | 'passport_biodata'
  | 'passport_non_biodata'
  | 'pan'
  | 'aadhaar'
  | 'driving_licence'
  | 'voter_id'
  | 'unknown'
export type UnsupportedReason = 'UNSUPPORTED_DOCUMENT'

export interface BaseDocumentScanResult {
  status: DocumentStatus
  documentType: DocumentType
  pageType: PageType
  confidence: number // 0.0 - 1.0
  lowConfidence: boolean
  mrzRaw: [string, string] | null
  mrzValid: boolean
  unsupportedReason: UnsupportedReason | null
  backPageFields: BackPageFields | null
  // Per-document field blocks — null unless documentType matches. Additive:
  // a passport result has all four null, a PAN result populates `panFields`, etc.
  panFields: PanFields | null
  aadhaarFields: AadhaarFields | null
  drivingLicenceFields: DrivingLicenceFields | null
  voterIdFields: VoterIdFields | null
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
  apiKey?: string // optional bearer token for http mode
}

export type PassportOCROptions = DocumentOCROptions
