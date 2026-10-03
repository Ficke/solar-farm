resource "google_artifact_registry_repository" "images" {
  repository_id = "solar-farm"
  format        = "DOCKER"
  description   = "Server images built by CI"

  # Stay inside the 0.5 GB free allowance.
  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions { keep_count = 5 }
  }
  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition { older_than = "604800s" }
  }
  depends_on = [google_project_service.apis]
}
