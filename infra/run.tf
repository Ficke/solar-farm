# One image, two services. solar-web is the private dashboard behind IAP.
# solar-edge is reachable from the internet but only answers the plug (with
# its key) and Cloud Scheduler (with a Google-signed token).

locals {
  jackery_enabled = nonsensitive(var.jackery_email != "")
  secret_env = merge(
    {
      WATTTIME_USERNAME = "watttime-username"
      WATTTIME_PASSWORD = "watttime-password"
    },
    local.jackery_enabled ? {
      JACKERY_EMAIL    = "jackery-email"
      JACKERY_PASSWORD = "jackery-password"
    } : {},
  )
}

resource "google_cloud_run_v2_service" "web" {
  provider            = google-beta
  name                = "solar-web"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  iap_enabled         = true
  deletion_protection = false

  template {
    service_account                  = google_service_account.server.email
    max_instance_request_concurrency = 80
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = var.image
      resources {
        limits            = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }
      env {
        name  = "SOLAR_ROLE"
        value = "web"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
    }
  }

  # CI owns the running image and its revision labels.
  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version, template[0].labels]
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service" "edge" {
  name                 = "solar-edge"
  location             = var.region
  ingress              = "INGRESS_TRAFFIC_ALL"
  invoker_iam_disabled = true # the plug can't sign in; the server checks X-Plug-Key itself
  deletion_protection  = false

  template {
    service_account = google_service_account.server.email
    timeout         = "120s"
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = var.image
      resources {
        limits            = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }
      env {
        name  = "SOLAR_ROLE"
        value = "edge"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "SCHEDULER_SERVICE_ACCOUNT"
        value = google_service_account.scheduler.email
      }
      env {
        name  = "JACKERY_SN"
        value = var.jackery_sn
      }
      env {
        name = "PLUG_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.s["plug-key"].secret_id
            version = "latest"
          }
        }
      }
      dynamic "env" {
        for_each = local.secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.s[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version, template[0].labels]
  }
  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.s,
    google_secret_manager_secret_iam_member.server,
  ]
}
