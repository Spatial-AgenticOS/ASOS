# FERAL Android Bridge

Android SDK and sample app for connecting to the FERAL Brain.

## Requirements

- Android Studio Hedgehog (2023.1.1) or later
- JDK 17
- Android SDK 34

## Build

```bash
# Library AAR
./gradlew :bridge:assembleRelease

# Sample APK (debug)
./gradlew :sample:assembleDebug
```

The AAR is output to `bridge/build/outputs/aar/`.
The APK is output to `sample/build/outputs/apk/debug/`.

## Usage

```kotlin
val client = FeralBrainClient(
    host = "192.168.1.100",
    port = 9090,
    apiKey = "your-api-key",
    delegate = this,
)
client.connect()

// Send text
client.sendTextCommand("What's the weather?")

// Send audio
client.sendAudioChunk(pcmBytes, chunkIndex = 0, isFinal = false)

// Send sensor data
client.sendSensorTelemetry(heartRate = 72, spo2 = 98)
```

## Architecture

- `bridge/` — Library module (AAR) with `FeralBrainClient` WebSocket client
- `sample/` — Demo app implementing `FeralBrainDelegate`

As of 2026.5.8 the bridge authenticates via the `Authorization: Bearer
<token>` header (matching `TheoraBrainClient.kt`). The legacy
`?api_key=` query auth is accepted by brains during the deprecation
window (sunset `2026.7.0`). The bridge connects to
`wss://host[:port]/v1/node` (or `ws://` for Mode A LAN with explicit
opt-in) and handles:
- Voice (PCM16 audio chunks)
- Text commands
- SDUI rendering
- Sensor telemetry
- Glasses status forwarding
