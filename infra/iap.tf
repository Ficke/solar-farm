# IAP's own service agent is what actually calls solar-web after sign-in.
resource "google_project_service_identity" "iap" {
  provider   = google-beta
  service    = "iap.googleapis.com"
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service_iam_member" "iap_invoker" {
  name     = google_cloud_run_v2_service.web.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_project_service_identity.iap.email}"
}

# A project with no Google organization must bring its own OAuth client for
# IAP's sign-in page. Created by hand once (README); this wires it in.
resource "google_iap_settings" "project" {
  name = "projects/${local.project_number}/iap_web"
  access_settings {
    oauth_settings {
      client_id     = var.iap_oauth_client_id
      client_secret = var.iap_oauth_client_secret
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_iap_web_cloud_run_service_iam_member" "users" {
  for_each               = toset(var.dashboard_users)
  location               = var.region
  cloud_run_service_name = google_cloud_run_v2_service.web.name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = "user:${each.value}"
}
