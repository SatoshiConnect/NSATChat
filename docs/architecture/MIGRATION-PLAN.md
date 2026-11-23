# Migration Plan

## This change

- **Database:** No Django model was added, moved, or renamed in Wallet Integration or the status policy extraction. No migration is expected.
- **HTTP:** The canonical Wallet read URL is `/api/wallet/read/`. The old `/api/accounts/wallet/read/` is an alias to the same view and is covered by a compatibility test. Keep the alias until client telemetry shows it is no longer used; removing it requires a separate deprecation change.
- **Frontend:** The Wallet screen import changes from a component path to the feature module public export. Shared styling and common UI components stay put.
- **Settings:** New feature environment variables default to existing behavior. Existing deployments need no immediate environment change. To disable a capability, set the corresponding backend variable to `false`; hide Wallet navigation with `VITE_FEATURE_WALLET_UI=false` and rebuild frontend assets.

## Rollback

Revert the feature branch commit(s). There is no schema/data rollback. The legacy Wallet URL remains wired. If reverting after deployment, restore both frontend/backend artifacts together; do not edit or reset database data.

## Future migrations

Do not move existing models or mass-reorganize React components in this branch. For any such work: record current schema and API behavior, add reversible/data-preserving migrations if needed, deploy additive schema first, test production-like data, then remove old paths only after client compatibility is verified. Wallet engine/key custody and NSAT Mainnet operations remain outside Messenger.
