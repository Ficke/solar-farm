# Email alerts when the system goes quiet. All of them are log-match alert
# policies, which Cloud Monitoring doesn't charge for (metric-based ones
# would be, from 2027), and the log volume stays far inside Logging's free
# 50 GiB a month.
#
# The server checks freshness on every collect (server/solar_server/health.py)
# and logs one line per problem. If the server itself is down, its scheduled
# calls fail instead, which the last policy catches.

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
      doc    = "No report from the Shelly plug in 10 minutes. It may be offline, unplugged or its script stopped. It still blocks 4 to 9 pm on its own if the script is running. Check it with `just status`."
    }
    samples_stale = {
      name   = "Readings have stopped"
      filter = "${local.edge_log}jsonPayload.alert=\"samples_stale\""
      doc    = "No Jackery or WattTime reading stored in 30 minutes. Both sources are failing; see the solar-edge logs."
    }
    plan_stale = {
      name   = "Grid plan is out of date"
      filter = "${local.edge_log}jsonPayload.alert=\"plan_stale\""
      doc    = "The grid plan is more than 2 hours old, so the plug is using its own fallback. Usually WattTime's forecast is failing; see the solar-edge logs."
    }
    task_failed = {
      name   = "Scheduled task failed"
      filter = <<-EOT
        resource.type="cloud_scheduler_job"
        resource.labels.job_id=~"^solar-"
        severity>=ERROR
      EOT
      doc    = "Cloud Scheduler couldn't run a solar-farm task (collect or plan). If this repeats, solar-edge may be down; see Cloud Run logs."
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

  # A problem logs every 5 minutes while it lasts; email about it at most
  # every 6 hours.
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
