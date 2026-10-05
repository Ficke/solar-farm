# Plug script

`src/grid-gate.js` runs on the Shelly plug; its rules are in
[docs/charging.md](../docs/charging.md#plug). The Shelly runtime requires ES5.

## Deploy

From the repository root, on the plug's Wi-Fi with any VPN off:

```sh
cp config/device.example.toml config/device.toml   # first time: set host
gcloud auth login
just deploy
just status
```

The first deploy sets a local `admin` password and saves it in
`config/device.toml`. If it is lost, turn off authentication in the Shelly
app and redeploy.

Deploy also adds firmware schedules that turn the relay off during the peak
and restart a stopped script every 10 minutes. Disable the restart schedule
before stopping the script on purpose.

`bun device/sim.js` simulates the next 24 hours against the live plan.
