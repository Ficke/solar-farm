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
