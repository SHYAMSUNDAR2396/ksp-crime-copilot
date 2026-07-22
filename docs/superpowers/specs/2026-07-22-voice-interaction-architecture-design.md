# Voice Interaction Architecture Design

**Status:** Approved design
**Date:** 2026-07-22
**Purpose:** Kannada-English voice interaction for the KSP Crime Copilot

## 1. Purpose and Coverage

The voice experience must let an officer ask a Kannada, English, or mixed-language question, interrupt an answer naturally, and receive a cited response in the requested language. It must preserve the existing Catalyst query, evidence, citation, and rank-derived authorization behavior.

The prototype is desktop-browser first, with a mobile-compatible layout and graceful text fallback. Browser speech APIs are acceptable for the prototype. Production must support replacing them with a dedicated multilingual streaming provider without changing Catalyst's reasoning contract.

## 2. System Boundary

```text
Desktop browser
  -> microphone capture
  -> client-side VAD
  -> stop current TTS immediately
  -> speech recognition adapter
  -> transcript + language segments
  -> Catalyst API Gateway
  -> authentication and rank-derived RBAC
  -> deterministic entity protection
  -> Kannada/English normalization
  -> SQL/evidence pipeline
  -> cited answer
  -> browser TTS adapter
```

### Browser responsibilities

- Request microphone access after an explicit user action.
- Detect speech start and stop using actual audio energy/VAD; recognition lifecycle events are not VAD.
- Cancel local TTS and abort the previous request when a new turn begins.
- Assign a monotonically increasing `turn_id` and reject stale responses.
- Show partial ASR text for feedback, but submit only final transcripts to Catalyst.
- Use provider-neutral recognizer and synthesizer interfaces.
- Use browser Web Speech APIs for the prototype and retain a typed-input fallback.

### Catalyst responsibilities

- Authenticate the caller and enforce rank-derived capability and unit scope.
- Validate transcript metadata and use the existing SQL, evidence, citation, translation, and audit pipeline.
- Protect crime numbers, case IDs, names, places, dates, sections, and numeric values before linguistic translation.
- Normalize mixed-language linguistic content without silently changing protected entities.
- Return a cited answer, language, voice text, and the original `turn_id`.
- Avoid raw-audio storage by default.

Catalyst remains request/response oriented. Real-time microphone capture, VAD, streaming ASR, and TTS playback belong in the browser or a dedicated voice provider adapter. Catalyst Functions may integrate a provider for server-side workflows, but the client must still own interruption and stale-response behavior.

## 3. Turn Lifecycle and API Contract

Each utterance is an independent turn. The browser increments `turn_id` before it starts recognition.

```text
speech_started
  -> increment turn_id
  -> cancel current TTS
  -> abort prior request
  -> start recognizer
  -> display partial transcript locally
  -> submit final transcript
  -> accept response only when response.turn_id == current turn_id
  -> speak and render accepted answer
```

`AbortController.abort()` stops the client from waiting; it does not guarantee that a backend computation has stopped. The server must echo `turn_id`, and the client must perform the final stale-response check. A stale result may be recorded for operational telemetry but must never be rendered as the current answer or spoken aloud.

### Request

```json
{
  "employee_id": 9,
  "session_id": "session-abc",
  "turn_id": 12,
  "input_mode": "voice",
  "transcript": "Koramangala alli theft cases yesterday beku",
  "language_segments": [
    {"text": "Koramangala alli", "language": "mixed"},
    {"text": "theft cases yesterday beku", "language": "mixed"}
  ],
  "response_language": "kn",
  "client_capabilities": {
    "supports_abort": true,
    "supports_streaming_tts": false
  }
}
```

The authenticated principal is authoritative for identity. `employee_id` may remain temporarily for backward compatibility with the current pure core, but the Catalyst handler must validate it against the authenticated caller before authorization.

### Response

```json
{
  "turn_id": 12,
  "refused": false,
  "answer": "ನಿನ್ನೆ Koramangala ನಲ್ಲಿ ...",
  "language": "kn",
  "citations": ["FIR-2026-0012"],
  "voice": {
    "speak": true,
    "text": "ನಿನ್ನೆ Koramangala ನಲ್ಲಿ ...",
    "language": "kn-IN"
  }
}
```

The existing text request shape remains supported. Voice-specific fields are additive, and the current `handle_question` behavior remains the compatibility baseline.

## 4. Voice Adapter Design

The frontend owns three provider-neutral interfaces:

```text
VoiceActivityDetector
  -> speech_started / speech_stopped

SpeechRecognizer
  -> partial_transcript
  -> final_transcript
  -> language_segments
  -> error

SpeechSynthesizer
  -> speak(text, language, turn_id)
  -> cancel(turn_id)
  -> finished / error
```

### Prototype

- Use `getUserMedia` and browser audio analysis or an energy gate for speech detection.
- Use browser speech recognition for Kannada and English input.
- Use `speechSynthesis` for output.
- Treat `webkitSpeechRecognition.onstart` as recognizer status only, never as evidence that the user is speaking.
- Cancel speech synthesis immediately on VAD speech start.
- Speak sentence-sized chunks where possible, with each chunk tagged by `turn_id`.
- Support Kannada-English code-switching within one utterance.
- Leave room for optional diarization if multi-speaker support is introduced later.

### Production replacement

The same interfaces must support a dedicated multilingual provider with streaming Kannada-English ASR, improved noise/accent handling, provider-side or server-side VAD, streaming TTS, audio cancellation, and optional diarization. Provider selection, data residency, retention, and service-level requirements are deployment decisions and must not leak into the Catalyst query contract.

## 5. Catalyst Processing Flow

```text
API Gateway
  -> authentication
  -> rank-derived capability check
  -> request validation
  -> deterministic entity protection
  -> language/code-switch analysis
  -> English query normalization
  -> SQL and evidence pipeline
  -> citation validation
  -> response translation
  -> audit logging
```

The current `functions/crime_query/main.py` remains the starting point. The voice path should extend its pure request core or add a thin voice-aware wrapper rather than creating a second query engine.

### Safe normalization rules

1. Preserve the original transcript for audit and troubleshooting.
2. Detect and protect identifiers deterministically before translation or LLM normalization.
3. Protect crime numbers, case IDs, names, locations, dates, section numbers, and numeric values when they are known or structurally identifiable.
4. Allow the LLM to normalize linguistic connectors and intent, but never silently rewrite protected values.
5. Validate generated SQL and returned identifiers against the protected values.
6. Preserve citations and identifying result values through the Kannada response translation.
7. Return a safe text answer if translation or TTS is unavailable; never invent a voice response.

The current binary `translate.detect` behavior is sufficient as a compatibility fallback, but the voice path must retain segment metadata and allow Catalyst to reclassify mixed utterances. Language detection must not determine authorization or entity identity.

## 6. State, Evidence, and Audit

`session_id` may identify cached conversational context, but every request must remain independently authorized. The backend must not rely on client state alone for access decisions.

Audit records should include:

- request id, session id, `turn_id`, authenticated principal, and capability;
- input mode, language segments, response language, and timing;
- ASR/TTS provider and model version when available;
- authorization result, refusal reason, generated-query metadata, citations, and stale-response status;
- translation and voice errors without storing raw audio by default.

Transcript retention must follow the project's privacy and operational policy. Client console logs must not contain unrestricted transcripts or sensitive identifiers.

## 7. Failure Handling

| Failure | Required behavior |
|---|---|
| Microphone denied | Offer typed input immediately |
| No speech detected | Show a recoverable prompt |
| ASR unavailable | Offer retry and text fallback |
| Backend timeout | Stop pending speech and show retry |
| Translation unavailable | Show the safe original-language text response |
| Stale response | Discard silently; never speak or render it as current |
| TTS failure | Keep the answer and citations visible as text |
| Session expiry/RBAC denial | Require re-authentication or show refusal |

## 8. Security and Privacy

- Enforce Catalyst authentication and rank-derived RBAC on every voice request.
- Treat browser metadata, language segments, and client-supplied `employee_id` as untrusted.
- Apply the same refusal, row filtering, citation, and masking rules to text and voice.
- Request microphone permission only after explicit action and expose a clear recording state.
- Do not persist raw audio by default; define transcript and audit retention before pilot deployment.
- Redact sensitive values from browser telemetry and provider diagnostics.
- Use throttling and abuse controls at the API Gateway.

## 9. Verification Strategy

The prototype must test:

- VAD start/stop and false-trigger behavior;
- TTS cancellation while a new utterance begins;
- abort and stale-response races;
- partial transcripts never entering SQL generation;
- Kannada, English, and mixed-language utterances;
- protected crime numbers, names, locations, dates, and sections;
- RBAC denial through voice requests;
- translation, ASR, backend, and TTS fallbacks;
- text/voice parity and citation preservation;
- desktop behavior and mobile-compatible layout.

Production readiness additionally requires real Kannada-English speech evaluation, latency/error telemetry, provider health monitoring, retention controls, and a documented incident path for incorrect transcription or authorization.

## 10. Rollout

1. **Prototype:** browser ASR/TTS, desktop-first UI, mobile-compatible layout, text fallback, no audio persistence, no streaming requirement.
2. **Pilot:** evaluate real Kannada-English code-switching, measure latency and recognition errors, test stale-turn behavior, and review audit data.
3. **Production:** replace browser speech adapters with a dedicated multilingual streaming provider, add robust VAD and streaming cancellation, enable provider monitoring, and finalize privacy/retention controls.

## 11. Open Decisions Before Production

- Select and approve the Kannada-capable ASR/TTS provider.
- Decide whether provider audio flows directly from the browser or through a controlled gateway.
- Define transcript and audit retention periods and data residency requirements.
- Define target latency for speech-start cancellation, final transcript, first answer token, and first spoken chunk.
- Confirm whether future WhatsApp/Telegram voice channels share this contract or use a separate adapter.
