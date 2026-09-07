variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "asia-south1"
}
variable "name" {
  type    = string
  default = "document-ocr"
}
variable "image_uri" {
  type        = string
  description = "Prebuilt OCR image URI, preferably pinned with @sha256. Build outside Terraform."
}
variable "languages" {
  type    = string
  default = "en"
}
variable "profile" {
  type    = string
  default = "economy"
  validation {
    condition     = contains(["economy", "warm"], var.profile)
    error_message = "profile must be economy or warm."
  }
}
variable "max_instances" {
  type    = number
  default = 10
  validation {
    condition     = var.max_instances >= 1 && floor(var.max_instances) == var.max_instances
    error_message = "max_instances must be a positive integer."
  }
}
variable "invoker_members" {
  type        = set(string)
  description = "Named IAM principals such as serviceAccount:caller@project.iam.gserviceaccount.com."
  default     = []
  validation {
    condition     = alltrue([for member in var.invoker_members : !contains(["allUsers", "allAuthenticatedUsers"], member)])
    error_message = "Public IAM principals are not supported."
  }
}
variable "api_token_secret" {
  type        = string
  default     = null
  description = "Existing Secret Manager secret ID; secret contents never enter Terraform state."
}
variable "api_token_version" {
  type    = string
  default = "latest"
}
variable "deletion_protection" {
  type    = bool
  default = true
}
