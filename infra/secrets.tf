# The plug sends this in its X-Plug-Key header. tools/deploy.py reads it from
# Secret Manager and writes it into the plug's key-value store.
resource "random_password" "plug_key" {
  length  = 40
  special = false
}

locals {
  secrets = {
    "watttime-username" = var.watttime_username
    "watttime-password" = var.watttime_password
    "jackery-email"     = var.jackery_email
    "jackery-password"  = var.jackery_password
    "plug-key"          = random_password.plug_key.result
  }
}

resource "google_secret_manager_secret" "s" {
  for_each  = local.secrets
  secret_id = each.key
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "s" {
  # Jackery telemetry is optional: no login, no version.
  for_each = toset(concat(
    ["watttime-username", "watttime-password", "plug-key"],
    local.jackery_enabled ? ["jackery-email", "jackery-password"] : [],
  ))
  secret      = google_secret_manager_secret.s[each.key].id
  secret_data = local.secrets[each.key]
}
