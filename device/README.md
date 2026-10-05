# Plug script

`src/grid-gate.js` runs on the Shelly Plug US Gen4 and switches the
Jackery's AC input. [docs/charging.md](../docs/charging.md#plug) lists its
rules. The Shelly runtime requires ES5; tests enforce it.

## Deploy

Run from the repository root, on the same Wi-Fi network as the plug, with any
VPN off:

```sh
cp config/device.example.toml config/device.toml   # first time: set host
gcloud auth login
just deploy             # or: just deploy --dry-run
just status
```

Deploy reads the plug key and WattTime login from Secret Manager (`.env`
overrides them), uploads the script with its settings, sets the timezone, and
starts the script on boot.

The first deploy turns on local authentication as `admin` and saves a
generated password to `config/device.toml`, which git ignores. If the
password is lost, turn off authentication in the Shelly app and redeploy.

## Firmware safeguards

Deploy also adds firmware schedules that work even if the script stops:

- **Peak off:** turns the relay off in the first minute of the peak and every
  half hour after it.
- **Watchdog:** restarts the script every 10 minutes if it has stopped.
  Disable this schedule before stopping the script on purpose.

During the low-battery peak exception, the script turns the relay on with a
3-minute firmware timer and renews it each minute, so the relay turns off if
the script stops.

Each deploy replaces all relay-off schedules for switch 0 and all script-start
schedules for grid-gate, including ones created by hand.

## Simulate

Run the next 24 hours against the live plan, without hardware:

```sh
bun device/sim.js           # uses gcloud to fetch the plug key
bun device/sim.js --stale   # ignores plan and live index; daytime fallback
```
