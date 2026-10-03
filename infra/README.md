# Google Cloud infrastructure

Everything in the `solar-farm-510518` project is defined here in [OpenTofu](https://opentofu.org). There are two parts:

- **`bootstrap/`**: the part CI can't create for itself. That's the state bucket, keyless GitHub access (Workload Identity Federation) and a $5 budget alert. You run it once by hand.
- **`./`**: everything else. That's the APIs, Firestore, Secret Manager, Artifact Registry, the two Cloud Run services, IAP, Cloud Scheduler and the deploy account. The Infra workflow applies it on every push to `main` that touches `infra/`.

| Resource | What it's for |
| --- | --- |
| `solar-web` (Cloud Run, IAP on) | Private dashboard and its API. Only `DASHBOARD_USERS` can sign in. |
| `solar-edge` (Cloud Run, public) | `/plug/*` for the Shelly plug (checks `X-Plug-Key`) and `/tasks/*` for Cloud Scheduler (checks a Google-signed token). |
| Firestore `(default)` | Readings, plans and plug reports. |
| Secret Manager | WattTime and Jackery logins, plus the plug key (generated here). |
| Cloud Scheduler | `solar-collect` every 5 min, `solar-plan` at :02 and :32. |
| Artifact Registry `solar-farm` | Server images; keeps the 5 newest. |

The server code doesn't exist yet. Until it does, both services run Google's placeholder "hello" image. CI owns the image after that, and `tofu apply` leaves it alone.

## One-time setup

Run these in [Cloud Shell](https://shell.cloud.google.com) (it's already signed in as you).

**1. Link billing and create the state bucket**

```sh
gcloud config set project solar-farm-510518
gcloud billing accounts list                       # note the ACCOUNT_ID
gcloud billing projects link solar-farm-510518 --billing-account=ACCOUNT_ID
gcloud storage buckets create gs://solar-farm-510518-tofu-state \
  --location=US --uniform-bucket-level-access --public-access-prevention
```

**2. Install OpenTofu and apply the bootstrap**

```sh
sudo apt-get update -qq && sudo apt-get install -y -qq gnupg   # lets the installer check OpenTofu's signature
curl -fsSL https://get.opentofu.org/install-opentofu.sh -o install-opentofu.sh
sh install-opentofu.sh --install-method standalone && rm install-opentofu.sh
git clone https://github.com/Ficke/solar-farm && cd solar-farm/infra/bootstrap
tofu init
tofu apply -var billing_account=ACCOUNT_ID
```

Then add one GitHub variable under **Settings > Secrets and variables > Actions > Variables**: `DASHBOARD_USERS`, set to `["you@gmail.com"]` (a JSON list). The workflows already know the two values the bootstrap prints, since they're fixed names in this project.

**3. Create the sign-in client for IAP**

A project without a Google Workspace organization has to supply its own OAuth client, and Google has no API for creating one, so this step happens in the console:

1. Go to [Google Auth Platform](https://console.cloud.google.com/auth/overview?project=solar-farm-510518) and click **Get started**. Set the app name to "Solar Farm", use your Gmail for both email fields, and choose **External** for the audience.
2. Under **Audience > Test users**, add your Gmail. Leave the app in Testing mode, so only test users can sign in.
3. Under **Clients > Create client**, choose **Web application** and name it "IAP". Create it, then edit it. Add the authorized redirect URI `https://iap.googleapis.com/v1/oauth/clientIds/CLIENT_ID:handleRedirect`, where CLIENT_ID is the client ID you were just shown.
4. Add two GitHub **secrets**: `IAP_OAUTH_CLIENT_ID` and `IAP_OAUTH_CLIENT_SECRET`.

The existing secrets `WATTTIME_USERNAME`, `WATTTIME_PASSWORD`, `JACKERY_EMAIL`, `JACKERY_PASSWORD` and `JACKERY_SN` get copied into Secret Manager on each apply.

**4. Apply the rest**

Merge to `main`, or run **Actions > Infra > Run workflow**. The dashboard URL appears in the run log as `dashboard_url`.

## Changing things

Edit the `.tf` files and open a PR. CI checks formatting and validates the config, and merging applies it. To preview locally, copy `terraform.tfvars.example` to `terraform.tfvars` (git-ignored) and run `tofu init && tofu plan` from Cloud Shell.

## Notes

- The state bucket is private and versioned. It holds the secret values, because OpenTofu needs them to manage the secret versions.
- Only workflows on `main` of `Ficke/solar-farm` can get Google credentials. Pull requests and forks can't.
- The infra account is a project owner, which lets it manage IAM. It has no access outside this project.
