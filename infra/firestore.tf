# The free tier only covers the database named "(default)".
resource "google_firestore_database" "default" {
  name                              = "(default)"
  location_id                       = var.region
  type                              = "FIRESTORE_NATIVE"
  delete_protection_state           = "DELETE_PROTECTION_ENABLED"
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"
  deletion_policy                   = "ABANDON"
  depends_on                        = [google_project_service.apis]
}

# Retain weekly backups for 14 weeks.
resource "google_firestore_backup_schedule" "weekly" {
  database  = google_firestore_database.default.name
  retention = "8467200s" # 98 days

  weekly_recurrence {
    day = "SUNDAY"
  }
}

# These fields are read as whole documents; disable unused indexes to limit growth.
locals {
  unindexed = {
    samples   = "items"
    plug      = "items"
    jackery   = "items"
    plans     = "items"
    forecasts = "items"
    mix       = "items"
    state     = "data_json"
  }
}

resource "google_firestore_field" "unindexed" {
  for_each   = local.unindexed
  database   = google_firestore_database.default.name
  collection = each.key
  field      = each.value
  index_config {}
}
