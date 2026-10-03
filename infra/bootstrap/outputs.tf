# Paste these into GitHub as repository variables (Settings > Secrets and
# variables > Actions > Variables).
output "GCP_WORKLOAD_IDENTITY_PROVIDER" {
  value = google_iam_workload_identity_pool_provider.github.name
}

output "GCP_INFRA_SERVICE_ACCOUNT" {
  value = google_service_account.infra.email
}
