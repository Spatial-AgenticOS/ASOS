# v2 mobile porting plan

> The ambient-OS design language lives in `feral-client-v2/`. This doc
> maps each web design token / primitive onto its iOS + Android equivalent
> so the three persona-critical screens (Orb, Chat, Voice) can be rebuilt
> on both platforms without drift.
>
> Scope of the initial v2 mobile drop: **tokens only**. Screen rewrites
> require a signed Xcode + working Android SDK build environment to
> verify; they are deliberately left to a follow-up commit by a dev
> running on those toolchains, per the "never claim something works until
> you've verified end-to-end" rule in `ASOS/AGENT_PROMPT.md`.

## 1. Token parity (shipped in this commit)

| Web token file | iOS token file | Android token file |
|---|---|---|
| [`feral-client-v2/src/styles/tokens.css`](../feral-client-v2/src/styles/tokens.css) | [`ios-app/App/FeralV2Tokens.swift`](ios-app/App/FeralV2Tokens.swift) | [`android-app/src/main/java/ai/feral/node/FeralV2Tokens.kt`](android-app/src/main/java/ai/feral/node/FeralV2Tokens.kt) |

All three files declare the same palette, type scale, radii, and motion
constants. If you update one, update all three **in the same commit** per
the systematic-sync rule in `ASOS/AGENT_PROMPT.md`.

## 2. Persona-critical screens to port (follow-up work)

Only these three screens define the "one FERAL across every device"
feeling. Everything else can migrate later.

### 2.1 Ambient / Orb

- **Web:** [`feral-client-v2/src/ui/Orb.jsx`](../feral-client-v2/src/ui/Orb.jsx)
  +  [`feral-client-v2/src/shell/Ambient.jsx`](../feral-client-v2/src/shell/Ambient.jsx).
- **iOS port target:** new `Sources/FeralBridge/Views/OrbView.swift`
  (SwiftUI `Canvas` + `TimelineView` for the animation). Must read
  colors from `FeralV2Tokens.swift`.
- **Android port target:** new `ui/OrbComposable.kt` using
  `androidx.compose.foundation.Canvas` + `animateFloatAsState`.
  Tokens: `FeralV2Tokens.kt`.

### 2.2 Chat (bubble-less, Orb role indicator)

- **Web:** [`feral-client-v2/src/pages/Chat.jsx`](../feral-client-v2/src/pages/Chat.jsx).
- **iOS port target:** replace `App/ChatView.swift` so messages render
  with a small `OrbView` (size=22) as role indicator and no bubbles.
  Composer pill matches the web `.v2-chat-composer`.
- **Android port target:** replace `src/main/java/ai/feral/node/ChatScreen.kt`
  using the same bubble-less pattern + Compose `Surface` with
  `FeralV2Tokens.surface1` + `hairline`.

### 2.3 Voice mode (visual takeover)

- **Web:** [`feral-client-v2/src/shell/VoiceOverlay.jsx`](../feral-client-v2/src/shell/VoiceOverlay.jsx)
  + [`feral-client-v2/src/hooks/useVoiceMode.js`](../feral-client-v2/src/hooks/useVoiceMode.js).
- **iOS port target:** `App/VoiceManager.swift` already exists; wrap its
  active state in a `.fullScreenCover` that shows the Orb + transcript +
  provider pill using tokens. Dim the underlying TabView to 0.4.
- **Android port target:** wrap the existing voice state in a full-screen
  `Dialog` / `ModalBottomSheet` with Orb takeover. Honest
  provider label: OpenAI Realtime / Gemini Live / Local Whisper+Piper —
  never hide which provider is driving.

## 3. Verification bar (before merging screen rewrites)

- **iOS:** `xcodebuild -scheme Feral -destination 'platform=iOS Simulator,name=iPhone 16' test` passes.
- **Android:** `./gradlew :androidTest` passes.
- Every new screen ships at least one snapshot or instrumentation test.
- Apple Human Interface Guidelines — native haptics, safe areas, no
  custom fonts beyond SF / Roboto.
- No hardcoded colors / sizes; every literal reads from
  `FeralV2Tokens.{swift,kt}`.

## 4. Why we shipped tokens-only first

See the `AGENT_PROMPT.md` "never fake / never workaround" rule. The
repo's current CI does not run Xcode or Android builds on every push
(mobile builds are dispatch-only). Shipping screen rewrites that haven't
been compiled end-to-end would be "claim something works when you
haven't verified." Tokens are pure declarations — they compile or they
don't — so they are safe to ship ahead of the screen-rewrite PRs.

The next contributor with an Xcode + Android SDK working locally
should pick up from this file, port the three persona-critical screens,
and run the verification bar above before merging.
