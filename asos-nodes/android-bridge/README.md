# THEORA Android Bridge

Android SDK and sample app for connecting to the THEORA Brain.

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
val client = TheoraBrainClient(
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

- `bridge/` — Library module (AAR) with `TheoraBrainClient` WebSocket client
- `sample/` — Demo app implementing `TheoraBrainDelegate`

The bridge connects to `ws://host:port/v1/node?api_key=...` and handles:
- Voice (PCM16 audio chunks)
- Text commands
- SDUI rendering
- Sensor telemetry
- Glasses status forwarding
