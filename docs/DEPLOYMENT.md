# Manual cloud deployment

This deployment runs one Echooo application worker, PostgreSQL 17, and Caddy with HTTP IP access or automatic domain HTTPS on a Linux server. GitHub Actions runs only when **Deploy → Run workflow** is selected. Pushes and merges do not deploy. Choose a trusted branch in the dropdown; the workflow must first exist on the repository's default branch and on the selected branch. Server files and secrets are not committed to Git.

This is an invitation-based test environment, not public multi-user registration. Each instance has one owner. Attendee is not included; the existing local Attendee stack requires separate cloud configuration. Browser recording, knowledge, chat, and guest invitations are included. Mock providers are the initial default; configure live providers for real AI and transcription.

## 1. Prepare the server

Use a Linux server with Docker Engine and Docker Compose v2 (including `up --wait`), Bash, Python 3, curl, tar, OpenSSH, and flock (util-linux). See [Docker's installation instructions](https://docs.docker.com/engine/install/). Both amd64 and arm64 images are built. Ports 80 and 443 must be free; if the server already runs a reverse proxy, adapt this stack before deployment.

Create a dedicated `deploy` user, allow its SSH key, and grant Docker access. Docker group membership is effectively root access: grant deployment permissions only to trusted maintainers. As a server administrator:

```bash
sudo useradd --create-home --shell /bin/bash deploy
sudo usermod -aG docker deploy
sudo install -d -m 700 -o deploy -g deploy /opt/echooo
sudo install -d -m 700 -o deploy -g deploy /opt/echooo/releases /opt/echooo/backups
```

Skip user creation if that user already exists. Install the deployment public key in `/home/deploy/.ssh/authorized_keys` with directory mode 700 and file mode 600, owned by deploy. Reconnect after changing group membership. Confirm `docker info` works as deploy without sudo.

For HTTP IP testing, no domain or certificate is needed; allow inbound TCP 80. For HTTPS, point a domain's A record to the server. Only set AAAA if IPv6 routing actually works. Allow inbound TCP 80/443 and your SSH port in the cloud firewall. GitHub-hosted runners must be able to reach SSH; a firewall allowing only your laptop will block deployment. The app and database publish no host ports. Allow outbound access to Alibaba Cloud ACR and Docker Hub, certificate authorities, and the configured model providers.

Obtain the server SSH host public key/fingerprint from the cloud console or another trusted channel. `SSH_KNOWN_HOSTS` must contain its OpenSSH known_hosts entry, such as `server.example.com ssh-ed25519 AAAA...`; use `[server.example.com]:2222` for a non-default port. Do not trust an unverified `ssh-keyscan` result.

## 2. Configure server secrets

Copy the two examples from this checkout to the server:

```bash
scp deploy/cloud/deploy.env.example deploy@SERVER:/opt/echooo/deploy.env
scp deploy/cloud/app.env.example deploy@SERVER:/opt/echooo/app.env
```

Add `-P PORT` if using a custom SSH port. As deploy on the server:

```bash
chmod 600 /opt/echooo/deploy.env /opt/echooo/app.env
openssl rand -hex 32
```

Edit `/opt/echooo/deploy.env`:

```dotenv
DOMAIN=39.106.102.121
PUBLIC_SCHEME=http
COOKIE_SECURE=false
ACME_EMAIL=
POSTGRES_PASSWORD=the_64_hex_characters_generated_above
```

Use exactly 64 hex characters for the database password. This avoids URL escaping problems. Do not change it after database initialization without also changing the PostgreSQL role password. The application URL and database URL are set by Compose. `PUBLIC_SCHEME=http` selects the HTTP proxy, and `COOKIE_SECURE=false` allows login cookies over HTTP. `ACME_EMAIL` is unused in this mode. Visit `http://39.106.102.121` after deployment. HTTP sends credentials and content without TLS; use it only for temporary testing. Browser microphone and screen capture require a secure context and are unavailable over a public HTTP IP address.

To switch to domain HTTPS, use:

```dotenv
DOMAIN=echooo.your-domain.com
PUBLIC_SCHEME=https
COOKIE_SECURE=true
ACME_EMAIL=you@your-domain.com
```

Keep the existing database password. Re-run the manual deployment to apply the proxy, origin, and cookie settings together. Existing configurations without `PUBLIC_SCHEME` or `COOKIE_SECURE` default to HTTPS with secure cookies. Deployment rejects mismatched cookie/scheme settings before stopping the application. These modes select one public origin per deployment; concurrent IP and domain sessions are not configured.

Edit `/opt/echooo/app.env` using the root `.env.example` as the provider reference. Start with mock providers for the first deployment. For live chat/transcription, configure the provider names, keys, model, and reachable endpoints. `localhost` inside a container is not the host server. Quote literal values containing `$` with single quotes in env files to prevent Compose interpolation. Never put secrets into the Dockerfile or image.

Create a namespace and image repository in Alibaba Cloud Container Registry (ACR). Copy the **public registry hostname** from the repository's push/pull instructions. Personal Edition and Enterprise Edition have different hostname formats; use the console value rather than constructing it. Enable public access and ensure access rules permit the GitHub runner and cloud server. This workflow uses the same public endpoint for pushing and pulling.

As **deploy** on the server, log in to that exact hostname:

```bash
docker login YOUR_ACR_REGISTRY --username YOUR_ACR_USERNAME
```

Enter the ACR registry access password interactively. This is the Docker registry credential configured in ACR, not an Alibaba Cloud console password or an AccessKey secret. Use an account authorized to pull the repository. The workflow's account must also have push permission. Server credentials remain on the server; changing GitHub Secrets does not update them. See the official [Personal Edition](https://www.alibabacloud.com/help/en/acr/user-guide/use-a-container-registry-personal-edition-instance-to-push-and-pull-images) and [Enterprise Edition](https://www.alibabacloud.com/help/en/acr/getting-started/use-a-container-registry-enterprise-edition-instance-to-push-and-pull-images) instructions.

## 3. Configure GitHub

Commit and push the deployment files. Put the workflow on the default branch once; this does not deploy anything. No GitHub Environment is required. Configure repository-level values at **Settings → Secrets and variables → Actions**. Anyone allowed to modify and deploy trusted branches can run code with deployment credentials.

In the **Secrets** tab, add:

| Secret | Value |
| --- | --- |
| `SSH_HOST` | Server IPv4 address or hostname, without a scheme |
| `SSH_PORT` | SSH port, optional; defaults to 22 |
| `SSH_USER` | `deploy` |
| `SSH_KEY` | Full private key matching the authorized public key |
| `SSH_KNOWN_HOSTS` | Verified known_hosts entry for that host and port |
| `ACR_USERNAME` | ACR Docker registry login username with push permission |
| `ACR_PASSWORD` | ACR Docker registry access password |

In the **Variables** tab, add:

| Variable | Value |
| --- | --- |
| `ACR_REGISTRY` | Public registry hostname from the ACR console; no protocol, path, or trailing slash |
| `ACR_NAMESPACE` | Existing namespace, for example `my-team` |
| `ACR_REPOSITORY` | Existing image repository, for example `echooo` |

The resulting image is `ACR_REGISTRY/ACR_NAMESPACE/ACR_REPOSITORY:COMMIT_SHA`. The server deploys its immutable `@sha256:...` digest. Supported registry hostnames include `registry.cn-hangzhou.aliyuncs.com`, `crpi-xxxx.cn-hangzhou.personal.cr.aliyuncs.com`, and `my-instance-registry.cn-hangzhou.cr.aliyuncs.com`. Replace these examples with your own console values.

Enable Actions; GitHub Packages permissions and a GitHub registry token are not needed. The Echooo application image is published to ACR. Python build images and the PostgreSQL/Caddy service images still come from Docker Hub, so both the runner and server need access to that registry.

If you already deployed the earlier configuration, stop the old Compose project and preserve its database volume before switching: the project name is now `echooo`, which changes automatically generated volume names. Reattach the existing volume explicitly in Compose or restore a tested backup; otherwise the new project starts with a fresh database. Existing server provider env files remain usable. Create the renamed repository secrets; old environment-scoped secrets are not read by this workflow.

## 4. Deploy and create the owner

Open **Actions → Deploy → Run workflow**, select the branch, and run it. It tests Python and JavaScript, smoke-tests the Docker image against disposable PostgreSQL, validates Caddy, publishes both architectures, and deploys the immutable image digest. Concurrent deployments are serialized in GitHub and on the server.

The server pulls images before downtime, stops the old application, creates a database dump, starts the new release, and checks the configured HTTP or HTTPS URL. Existing voice/meeting connections are interrupted: publish between testing sessions. A release is marked current only after health checks succeed. `/health` is service liveness, not an end-to-end provider check.

For the first deployment, connect to the server as deploy and run:

```bash
bash /opt/echooo/current/compose.sh exec app python /app/deploy/cloud/create_owner.py
```

Enter the owner name and a password of at least 16 characters interactively. Public `/api/auth/setup` is blocked by Caddy, so visitors cannot claim the initial workspace. Open your configured URL and sign in. The setup command refuses to create another owner.

Check:

- The configured HTTP IP or HTTPS domain loads and owner login works; HTTPS has no certificate errors.
- `/api/auth/setup` returns 403 through the public domain.
- Chat and guest invitations work; guests cannot browse owner data.
- With live providers and HTTPS enabled, microphone transcription and speech work.
- A short meeting recording remains available after an application restart.

When provider settings change, restart with recreation to apply them:

```bash
bash /opt/echooo/current/compose.sh up -d --no-deps --force-recreate --wait app
```

## 5. Logs, backups, and recovery

```bash
bash /opt/echooo/current/compose.sh ps
bash /opt/echooo/current/compose.sh logs --tail 100 app proxy
```

Every deployment creates `/opt/echooo/backups/TIMESTAMP-RELEASE.dump`. PostgreSQL contains meeting audio as well as text, so monitor disk usage. Docker logs rotate. Database backups are not automatically deleted or copied off-server; establish a retention schedule and off-server backup before storing important data. To create an additional consistent database backup:

```bash
umask 077
bash /opt/echooo/current/compose.sh exec -T db pg_dump -U echooo -d echooo -Fc > /opt/echooo/backups/manual-$(date -u +%Y%m%dT%H%M%SZ).dump
```

This uses PostgreSQL's consistent snapshot; deployment backups additionally stop the app before migrations. Restore-test dumps in an isolated PostgreSQL instance with `pg_restore --exit-on-error --no-owner --dbname=TEST_DATABASE BACKUP.dump`. Never restore over a live database as an experiment. Back up server env files securely as well. Database/HTTPS volumes persist across releases; **never run `down -v`** unless deliberately deleting this environment.

A failed deployment may leave the app stopped or the candidate version running; the workflow fails and does not move the `current` link. Use the failed release path printed in Actions with `bash /opt/echooo/releases/RELEASE/compose.sh logs --tail 100` to diagnose. A failure after application startup may already have applied database migrations. No automatic rollback or destructive restore is attempted.

For a known database-compatible rollback, stop the failed/current application and start the last good release under the same deployment lock:

```bash
(
  flock -n 9 || exit 1
  # If the last deployment failed, current is still the last successful release.
  # After a successful but unwanted deployment, use /opt/echooo/previous instead.
  good=/opt/echooo/current
  bash "$good/compose.sh" stop app
  bash "$good/compose.sh" up -d --wait --wait-timeout 180
) 9>/opt/echooo/deploy.lock
```

After rolling back to `previous`, update the current link to that release and verify the configured public URL. Rollback also restores that release's Compose/Caddy files, but uses today's server env files. For incompatible schema changes, stop the app and plan a database restore from the matching pre-deploy dump; this loses writes made after that backup. Retain the image digest in ACR and the corresponding release directory as long as you need rollback.

The standard Caddy image does not add comprehensive request-rate limits or model-spending quotas. Keep this environment invitation-only; add an appropriate edge access/rate-control layer before broader exposure. Use a separate instance and database per tester if independent owner workspaces are required.

## Local container check

With Docker running, from the repository root:

```bash
bash deploy/cloud/smoke-test.sh
```

This builds the image, tests PostgreSQL startup, static assets and owner creation with mock providers, and validates both Caddy modes. Its temporary containers, database volume, network, and image are removed on exit. It does not connect to the cloud server or test public certificate issuance.

## ACR manifest compatibility

The publish step disables provenance and SBOM attestations and explicitly exports Docker media types (`oci-mediatypes=false`). This avoids the OCI attestation artifact format rejected by some ACR Personal Edition registries with `unknown manifest class for application/vnd.oci.empty.v1+json`. Both CPU architectures and deployment by digest remain enabled. Published images do not include provenance/SBOM attestations; commit revision labels are retained.

After updating the workflow, start a new **Deploy → Run workflow** from the branch containing the fix. Re-running an older failed run uses its older workflow revision.
