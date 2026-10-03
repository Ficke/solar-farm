locals {
  jobs = {
    collect = { path = "/tasks/collect", schedule = "*/5 * * * *", what = "Jackery + WattTime sample" }
    plan    = { path = "/tasks/plan", schedule = "2,32 * * * *", what = "24 h forecast and grid plan" }
  }
}

resource "google_cloud_scheduler_job" "tasks" {
  for_each         = local.jobs
  name             = "solar-${each.key}"
  description      = each.value.what
  schedule         = each.value.schedule
  time_zone        = "America/Los_Angeles"
  attempt_deadline = "120s"

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.edge.uri}${each.value.path}"
    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = google_cloud_run_v2_service.edge.uri
    }
  }
  depends_on = [google_project_service.apis]
}
