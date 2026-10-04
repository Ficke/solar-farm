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

  # State and plan files hold the secret values (Secret Manager versions need
  # them), so OpenTofu encrypts both with a key derived from a passphrase
  # kept in GitHub. A Cloud KMS key would also work but isn't free.
  encryption {
    key_provider "pbkdf2" "passphrase" {
      passphrase = var.state_passphrase
    }
    method "aes_gcm" "main" {
      keys = key_provider.pbkdf2.passphrase
    }
    # Lets the first apply read the old unencrypted state; it saves it back
    # encrypted. After that, drop this method and the fallback below, and
    # set enforced = true on state (OpenTofu refuses enforced with it).
    method "unencrypted" "migrate" {}

    state {
      method = method.aes_gcm.main
      fallback {
        method = method.unencrypted.migrate
      }
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
