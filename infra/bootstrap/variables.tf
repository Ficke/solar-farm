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

variable "billing_account" {
  description = "Billing account ID (XXXXXX-XXXXXX-XXXXXX) for the budget alert; empty skips it."
  type        = string
  default     = ""
}

variable "budget_usd" {
  description = "Email alerts at 50% and 100% of this monthly amount."
  type        = number
  default     = 5
}
