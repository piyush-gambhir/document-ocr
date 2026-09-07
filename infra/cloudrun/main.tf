terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 7.0" }
  }
}
provider "google" { project = var.project_id }
locals {
  services = toset(["run.googleapis.com", "artifactregistry.googleapis.com", "iam.googleapis.com", "secretmanager.googleapis.com"])
}
resource "google_project_service" "apis" {
  for_each           = local.services
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = var.name
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}
resource "google_service_account" "runtime" {
  account_id   = "${substr(var.name, 0, 23)}-ocr-sa"
  display_name = "Document OCR runtime"
  depends_on   = [google_project_service.apis]
}
resource "google_secret_manager_secret_iam_member" "token" {
  count     = var.api_token_secret == null ? 0 : 1
  project   = var.project_id
  secret_id = var.api_token_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_cloud_run_v2_service" "ocr" {
  name                 = var.name
  location             = var.region
  deletion_protection  = var.deletion_protection
  ingress              = "INGRESS_TRAFFIC_ALL"
  invoker_iam_disabled = false
  template {
    service_account                  = google_service_account.runtime.email
    max_instance_request_concurrency = 1
    timeout                          = "300s"
    scaling {
      min_instance_count = var.profile == "warm" ? 1 : 0
      max_instance_count = var.max_instances
    }
    containers {
      image = var.image_uri
      ports { container_port = 8000 }
      resources {
        limits            = { cpu = "2", memory = "2Gi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }
      env {
        name  = "DOCUMENT_OCR_KYC_LANGS"
        value = var.languages
      }
      dynamic "env" {
        for_each = var.api_token_secret == null ? [] : [var.api_token_secret]
        content {
          name = "API_TOKEN"
          value_source {
            secret_key_ref {
              secret  = env.value
              version = var.api_token_version
            }
          }
        }
      }
      startup_probe {
        period_seconds    = 5
        failure_threshold = 30
        timeout_seconds   = 3
        http_get {
          path = "/ready"
          port = 8000
        }
      }
      liveness_probe {
        period_seconds  = 30
        timeout_seconds = 3
        http_get {
          path = "/health"
          port = 8000
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_secret_manager_secret_iam_member.token]
}
# Authoritative only for run.invoker: explicitly excludes public invocation.
resource "google_cloud_run_v2_service_iam_binding" "invokers" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.ocr.name
  role     = "roles/run.invoker"
  members  = var.invoker_members
}
output "url" { value = google_cloud_run_v2_service.ocr.uri }
output "runtime_service_account" { value = google_service_account.runtime.email }
output "repository" { value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}" }
