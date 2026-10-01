# Gemini 3.8 Live avatars in Echo

Verified against Google's documentation and a live Cloud session on 2026-10-02.

## Choose the correct platform

`gemini-3.8-live` supports ordinary audio conversations through both the Google
Developer API (AI Studio) and Google Cloud. Avatar output is a Cloud capability:
use Echo's **Google Agent Platform** provider. There is no separate
`gemini-3.8-live-avatar` Google model. Echo now represents avatars as a session
mode of the real model. Existing saved avatar aliases are recovered onto that
Cloud mode. Ordinary AI Studio voice calls remain available.

Sources: [Cloud avatar setup](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/configure-live-avatars),
[Developer API model](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live).

## Get access and configure credentials

1. Select your Google Cloud project, enable billing and the Agent Platform API
   (`aiplatform.googleapis.com`), and give the calling identity the appropriate
   model invocation permission (for example, the Vertex AI User role,
   `roles/aiplatform.user`). Your Cloud administrator may need to do this.
2. Use **Cloud Console → Agent Platform → Studio → Stream realtime**, choose
   `gemini-3.8-live`, and select **Live Avatar** to verify project access and
   available prebuilt avatar/voice names.
3. Authenticate on the computer running Echo's backend with
   `gcloud auth application-default login`, or use a service-account JSON file.
   An AI Studio API key does not authenticate the regional avatar connection.
4. In **Echo → Settings → Google Agent Platform**, enter your **project ID**,
   **region**, and optionally the **service-account JSON file path**. Save.
   A path refers to a file on the backend computer; Echo does not upload it to
   the browser. ADC is used if no service-account file is selected.

The documented regions for this model are `us-central1`, `us`, and `eu`.
Use `us-central1` initially. OAuth credentials stay in the backend, which uses
the regional Live API connection. Google lists the model as generally available;
this does not guarantee that every project has the required permissions or quota.

Sources: [Cloud model availability](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-live),
[session authentication](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/start-manage-session),
[Cloud quickstart](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start?usertype=adc).

## Start an avatar conversation

1. In Chat's call settings/model picker choose **Google Agent Platform →
   Gemini 3.8 Live · Avatar**. This explicitly enables avatar mode, closes the
   menu, and keeps Chat open. The summary displays **Avatar · Ben**.
   Choose the ordinary `gemini-3.8-live` entry to return to audio mode.
2. The **Live Avatar** controls and player appear in the composer immediately.
   The default prebuilt face is **Ben**.
   To use another prebuilt face, enter its exact name from the Cloud console's
   Avatar list. Google does not provide a complete prebuilt-face catalog in the
   linked setup guide, so Echo does not invent additional face names.
3. Choose a voice using the call settings picker, then click the call button.
   The microphone supplies your audio and the avatar appears in the same Chat.
4. If the browser blocks audible autoplay, click Play on the avatar video.
   Stop the call using the normal hang-up control. Face and mode controls are
   disabled while a call is active because the setup is fixed per connection.

Echo sends `response_modalities=["VIDEO"]`, the selected
`avatar_config.avatar_name`, and `speech_config` to `gemini-3.8-live`.
No Tavus face/persona or separate agent deployment is required.

## Custom faces

Google limits reference-image avatars to select customers. Request access from
your **Google Cloud account team**. That entitlement is separate from using a
prebuilt face such as Ben. This Echo flow supports prebuilt names; it does not
offer custom-face uploads or imply that an API key grants custom-face access.

Source: [custom-avatar access](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/configure-live-avatars#use_a_custom_avatar).

## Implementation and verification

The backend uses a regional Cloud SDK client with OAuth credentials and never
changes the process-wide credential environment. Incoming inline data is split
by MIME type. SDK `response.data` combines *all* inline data, including video,
and must not be blindly interpreted as PCM.

A real Ben/Puck session returned fragmented MP4 containing H.264 video at
704×1280, 24 FPS, and an AAC-LC voice track. Echo plays that muxed stream through
MediaSource, preserving packet order without React state batching. The voice
track plays with the video; separate PCM parts, when present, use the existing
audio path. Interruption resets queued video along with speech; closing the call
or unmounting releases the media source and object URL. Playback retains a
bounded window instead of accumulating an entire long call.
Google sends the MP4 initialization segment only once per session. Echo retains
it across an interruption and prepends it when rebuilding playback for the next
reply; ending a session clears it.

Verification included an actual Cloud handshake and response, codec inspection,
and replaying those real packets through Echo's playback class in headless
Chrome: both audio and video decoded, playback advanced, and reset removed the
media source. Automated tests cover configuration, routing, packet ordering,
interruption, and cleanup. This browser check does not establish playback in
every packaged PyWebView or Electron runtime; their installed codecs and
autoplay policies still apply.
