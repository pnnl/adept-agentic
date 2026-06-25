terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 4.0.0"
    }
  }
}

provider "google" {
  project = var.gcp_project
  region  = var.gcp_region
}

resource "google_container_cluster" "primary" {
  name     = "agentic-framework-cluster"
  location = var.gcp_region

  initial_node_count = 1

  node_config {
    machine_type = "n1-standard-2"
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
  }

  workload_identity_config {
    workload_pool = "${var.gcp_project}.svc.id.goog"
  }
}

resource "google_artifact_registry_repository" "primary" {
  location      = var.gcp_region
  repository_id = "agentic-framework-repo"
  format        = "DOCKER"
}

resource "google_service_account" "gke_sa" {
  account_id   = "gke-workload-identity-sa"
  display_name = "GKE Workload Identity Service Account"
}

resource "google_project_iam_member" "gke_sa_binding" {
  project = var.gcp_project
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.gke_sa.email}"
}

resource "google_filestore_instance" "primary" {
  name     = "agentic-framework-filestore"
  location = var.gcp_region
  tier     = "STANDARD"

  file_shares {
    capacity_gb = 1024
    name        = "shared"
  }

  networks {
    network = "default"
    modes   = ["MODE_IPV4"]
  }
}

resource "google_secret_manager_secret" "api_keys" {
  secret_id = "api-keys"

  replication {
    automatic = true
  }
}

variable "gcp_project" {
  description = "The GCP project ID."
}

variable "gcp_region" {
  description = "The GCP region."
  default     = "us-central1"
}

output "gke_cluster_name" {
  value = google_container_cluster.primary.name
}

output "artifact_registry_url" {
  value = "${google_artifact_registry_repository.primary.location}-docker.pkg.dev/${var.gcp_project}/${google_artifact_registry_repository.primary.repository_id}"
}
