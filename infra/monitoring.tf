# Match health logs from each collect and Scheduler failures when collect cannot run.

resource "google_project_service" "monitoring" {
  for_each           = toset(["logging.googleapis.com", "monitoring.googleapis.com"])
  service            = each.value
  disable_on_destroy = false
}

resource "google_monitoring_notification_channel" "email" {
  for_each     = toset(length(var.alert_emails) > 0 ? var.alert_emails : var.dashboard_users)
  display_name = "Email ${each.value}"
  type         = "email"
  labels       = { email_address = each.value }
  depends_on   = [google_project_service.monitoring]
}

locals {
  edge_log = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="${google_cloud_run_v2_service.edge.name}"
  EOT

  alerts = {
    plug_silent = {
      name   = "Plug has gone quiet"
      filter = "${local.edge_log}jsonPayload.alert=\"plug_silent\""
      doc    = "No plug report in 10 minutes. Check power, Wi-Fi and script status with `just status`. The deployed firmware peak schedule works even if the script stops."
    }
    samples_stale = {
      name   = "Readings have stopped"
      filter = "${local.edge_log}jsonPayload.alert=\"samples_stale\""
      doc    = "No Jackery or WattTime reading stored in 30 minutes. Check solar-edge and Cloud Scheduler logs for collection or source failures."
    }
    plan_stale = {
      name   = "Grid plan is out of date"
      filter = "${local.edge_log}jsonPayload.alert=\"plan_stale\""
      doc    = "The plan is over two hours old. The plug accepts ordinary plans for three hours, subject to its safety backstop. Check solar-edge logs for forecast or collection failures."
    }
    grid_not_charging = {
      name   = "Grid on but the battery isn't charging"
      filter = "${local.edge_log}jsonPayload.alert=\"grid_not_charging\""
      doc    = "The plug has been on with draw below 100 W for 10 minutes, and the latest battery reading is below 95%. Check AC connections, Jackery charging limits and telemetry freshness."
    }
    task_failed = {
      name   = "Scheduled task failed"
      filter = <<-EOT
        resource.type="cloud_scheduler_job"
        resource.labels.job_id=~"^solar-"
        severity>=ERROR
      EOT
      doc    = "A solar-farm scheduled task failed. Check Cloud Scheduler and solar-edge logs if failures repeat."
    }
  }
}

resource "google_monitoring_alert_policy" "quiet" {
  for_each     = local.alerts
  display_name = each.value.name
  combiner     = "OR"

  conditions {
    display_name = each.value.name
    condition_matched_log {
      filter = each.value.filter
    }
  }

  # Limit repeated notifications to one per policy every six hours.
  alert_strategy {
    notification_rate_limit {
      period = "21600s"
    }
    auto_close = "1800s"
  }

  documentation {
    content   = each.value.doc
    mime_type = "text/markdown"
  }

  notification_channels = [for c in google_monitoring_notification_channel.email : c.id]
  depends_on            = [google_project_service.monitoring]
}
