# NSAT Social Live Streaming

Live video uses a self-hosted LiveKit SFU. The creator publishes one camera and
microphone stream; LiveKit forwards media to viewers. Django still enforces
account access, private-profile/follow rules, viewer admission, chat and
moderation events. The browser receives a short-lived room token. Only the
creator token can publish tracks; viewer tokens can subscribe only.

## Production setup

1. Set these values in the untracked `.env.prod` file:

   ```dotenv
   LIVEKIT_PUBLIC_URL=wss://chat.satoshicore.org
   LIVEKIT_API_KEY=<random key>
   LIVEKIT_API_SECRET=<random secret>
   SOCIAL_LIVE_MAX_VIEWERS=1000
   LIVEKIT_MAX_PARTICIPANTS=1001
   ```

   Generate the key and secret separately with `openssl rand -hex 16` and
   `openssl rand -hex 32`. Keep them private. The API secret is shared by the
   backend and the LiveKit service but is never returned to a browser.

2. Permit inbound `TCP 7881` and `UDP 7882` to the server in its host firewall,
   cloud security rules and (if applicable) router. HTTPS signaling uses the
   existing `chat.satoshicore.org` TLS endpoint at `/rtc`; it does not need a new
   DNS name. `rtc.use_external_ip` asks LiveKit to discover the public address.

3. Back up the deployment and `.env.prod`, then deploy with the project's usual
   Compose command. Compose requires the LiveKit key and secret and will stop
   before starting if they are missing. Run the database migrations as part of
   the normal web entrypoint. Check the `livekit` and `livekit-redis` service
   logs, then test a host and at least two viewers on separate networks.
   Confirm the LiveKit log no longer warns that its UDP receive buffer is too
   small; if it does, raise the UDP socket buffer limits on the Linux host/VM
   before a large audience test. Docker Desktop does not allow this container
   sysctl on the current development Mac.

4. If users cannot connect from a restrictive network, configure a TURN relay
   and its TLS/firewall path. Do not assume the existing app TURN service is
   automatically configured for LiveKit.

## Capacity and scaling

The app's server-side admission cap defaults to **1,000 viewers per live** and
can be lowered or raised with `SOCIAL_LIVE_MAX_VIEWERS` (allowed range 1–2,999).
Set `LIVEKIT_MAX_PARTICIPANTS` to at least the viewer cap plus one for the
creator (maximum 3,000). This is a
configured ceiling, not a promise that the current iMac/VM/network can sustain
that audience. Actual concurrent capacity depends on encoded video quality,
CPU, memory, network egress, packet loss and other active streams. Load-test
with the target hardware and real egress path before advertising a capacity.
There is no technically honest “unlimited” cap.

Adaptive streaming and dynacast reduce unnecessary video layers, but every
viewer still consumes server bandwidth. LiveKit's self-hosted architecture is
single-home per room; many simultaneous rooms can be distributed across SFU
nodes with Redis and a suitable load balancer, while one very large room still
needs enough capacity on its assigned SFU. See the official [self-hosting
overview](https://docs.livekit.io/transport/self-hosting/),
[deployment](https://docs.livekit.io/transport/self-hosting/deployment/) and
[firewall ports](https://docs.livekit.io/transport/self-hosting/ports-firewall/).

## Rollback

Restore the previous application image/source and Caddy configuration from the
deployment backup. Keep `.env.prod` and the LiveKit service data; the schema
migration only changes the default viewer cap and is reversible. If reverting
the app, stop the LiveKit service after confirming no live sessions remain.
