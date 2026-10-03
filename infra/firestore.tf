# The free tier only covers the database named "(default)".
resource "google_firestore_database" "default" {
  name                    = "(default)"
  location_id             = var.region
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = "DELETE_PROTECTION_ENABLED"
  deletion_policy         = "ABANDON"
  depends_on              = [google_project_service.apis]
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
