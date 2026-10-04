terraform {
  required_version = ">= 1.10"
  required_providers {
    google      = { source = "hashicorp/google", version = "~> 8.5" }
    google-beta = { source = "hashicorp/google-beta", version = "~> 8.5" }
    random      = { source = "hashicorp/random", version = "~> 3.7" }
  }
  backend "gcs" {
    bucket = "solar-farm-510518-tofu-state"
    prefix = "main"
  }

  # Secret Manager versions put credentials in state and plans; encrypt both.
  encryption {
    key_provider "pbkdf2" "passphrase" {
      passphrase = var.state_passphrase
    }
    method "aes_gcm" "main" {
      keys = key_provider.pbkdf2.passphrase
    }
    state {
      method   = method.aes_gcm.main
      enforced = true
    }
    plan {
      method   = method.aes_gcm.main
      enforced = true
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

data "google_project" "this" {}

locals {
  project_number = data.google_project.this.number
}
