output "dashboard_url" {
  value = google_cloud_run_v2_service.web.uri
}

output "plug_base_url" {
  value = google_cloud_run_v2_service.edge.uri
}

output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "deploy_service_account" {
  value = google_service_account.deploy.email
}

output "agent_reader_service_account" {
  value = google_service_account.agent_reader.email
}
