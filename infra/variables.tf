variable "project_id" {
  type    = string
  default = "solar-farm-510518"
}

variable "region" {
  type    = string
  default = "us-west1"
}

variable "github_repo" {
  type    = string
  default = "Ficke/solar-farm"
}

variable "state_passphrase" {
  description = "Encrypts OpenTofu state and plans (GitHub secret TOFU_STATE_PASSPHRASE)."
  type        = string
  sensitive   = true
}

variable "dashboard_users" {
  description = "Google accounts allowed to open the dashboard."
  type        = list(string)
}

variable "alert_emails" {
  description = "Where alerts go. Empty means the dashboard users."
  type        = list(string)
  default     = []
}

variable "iap_oauth_client_id" {
  description = "OAuth client for IAP sign-in (projects without an organization need their own)."
  type        = string
}

variable "iap_oauth_client_secret" {
  type      = string
  sensitive = true
}

variable "watttime_username" {
  type      = string
  sensitive = true
}

variable "watttime_password" {
  type      = string
  sensitive = true
}

variable "jackery_email" {
  type      = string
  sensitive = true
  default   = ""
}

variable "jackery_password" {
  type      = string
  sensitive = true
  default   = ""
}

variable "jackery_sn" {
  type    = string
  default = ""
}

variable "image" {
  description = "Initial container image. CI deploys the real one; later applies leave it alone."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}
