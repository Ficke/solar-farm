# Google Cloud infrastructure

Everything in the `solar-farm-510518` project is defined here in [OpenTofu](https://opentofu.org). There are two parts:

- **`bootstrap/`**: the part CI can't create for itself. That's the state bucket, keyless GitHub access (Workload Identity Federation) and a $5 budget alert. You run it once from your machine.
- **`./`**: everything else. That's the APIs, Firestore, Secret Manager, Artifact Registry, the two Cloud Run services, IAP, Cloud Scheduler, alerts and the deploy account. The Infra workflow applies it on every push to `main` that touches `infra/`.

| Resource | What it's for |
| --- | --- |
| `solar-web` (Cloud Run, IAP on) | Private dashboard and its API. Only `DASHBOARD_USERS` can sign in. |
| `solar-edge` (Cloud Run, public) | `/plug/*` for the Shelly plug (checks `X-Plug-Key`) and `/tasks/*` for Cloud Scheduler (checks a Google-signed token). |
| Firestore `(default)` | Readings, plans and plug reports. Weekly backups and 7 days of point-in-time recovery. |
| Secret Manager | WattTime and Jackery logins, plus the plug key (generated here). |
| Cloud Scheduler | `solar-collect` every minute. |
| Artifact Registry `solar-farm` | Server images; keeps the 5 newest. |
| Alert policies | Email when the plug is silent for 10 min, readings stop for 30 min, the plan is over 2 h old, or a scheduled task fails. |

## One-time setup

Run everything from your local clone of this repo.

**1. Install the tools and sign in**

On a Mac with Homebrew (Homebrew checks each download's integrity itself):

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

From the repo root:

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

The last command encrypts OpenTofu's state. Save the passphrase it prints in your password manager: without it the state can't be read.

The workflows already know the two values the bootstrap prints, since they're fixed names in this project.

**3. Create the sign-in client for IAP**

A project without a Google Workspace organization has to supply its own OAuth client, and Google has no API for creating one, so this step happens in the console:

1. Go to [Google Auth Platform](https://console.cloud.google.com/auth/overview?project=solar-farm-510518) and click **Get started**. Set the app name to "Solar Farm", use your Gmail for both email fields, and choose **External** for the audience.
2. Under **Audience > Test users**, add your Gmail. Leave the app in Testing mode, so only test users can sign in.
3. Under **Clients > Create client**, choose **Web application** and name it "IAP". Create it, then edit it. Add the authorized redirect URI `https://iap.googleapis.com/v1/oauth/clientIds/CLIENT_ID:handleRedirect`, where CLIENT_ID is the client ID you were just shown.
4. Store the client in GitHub. Each command prompts you to paste the value:

   ```sh
   gh secret set IAP_OAUTH_CLIENT_ID
   gh secret set IAP_OAUTH_CLIENT_SECRET
   ```

The existing secrets `WATTTIME_USERNAME`, `WATTTIME_PASSWORD`, `JACKERY_EMAIL`, `JACKERY_PASSWORD` and `JACKERY_SN` get copied into Secret Manager on each apply.

**4. Apply the rest**

Merge to `main`, or run it now:

```sh
gh workflow run infra.yml && gh run watch
```

The dashboard URL appears in the run log as `dashboard_url`.

## Changing things

Edit the `.tf` files and open a PR. CI checks formatting and validates the config, and merging applies it. To preview locally, copy `terraform.tfvars.example` to `terraform.tfvars` (git-ignored) and run `tofu -chdir=infra init && tofu -chdir=infra plan`. Provider versions are pinned in the committed `.terraform.lock.hcl` files; after changing a provider version, run `just lock` and commit them.

## Notes

- The state holds the secret values, because OpenTofu needs them to manage the secret versions, so it's encrypted with `TOFU_STATE_PASSPHRASE` (OpenTofu state encryption). The bucket is also private and versioned. For a local `tofu plan`, put the passphrase in `terraform.tfvars` as `state_passphrase`.
- Alerts are log-match policies, which are free. The server logs a line for each stale part on every collect (`server/solar_server/health.py`); Cloud Scheduler logs its own failures. They go to `DASHBOARD_USERS`, at most one email per alert every 6 hours.
- Only workflows on `main` of `Ficke/solar-farm` can get Google credentials. Pull requests and forks can't.
- The infra account is a project owner, which lets it manage IAM. It has no access outside this project.
- AI agents read Firestore as `agent-reader`, which only has Cloud Datastore Viewer. For Claude cloud sessions its key lives in the cloud environment's API credentials (type "GCP access token", allowed website `firestore.googleapis.com`), never in environment variables, chat or this repo. To rotate it, create a new key, replace the credential, then delete the old key.
