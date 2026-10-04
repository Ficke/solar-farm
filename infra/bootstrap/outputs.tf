# Workflows embed these names; update them if bootstrap identifiers change.
output "GCP_WORKLOAD_IDENTITY_PROVIDER" {
  value = google_iam_workload_identity_pool_provider.github.name
}

output "GCP_INFRA_SERVICE_ACCOUNT" {
  value = google_service_account.infra.email
}
