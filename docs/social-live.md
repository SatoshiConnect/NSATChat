# Social Live

The Social feed includes a small-room vertical live video MVP. Hosts and viewers exchange WebRTC media directly; Django Channels handles authenticated signaling, comments, reactions, viewer presence, and free or owned sticker events. Live video is not recorded or relayed through the application server.

## Production requirements

- Apply the `social` migrations through `0012` before serving the updated frontend.
- Run the Channels-capable ASGI application with the configured Redis channel layer. WebSocket routing is part of `config.asgi`.
- Serve the app over HTTPS so browsers can grant camera and microphone access.
- Configure TURN through the existing `MHTALK_TURN_URLS` and credential settings. STUN alone cannot connect every carrier, enterprise, or restrictive NAT network.
- The current direct WebRTC mesh is capped at six viewers per live. Host upload and device encoding grow with each viewer. This is an early community feature, not TikTok-scale broadcasting; larger audiences need a media SFU and operational monitoring.
- NSAT support opens the existing wallet send flow for explicit review and signing. A reaction or sticker never sends coins automatically.

The frontend currently displays active sessions from the social feed and refreshes that list every 20 seconds. WebRTC connection success depends on both users' network paths and TURN availability.
