# Cloudflare Setup

## Quick way

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_phone_access.ps1
```

If you have no permanent tunnel tokens set yet, the script will create quick tunnels.
Read the public URLs from:

- `.runtime/logs/cloudflared-quick-bridge.err.log`
- `.runtime/logs/cloudflared-quick-ui.err.log`

Stop them with:

```powershell
powershell -ExecutionPolicy Bypass -File .\stop_phone_access.ps1
```

## Permanent way

Create 2 named tunnels in Cloudflare Zero Trust:

1. One tunnel for the backend bridge `http://127.0.0.1:5050`
2. One tunnel for the UI `http://127.0.0.1:8080`

Then place these values in `.env`:

```env
CLOUDFLARE_TUNNEL_BRIDGE_TOKEN=your_bridge_tunnel_token
CLOUDFLARE_TUNNEL_UI_TOKEN=your_ui_tunnel_token
CLOUDFLARE_PUBLIC_BRIDGE_URL=https://your-bridge-domain.example.com
CLOUDFLARE_PUBLIC_UI_URL=https://your-ui-domain.example.com
```

After that, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_phone_access.ps1
```

The script will prefer the permanent tunnels automatically.

## GitHub Pages usage

Supervisor:

```text
https://kutmillztbot.github.io/personalsystemai/?bridge=https://your-bridge-domain.example.com
```

ForexSmartBot:

```text
https://kutmillztbot.github.io/personalsystemai/ForexSmartBot/forexsmartbot_dashboard.html?bridge=https://your-bridge-domain.example.com
```
