resource "google_service_account" "server" {
  account_id   = "solar-server"
  display_name = "Solar Farm server (Cloud Run)"
}

resource "google_project_iam_member" "server_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.server.email}"
}

resource "google_secret_manager_secret_iam_member" "server" {
  for_each  = google_secret_manager_secret.s
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.server.email}"
}

# The server verifies this identity on /tasks/* calls.
resource "google_service_account" "scheduler" {
  account_id   = "solar-scheduler"
  display_name = "Solar Farm scheduled tasks"
}

# Deploy grants image-push and service-update access, including server impersonation.
resource "google_service_account" "deploy" {
  account_id   = "github-deploy"
  display_name = "GitHub Actions: build and deploy"
}

resource "google_artifact_registry_repository_iam_member" "deploy_push" {
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_cloud_run_v2_service_iam_member" "deploy" {
  for_each = { web = google_cloud_run_v2_service.web.name, edge = google_cloud_run_v2_service.edge.name }
  name     = each.value
  location = var.region
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_service_account_iam_member" "deploy_acts_as_server" {
  service_account_id = google_service_account.server.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_service_account_iam_member" "deploy_wif" {
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${local.project_number}/locations/global/workloadIdentityPools/github/attribute.repository/${var.github_repo}"
}

# Manage the reader key outside OpenTofu; see README.md for credential storage.
resource "google_service_account" "claude_reader" {
  account_id   = "claude-reader"
  display_name = "Claude sessions: read-only Firestore"
}

resource "google_project_iam_member" "claude_reader_firestore" {
  project = var.project_id
  role    = "roles/datastore.viewer"
  member  = "serviceAccount:${google_service_account.claude_reader.email}"
}
