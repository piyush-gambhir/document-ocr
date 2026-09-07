variable "name" {
  type    = string
  default = "document-ocr"
}
variable "region" {
  type    = string
  default = "ap-south-1"
}
variable "image_uri" {
  type        = string
  description = "Prebuilt Lambda-compatible image in ECR in this region, preferably pinned by digest."
}
variable "languages" {
  type    = string
  default = "en"
}
variable "input_bucket" {
  type        = string
  default     = null
  description = "Existing input bucket. Only GetObject on input_prefix is granted; no uploads/deletes/listing."
}
variable "input_prefix" {
  type    = string
  default = "uploads/"
  validation {
    condition     = can(regex("^[A-Za-z0-9._/-]+/$", var.input_prefix)) && !strcontains(var.input_prefix, "..")
    error_message = "Use a nonempty relative prefix ending in / without wildcards or .. segments."
  }
}
variable "max_concurrency" {
  type    = number
  default = 10
  validation {
    condition     = var.max_concurrency >= 1 && floor(var.max_concurrency) == var.max_concurrency
    error_message = "max_concurrency must be a positive integer."
  }
}
