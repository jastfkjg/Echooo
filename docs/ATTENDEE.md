# Independent meeting participants

Echooo can invite **Echooo AI** into an online meeting as a visible, independent participant. The browser sends a join request to Echooo; a self-hosted Attendee worker joins the meeting, and sends live audio back to Echooo over an authenticated TLS WebSocket. Closing the Echooo page does not remove the participant.

This version records silently. It does not speak, represent a person, read personal memory, or make commitments. Speech and turn-taking policies are a separate product step.

## Start locally

Requirements: Docker with Compose, Git, Python 3, OpenSSL, and working internet access to the meeting platform. Start Docker Desktop first on macOS. The upstream image targets **linux/amd64**; Apple Silicon runs it under emulation, so the first build is large and browser startup is slower.

From the Echooo project directory:

```bash
python3 scripts/attendee.py up
./start.sh
```

The setup script:

1. Downloads Attendee at commit `60e885df6f9ed0f38ef141438caac9978a38a6cc` into the ignored `.local/attendee` directory, and builds it.
2. Starts a dedicated PostgreSQL, Redis, Attendee API, single Celery worker, and private TLS gateway.
3. Creates a local Attendee organization, project, API key and dashboard account. Secrets are generated into `.local/attendee.env` with owner-only permissions.
4. Updates only `ATTENDEE_BASE_URL`, `ATTENDEE_API_KEY` and `ATTENDEE_CALLBACK_URL` in Echooo's `.env`. Existing provider settings and application data are preserved. Restart Echooo after this step.

The gateway reads Echooo's `APP_PORT` from `.env`, defaulting to 8000. If you launch Echooo with a different port, use the same port for setup, for example `ECHOOO_PORT=8010 python3 scripts/attendee.py up`, then `./start.sh --port 8010`.

The Attendee dashboard is available at [localhost:8011](http://127.0.0.1:8011). Login email: `echooo@localhost` (the dashboard accepts email, not the internal username `echooo`). Its generated password is `ECHOOO_ADMIN_PASSWORD` in `.local/attendee.env`. The bootstrap provisions and verifies this local-only address; no email delivery or Attendee cloud registration is required.

```bash
python3 scripts/attendee.py status
python3 scripts/attendee.py logs
python3 scripts/attendee.py down
```

`down` preserves the database and diagnostic-file volumes. Error screenshots and debug logs stay in the local `debug` volume and can be opened through the authenticated Attendee dashboard; no S3 account is needed. **Let the participant leave from Echooo before stopping Docker.** A normal Echooo shutdown requests departure; a crash cannot guarantee immediate departure. Attendee also receives a maximum session duration (default two hours), a ten-minute admission timeout and a one-minute alone-in-meeting timeout.

## Join a meeting

1. Open **Meetings → New meeting** in Echooo.
2. Select **Join online meeting**, paste the direct meeting URL and choose the participant name. Names retain an explicit AI label.
3. Inform participants that audio will be recorded. Admit **Echooo AI** from the platform's waiting room if needed.
4. Follow participant status and the transcript in Echooo. **In the meeting** and **audio connected** are separate signals; a joined participant may still be waiting for audio or permission.
5. Select **Leave online meeting**. Echooo immediately stops accepting audio, then waits for Attendee to confirm departure. Once it has left, audio can be played or downloaded, and the Echooo meeting can be ended.

Local browser capture and an independent participant cannot record into the same meeting simultaneously. This deployment allows **one independent participant at a time across the workspace**. Keep the Echooo server, Docker, and the host computer awake while recording.

## Platform adapters

| Platform | Integration used here | Setup and limits |
| --- | --- | --- |
| Google Meet | Attendee's automated browser joins the web meeting and captures audio | Host admission and meeting guest-access policy apply; some organizations require an authenticated Google participant. |
| Microsoft Teams | Attendee's automated browser joins the web meeting and captures audio | Use a direct meeting link. Lobby, anonymous access and tenant policy apply. |
| Zoom | Attendee's **web SDK** adapter | Add Zoom App credentials in the Attendee project's credentials page first; host permissions and Zoom app authorization rules apply. |

Attendee normally also supports a native Zoom SDK adapter. Echooo explicitly selects the web adapter and platform closed captions so Attendee does not require a second paid transcription provider. Echooo performs its own transcription from the audio stream. Upstream capture is configured as `recording_settings.format=none`; the original audio is saved in Echooo, while Attendee may retain platform captions and participant metadata in its own database.

The implementation and self-host instructions follow the pinned [Attendee source](https://github.com/attendee-labs/attendee/tree/60e885df6f9ed0f38ef141438caac9978a38a6cc). Browser admission flows can change; pinning makes upgrades reviewable but cannot prevent platform-side breakage. This integration does not bypass sign-in, admission, or recording permissions.

## Configure Zoom before joining

Missing Zoom credentials are rejected by Attendee before a participant is launched. This is separate from the `ATTENDEE_API_KEY` used by Echooo to contact Attendee.

For a first test, use a meeting hosted within the **same Zoom account as the app**:

1. Sign in to [Zoom App Marketplace](https://marketplace.zoom.us/) with that account. Choose **Develop → Build App → General App**.
2. Enable **Features → Embed → Meeting SDK**. Copy its **Client ID** and **Client Secret** from Basic Information / App Credentials. Use the credentials for the app environment you are testing.
3. Sign in to the local Attendee dashboard with email `echooo@localhost` (the password is in `.local/attendee.env`). Open the **Echooo** project's **Settings → Credentials**, then **Zoom Credentials → Add Credentials**, and save these two values there. Do not put the Zoom Client Secret in frontend code or substitute it for Echooo's Attendee API key.
4. Retry joining a meeting hosted by that Zoom account. Saving these credentials in Attendee does not require restarting Echooo. Host admission and recording permissions still apply.

See Zoom's [Meeting SDK credential setup](https://developers.zoom.us/docs/meeting-sdk/get-credentials/). A General App with Meeting SDK enabled supplies the credentials for this integration.

**Meetings hosted outside the app's Zoom account require more setup.** Zoom currently requires app review and attribution to a user via a ZAK or On Behalf Of (OBF) token. The current Echooo implementation only sends `zoom_settings.sdk=web`; it does **not yet implement the user OAuth flow or supply these tokens**. Adding Client ID / Secret alone therefore does not complete external-meeting support. See [Zoom's external-meeting requirements](https://developers.zoom.us/docs/meeting-sdk/get-credentials/) and [Attendee's managed OAuth integration](https://docs.attendee.dev/guides/zoom/zoomoauth).

For external meetings while keeping Echooo visible as an independent participant, the next integration step is a Zoom OAuth authorization flow and Attendee-managed OBF tokens. This associates the bot with its authorizing user; it does not grant the bot that person's knowledge or authority to make commitments.

## Audio, state and isolation

- The audio callback carries **16 kHz, mono PCM16**. Sub-10-ms browser chunks are combined into 100-ms transcription frames without padding the saved audio.
- Audio is saved as it arrives. A reconnect starts a separate recording to make the gap explicit; continuous sessions rotate at 30 minutes. The selected recording follows new segments while **Follow live** is enabled.
- Existing Echooo live transcription and saved-audio verification are reused. Mock STT saves audio without producing real transcripts. Speaker labels are hypotheses scoped to a recording/session, not verified meeting identities.
- Join intent is stored before contacting Attendee. An uncertain create response is reconciled using its deduplication key rather than creating another participant.
- Join, status and leave require the owner session and existing origin checks. The callback uses a separate random, per-invitation token; Echooo stores only its hash and redacts it in Uvicorn access logs. A wrong bot ID, expired token, departed participant, duplicate socket or invalid audio frame is rejected.
- Closing the page leaves the server session running. On process restart, Echooo reconciles stored participants with Attendee. If status cannot be confirmed, the page says so and continues to block duplicate joins. The host can always remove the participant directly.

## Cost and deployment boundary

Self-hosting removes the Recall/Attendee cloud per-minute fee. Docker compute, network and storage remain your responsibility; **the configured AssemblyAI and LLM providers can still charge for transcription and notes**. This change does not introduce a free local speech model.

Attendee uses the [Elastic License 2.0](https://github.com/attendee-labs/attendee/blob/60e885df6f9ed0f38ef141438caac9978a38a6cc/LICENSE). It is source-available software with license conditions, not an unrestricted MIT component.

The supplied Compose stack is **for a local workstation**: its Django development dashboard binds only to `127.0.0.1`, and the audio gateway is reachable only on the Docker network. Its private certificate is valid for one year; renew it before expiry and restart the gateway and worker together. Do not publish this development dashboard to the internet. A remote deployment needs a production application server, durable storage, TLS and a callback hostname reachable by its workers. Continue to run one Echooo application worker; scaling meeting concurrency requires isolated bot runtimes and shared lifecycle coordination.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Join button is disabled | Start Attendee, ensure all three connector settings are present, and restart Echooo. |
| Waiting for the host | Admit Echooo AI and check the meeting's guest-access policy. |
| Zoom request rejected | Configure Zoom App credentials in the Attendee project and check Zoom authorization requirements. |
| In the meeting, no audio | Check host permission, the participant microphone, gateway port and worker-to-Echooo connectivity. |
| Audio saves but transcription reconnects | Inspect Echooo provider configuration/network. Saved audio is retained for verification. |
| Departure remains unconfirmed | Keep services running so retries can complete, or remove Echooo AI using the meeting host controls and inspect the Attendee dashboard. |

Do not share `.local/attendee.env`, the private TLS key, or raw upstream logs that may contain meeting links/callback credentials.

## Verification record

On 2026-09-12, the pinned deployment was built and run on Apple Silicon. A user-provided Google Meet was joined twice as **Echooo AI**. The first run verified admission, audio persistence and confirmed departure. The second verified non-silent audio, 19 live transcript passages with valid recording-relative timestamps, and continued capture after navigating away from the Echooo page and returning. Saved-audio verification completed with 26 passages and generated meeting notes. Both participants were confirmed departed. The small browser audio frames discovered in this test are now coalesced before transcription.

The automated suite passed 152 Python tests (one optional PostgreSQL test skipped) and 58 JavaScript tests. Connector tests cover owner isolation, URL validation, duplicate prevention, ambiguous create recovery, departure failure, callback authentication, stream identity, audio preservation, frame coalescing, independent sample rates and duration expiry. Desktop and mobile browser controls were exercised with no browser console errors. Local diagnostic storage was checked for write/read, login, signed-URL integrity and organization isolation. After restarting the services, TLS callback authentication and actual Uvicorn token redaction were verified. Zoom and Teams request schemas were checked against the running Attendee serializer; **live Zoom/Teams meetings have not yet been tested**.
