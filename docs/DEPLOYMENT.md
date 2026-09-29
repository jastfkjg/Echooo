# Manual cloud deployment

This deployment runs one Echooo application worker and PostgreSQL 17 behind the independent jastcraft-infra Caddy gateway on a Linux server. GitHub Actions runs only when **Deploy → Run workflow** is selected. Pushes and merges do not deploy. Choose a trusted branch in the dropdown; the workflow must first exist on the repository's default branch and on the selected branch. Server files and secrets are not committed to Git.

This is an invitation-based test environment, not public multi-user registration. Each instance supports multiple independent owner accounts, provisioned through trusted server access. Attendee is not included; the existing local Attendee stack requires separate cloud configuration. Browser recording, knowledge, chat, and guest invitations are included. Mock providers are the initial default; configure live providers for real AI and transcription.

## 1. Prepare the server and independent gateway

Use Linux, Docker Engine, Docker Compose v2.24+, Bash, Python3, curl, tar, OpenSSH and flock. Keep the existing `echooo` Compose project name and PostgreSQL volume. The deployment account needs Docker access and write access to `/opt/echooo`, including `releases` and `backups`.

Caddy is now managed by the separate `jastcraft-infra` repository. Follow its migration runbook before deploying this version. It creates `echooo_proxy`, attaches the gateway, preserves the existing Caddy certificate volumes, and transfers ports 80/443. This repository deploys only app/db. Do not run the old deployment workflow after gateway migration.

The application joins its default database network and `echooo_proxy` with alias `echooo-upstream`; PostgreSQL only joins the default network. Neither service publishes host ports. The gateway preserves the public owner-setup block, 25MB request limit, and streaming proxy settings.

## 2. Configure server secrets

Preserve existing `/opt/echooo/app.env` and `/opt/echooo/deploy.env` (mode 600). For a new instance, copy their examples from `deploy/cloud`. Set deploy.env to the actual public origin:

```dotenv
DOMAIN=echooo.your-domain.com
PUBLIC_SCHEME=https
COOKIE_SECURE=true
POSTGRES_PASSWORD=the_existing_64_hex_character_password
```

Do not change the database password during gateway migration. If currently serving HTTP, preserve `PUBLIC_SCHEME=http` and `COOKIE_SECURE=false` and configure the gateway's ECHOOO_ADDRESS to the same `http://IP`. Migrate to domain HTTPS separately, changing both gateway route and application origin/cookie settings. ACME_EMAIL now belongs only to the gateway environment. Domain HTTPS is needed for secure browser recording.

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

Enable Actions; GitHub Packages permissions and a GitHub registry token are not needed. Actions publishes the Echooo application and mirrors the official PostgreSQL image to the same ACR repository under `deps-postgres-*` tags. Both immutable digests are saved in each release's `image.env`. No extra ACR repositories, variables, or credentials are needed. Only the GitHub runner needs Docker Hub access for builds and smoke tests; the server pulls all service images from ACR. Keep dependency tags/digests when configuring registry cleanup or retaining rollback releases.

If you already deployed the earlier configuration, stop the old Compose project and preserve its database volume before switching: the project name is now `echooo`, which changes automatically generated volume names. Reattach the existing volume explicitly in Compose or restore a tested backup; otherwise the new project starts with a fresh database. Existing server provider env files remain usable. Create the renamed repository secrets; old environment-scoped secrets are not read by this workflow.

## 4. Deploy and create the owner

Open **Actions → Deploy → Run workflow**, select the branch, and run it. It tests Python and JavaScript, smoke-tests the Docker image against disposable PostgreSQL, publishes both architectures, and deploys the immutable image digest. Concurrent deployments are serialized in GitHub and on the server.

The server pulls images before downtime, stops the old application, creates a database dump, starts the new release, and checks the configured HTTP or HTTPS URL. Existing voice/meeting connections are interrupted: publish between testing sessions. A release is marked current only after health checks succeed. `/health` is service liveness, not an end-to-end provider check.

For the first deployment, connect to the server as deploy and run:

```bash
bash /opt/echooo/current/compose.sh exec app python /app/deploy/cloud/create_owner.py
```

Enter the owner name and a password of at least 16 characters interactively. Public `/api/auth/setup` is blocked by Caddy, so visitors cannot claim the initial workspace. Open your configured URL and sign in. Without flags, the setup command still refuses to create another owner.

### Add a judge/demo account

After deploying the updated application, run on the server:

```bash
bash /opt/echooo/current/compose.sh exec app python /app/deploy/cloud/create_owner.py --additional
```

Enter `judge-demo` and a unique password of 16–200 characters at the prompts. Passwords are not passed as command-line arguments or printed. Duplicate names are rejected without changing the existing account. The new account starts with an empty `default` domain; existing accounts, sessions, and data remain intact. Public registration remains closed.

Sign in using a separate browser profile and populate only synthetic demo meetings and knowledge. Each account can access only its own workspace, including uploads, chats, meeting recordings, exports, and live connections. Guest invitations still grant access only to their designated conversation. Share demo credentials through the submission platform's private credential field, never in this repository or public README.

Newly cloned voices belong to their creating account. Provider voices created before ownership tracking remain available to the original account. Explicitly configured server voice presets remain shared.

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
bash /opt/echooo/current/compose.sh logs --tail 100 app
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

After rolling back to `previous`, update the current link to that release and verify the configured public URL. Rollback uses that release's business Compose and today's server env files. Never run a pre-gateway-split Compose release with whole-stack up: it would recreate the old proxy. To restore older application code, use the new split Compose with the older app digest and the current database image. For incompatible schema changes, stop the app and plan a database restore from the matching pre-deploy dump; this loses writes made after that backup. Retain the image digest in ACR and the corresponding release directory as long as you need rollback.

The standard Caddy image does not add comprehensive request-rate limits or model-spending quotas. Keep this environment invitation-only; add an appropriate edge access/rate-control layer before broader exposure. Accounts have independent workspaces within the same instance. Provider credentials, configured voice presets, infrastructure, and usage limits remain server-wide; use separate deployments when those resources also need isolation.

## Local container check

With Docker running, from the repository root:

```bash
bash deploy/cloud/smoke-test.sh
```

This builds the image, tests PostgreSQL startup, static assets and owner creation with mock providers, without managing the independent gateway. Its temporary containers, database volume, network, and image are removed on exit. It does not connect to the cloud server or test public certificate issuance.

## ACR manifest compatibility

The publish step disables provenance and SBOM attestations and explicitly exports Docker media types (`oci-mediatypes=false`). This avoids the OCI attestation artifact format rejected by some ACR Personal Edition registries with `unknown manifest class for application/vnd.oci.empty.v1+json`. Both CPU architectures and deployment by digest remain enabled. Published images do not include provenance/SBOM attestations; commit revision labels are retained.

After updating the workflow, start a new **Deploy → Run workflow** from the branch containing the fix. Re-running an older failed run uses its older workflow revision.

## Deployment preflight and server compatibility

Before building images, Actions checks SSH connectivity, readable env files, directory permissions, Docker daemon access, and host tooling (Compose 2.24+, Python 3.6+). You can run `bash deploy/cloud/preflight.sh` on the server independently. It does not restart services.

After pulling the candidate images, deployment validates the application settings in disposable containers without starting app migrations. For an existing running database it also checks the configured application database credentials before stopping the old app. The old app is then stopped and the existing database backed up before any database container recreation. Health checks use a bounded shell retry loop compatible with older curl versions, including 7.61.1; TLS verification remains enabled for HTTPS.

Host checks do not validate live model-provider credentials or provider quotas. A successful HTTP health response is not an end-to-end voice/LLM test. If an earlier release failed after startup, containers may already be healthy while `/opt/echooo/current` is absent; the next successful deployment creates that link. No database rollback is automatic.
