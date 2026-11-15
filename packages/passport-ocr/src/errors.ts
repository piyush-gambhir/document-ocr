
export class HttpError extends Error {
  constructor(readonly status: number, message: string) {
    super(message)
    this.name = 'HttpError'
  }

  get retryable(): boolean {
    return this.status === 408 || this.status === 429 || this.status >= 500
  }
}


export class InputValidationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'InputValidationError'
  }
}
