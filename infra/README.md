# Google Cloud infrastructure

[OpenTofu](https://opentofu.org) manages the `solar-farm-510518` project:

- **`bootstrap/`** creates the state bucket, keyless GitHub access (Workload Identity Federation), and a $5 budget alert. Apply it locally once; later bootstrap changes also require a local apply.
- **`./`** manages application resources. Infra runs CI and applies changes on relevant pushes to `main`, excluding bootstrap-only changes.

| Resource | What it's for |
| --- | --- |
| `solar-web` (Cloud Run, IAP on) | Private dashboard and its API. Only `DASHBOARD_USERS` can sign in. |
| `solar-edge` (Cloud Run, public) | `/plug/*` for the Shelly plug (checks `X-Plug-Key`) and `/tasks/*` for Cloud Scheduler (checks a Google-signed token). |
| Firestore `(default)` | Telemetry, mix, plan and forecast history, live state, and totals. Weekly backups retained for 14 weeks; seven-day point-in-time recovery. |
| Secret Manager | WattTime and Jackery logins, plus the plug key (generated here). |
| Cloud Scheduler | `solar-collect` every minute. |
| Artifact Registry `solar-farm` | Keeps the five newest image versions; deletes other versions older than seven days. |
| Alert policies | Email for missing reports (10 min), missing readings (30 min), stale plans (2 h), low charging power (10 min below 95% battery), or failed tasks. |

## One-time setup

Run commands from the repository root unless shown otherwise.

**1. Install the tools and sign in**

On macOS with Homebrew:

```sh
brew install opentofu gh
brew install --cask gcloud-cli
```

On Linux, install [OpenTofu from its apt or rpm repository](https://opentofu.org/docs/intro/install/) and the [gcloud CLI](https://cloud.google.com/sdk/docs/install).

```sh
gcloud auth login                         # for gcloud commands
gcloud auth application-default login     # for OpenTofu
gcloud config set project solar-farm-510518
gh auth login                             # for setting GitHub variables and secrets below
```

**2. Link billing, create the state bucket, apply the bootstrap**

```sh
gcloud billing accounts list              # note the ACCOUNT_ID
gcloud billing projects link solar-farm-510518 --billing-account=ACCOUNT_ID
gcloud storage buckets create gs://solar-farm-510518-tofu-state \
  --location=US --uniform-bucket-level-access --public-access-prevention

tofu -chdir=infra/bootstrap init
tofu -chdir=infra/bootstrap apply -var billing_account=ACCOUNT_ID

gh variable set DASHBOARD_USERS --body '["you@gmail.com"]'
openssl rand -base64 32 | tee /dev/tty | gh secret set TOFU_STATE_PASSPHRASE
```

Save the printed passphrase in a password manager; it is required to decrypt main state and plan files.

Workflows already contain this project's bootstrap provider and service-account names.

**3. Create the sign-in client for IAP**

This setup uses a manually created OAuth client for IAP. In the Google Cloud console:

1. Go to [Google Auth Platform](https://console.cloud.google.com/auth/overview?project=solar-farm-510518) and click **Get started**. Set the app name to "Solar Farm", use your Gmail for both email fields, and choose **External** for the audience.
2. Under **Audience > Test users**, add your Gmail. Leave the app in Testing mode, so only test users can sign in.
3. Under **Clients > Create client**, choose **Web application** and name it "IAP". Create it, then edit it. Add the authorized redirect URI `https://iap.googleapis.com/v1/oauth/clientIds/CLIENT_ID:handleRedirect`, where CLIENT_ID is the client ID you were just shown.
4. Store the client in GitHub. Each command prompts you to paste the value:

   ```sh
   gh secret set IAP_OAUTH_CLIENT_ID
   gh secret set IAP_OAUTH_CLIENT_SECRET
   ```

Set `WATTTIME_USERNAME` and `WATTTIME_PASSWORD` as GitHub secrets. Optional `JACKERY_EMAIL` and `JACKERY_PASSWORD` enable telemetry; `JACKERY_SN` selects the station. Infra copies credentials into Secret Manager and passes the serial number directly to Cloud Run.

**4. Apply the rest**

Push application infrastructure changes to `main`, or dispatch Infra:

```sh
gh workflow run infra.yml && gh run watch
```

The dashboard URL appears in the run log as `dashboard_url`.

## Changing things

Edit `.tf` files and open a PR; CI checks formatting, provider locks and validity. Merging application infrastructure changes applies them. For a local preview, copy `infra/terraform.tfvars.example` to `infra/terraform.tfvars`, fill in the values, and run `tofu -chdir=infra init && tofu -chdir=infra plan`. Local state and variable files are excluded by `infra/.gitignore`. After changing provider constraints, run `just lock` and commit both `.terraform.lock.hcl` files.

## Notes

- Main state and plans contain secret values and use `TOFU_STATE_PASSPHRASE` for encryption. For local commands, set `state_passphrase` in `infra/terraform.tfvars`. The private state bucket retains up to 20 archived versions.
- Alerts match server health logs and Cloud Scheduler failures. Recipients are `alert_emails`, or `dashboard_users` when no override is set, with at most one notification per policy every six hours.
- Only workflows on `main` of `Ficke/solar-farm` can obtain Google credentials. The infra account has project-owner access to manage IAM; the deploy account has image-push and service-deployment roles.
- `claude-reader` has Cloud Datastore Viewer access for cloud sessions. Its manually managed key belongs in the cloud environment's API credentials (type “GCP access token”, host `firestore.googleapis.com`), outside this repository and OpenTofu state. Rotate by creating a key, replacing the credential, then deleting the old key.
