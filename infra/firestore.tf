# The free tier only covers the database named "(default)".
resource "google_firestore_database" "default" {
  name                    = "(default)"
  location_id             = var.region
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = "DELETE_PROTECTION_ENABLED"
  # Any moment in the last 7 days can be read back or restored. Billed like
  # stored data, which at this size is well under a cent a month.
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"
  deletion_policy                   = "ABANDON"
  depends_on                        = [google_project_service.apis]
}

# Weekly backups, kept for 14 weeks (the longest a weekly schedule allows).
# The data is a few MB, so this costs cents a month.
resource "google_firestore_backup_schedule" "weekly" {
  database  = google_firestore_database.default.name
  retention = "8467200s" # 98 days

  weekly_recurrence {
    day = "SUNDAY"
  }
}

# Firestore indexes every value in a document by default, including each
# element of a day's `items` array. Nothing queries them, so turn that off:
# each write gets cheaper and the index stops growing with the data. The
# same goes for the JSON blob in `state/*`.
locals {
  unindexed = {
    samples   = "items"
    plug      = "items"
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
