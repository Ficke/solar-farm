# One-time setup, run by hand from Cloud Shell with your own login. It gives
# GitHub Actions a keyless way into the project so that everything in ../
# (the main config) is applied by CI on every merge to main. See ../README.md.

terraform {
  required_version = ">= 1.10"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 8.5" }
  }
  backend "gcs" {
    bucket = "solar-farm-510518-tofu-state"
    prefix = "bootstrap"
  }
}

provider "google" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}

data "google_project" "this" {}

resource "google_project_service" "bootstrap" {
  for_each = toset([
    "billingbudgets.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "serviceusage.googleapis.com",
    "sts.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# The state bucket has to exist before `tofu init`, so the README creates it
# with one gcloud command and this block adopts it.
import {
  to = google_storage_bucket.state
  id = "solar-farm-510518-tofu-state"
}

# Versioning keeps every past state file, so a bad apply can be rolled back.
resource "google_storage_bucket" "state" {
  name                        = "${var.project_id}-tofu-state"
  location                    = "US"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  versioning { enabled = true }
  lifecycle_rule {
    condition {
      num_newer_versions = 20
      with_state         = "ARCHIVED"
    }
    action { type = "Delete" }
  }
}

# --- GitHub Actions -> Google Cloud, without a stored key -------------------

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  depends_on                = [google_project_service.bootstrap]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "solar-farm"
  display_name                       = "Ficke/solar-farm"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  # Only workflows running on main of this repository can get a token. Pull
  # requests (including from forks) cannot.
  attribute_condition = "assertion.repository == '${var.github_repo}' && assertion.ref == 'refs/heads/main'"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Applies ../ from CI. It needs to create service accounts, grant roles and
# manage every service in the project, so it is an owner of this project
# (and nothing else). Only a push to main can act as it.
resource "google_service_account" "infra" {
  account_id   = "github-infra"
  display_name = "GitHub Actions: OpenTofu apply"
}

resource "google_project_iam_member" "infra_owner" {
  project = var.project_id
  role    = "roles/owner"
  member  = "serviceAccount:${google_service_account.infra.email}"
}

resource "google_storage_bucket_iam_member" "infra_state" {
  bucket = google_storage_bucket.state.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.infra.email}"
}

resource "google_service_account_iam_member" "infra_wif" {
  service_account_id = google_service_account.infra.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

# --- Spending guard ----------------------------------------------------------

resource "google_billing_budget" "monthly" {
  count           = var.billing_account == "" ? 0 : 1
  billing_account = var.billing_account
  display_name    = "solar-farm monthly"
  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }
  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.budget_usd)
    }
  }
  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 1.0 }
  depends_on = [google_project_service.bootstrap]
}
