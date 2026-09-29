# Deploy Attendee from GitHub Actions

Use **Actions → Deploy Attendee → Run workflow** after the existing **Deploy** workflow has successfully deployed Echooo. Commit and push the new workflow to the default branch first. Select the branch containing the deployment changes when running it.

The workflow builds Attendee independently of Echooo, mirrors its dependencies to ACR, smoke-tests the published stack on the runner, then deploys immutable image digests over SSH. It reuses the existing repository variables `ACR_REGISTRY`, `ACR_NAMESPACE`, `ACR_REPOSITORY` and secrets `ACR_USERNAME`, `ACR_PASSWORD`, `SSH_HOST`, `SSH_PORT` (optional, defaults to 22), `SSH_USER`, `SSH_KEY`, `SSH_KNOWN_HOSTS`. No additional GitHub secrets are required. The server must already be able to pull from ACR, as for the Echooo deployment.

## Before running

- Use the same **x86_64/amd64 Linux server** as Echooo; this pinned Attendee browser image does not support ARM servers. The workflow rejects an incompatible server before building.
- Docker Compose 2.24+, Python 3.6+, OpenSSL with `-addext`, `flock`, and the existing `/opt/echooo/current`, `/opt/echooo/app.env`, and `echooo_proxy` network must be available to the deployment user.
- Finish recordings and have all bots leave before deploying. Attendee deployments reject active or scheduled bots on an existing installation. Echooo briefly stops during deployment, so browser recordings and invitations are interrupted.
- Provide enough disk and memory for the browser worker and image build/pull. The worker reserves a 2 GiB shared-memory limit, which is not a recommendation for total server RAM. The first image build is large and can take considerably longer than an Echooo build.
- The server needs outbound access to the meeting platform and configured STT/LLM/TTS providers.

Both workflows share GitHub's `deploy` concurrency group and the server's `/opt/echooo/deploy.lock`.

## What is installed

A separate Compose project, `echooo-attendee-cloud`, runs PostgreSQL 15, Redis with AOF persistence, a Gunicorn API, one Celery worker, and a private Caddy TLS callback gateway. Echooo's database and existing public reverse proxy are retained. The API/dashboard binds only to `127.0.0.1:8011`; do not open this port in the public firewall.

The workflow pins upstream Attendee to `60e885df6f9ed0f38ef141438caac9978a38a6cc` and bakes the same checked chat/audio overlay used by the local connector into its image. Dependency tags are resolved to immutable ACR digests for each release.

Server files:

| Path | Purpose |
| --- | --- |
| `/opt/echooo/attendee/attendee.env` | Generated Django, encryption, database, connector and dashboard credentials; preserved on reruns |
| `/opt/echooo/attendee/tls/` | Private callback certificate and key |
| `/opt/echooo/attendee/releases/` | Release configurations and image digests |
| `/opt/echooo/attendee/current` | Last successful Attendee deployment |
| `/opt/echooo/attendee/previous` | Previous successful Attendee deployment |
| `/opt/echooo/attendee/backups/` | Pre-update database dumps and private Echooo environment backups |

The deployment edits only these entries in `/opt/echooo/app.env`, then recreates the existing Echooo app container:

```dotenv
ATTENDEE_BASE_URL=http://attendee-api:8000/api/v1
ATTENDEE_API_KEY=<automatically generated on the server>
ATTENDEE_CALLBACK_URL=wss://echooo-attendee-gateway:8443
```

The API shares Echooo's existing private Docker proxy network. The worker reaches Echooo through its private TLS gateway, which forwards `/ws/meeting-bots/*` to `echooo-upstream:8000`. This does not require a public HTTPS domain for the connector callback, including when the Echooo page is currently served over HTTP/IP.

Before marking a release successful, deployment verifies the authenticated API from the Echooo container, worker health, and TLS WebSocket forwarding from the worker. The callback probe intentionally uses an invalid token and expects Echooo's HTTP 403 rejection; no meeting is created. After deployment, invite Echooo to a test meeting and verify admission and live audio. Zoom still requires project-specific Zoom credentials described in [ATTENDEE.md](ATTENDEE.md).

## Dashboard and diagnostics

Open a tunnel from your computer (replace user, host and SSH port):

```bash
ssh -p 22 -L 8011:127.0.0.1:8011 user@server
```

Visit `http://127.0.0.1:8011`. Login email is `echooo@localhost`; retrieve `ECHOOO_ADMIN_PASSWORD` privately from `/opt/echooo/attendee/attendee.env`. Do not paste that file or raw bot logs into public issues or Actions logs.

On the server:

```bash
bash /opt/echooo/attendee/current/compose.sh ps
bash /opt/echooo/attendee/current/compose.sh logs --tail=80 api worker gateway
```

A normal Echooo **Deploy** continues using the connector configuration in `app.env`; it does not rebuild Attendee. Run **Deploy Attendee** again when changing the connector image or deployment files.

## Failure and recovery

Build, runner smoke-test, registry pull, or an initial active-bot check failure does not stop Echooo. After downtime starts, a handled deployment failure restores the previous Echooo environment and attempts to restart its app. The failed Attendee release is not promoted. A forcibly killed job or disconnected server may require manual recovery; inspect the services and private environment backup before restarting them.

There is deliberately no automatic database downgrade: an Attendee migration may already have run. Existing volumes and the pre-migration dump are preserved. Inspect the failed release and decide whether to repair it or restore its database backup with the compatible previous image. Do not blindly switch images after migrations. The failed release directory contains its own `compose.sh` for diagnostics even if `current` still points to the previous release.

If the **first** deployment fails after containers are created, the next attempt refuses to overwrite that incomplete installation. Inspect it using its release's `compose.sh`. Once there are no bots to preserve, use that script with `down` (without `-v`) to remove the incomplete containers while retaining data, then rerun the workflow. Never remove `attendee.env` when keeping the database: that file contains its credentials and encryption key.

The private certificate lasts one year. Deployments reject a certificate expiring within seven days. During a maintenance window with no bots, stop the worker and gateway, back up the TLS files, regenerate the certificate/key with the hostname `echooo-attendee-gateway`, preserve key mode 600 and certificate mode 644, and recreate both containers. The worker loads its trusted certificate at startup. Rerun the workflow to verify routing afterward.
