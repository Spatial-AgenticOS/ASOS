# FeralNodeSDK — iOS phone-as-HUP-daemon bridge

> **Status:** scaffold (2026.4.22). Structure + public API defined; the
> three vendor-SDK adapters (Veepoo wristband, JW Ble glasses, QCSDK
> W610) have placeholders that intentionally refuse to return fake
> data. When the hardware is in reach and you hand the SDKs to the
> iOS project the adapters get wired in one focused session.

## Why this exists

All three first-party Theora devices (wristband, health glasses, W610
open-source Meta-Ray-Ban-style glasses) only pair through an iPhone.
The phone is the HUP daemon in this topology — not a desktop bleak
process. Attempting to talk to them from `feral-nodes/wristband_daemon`
or `feral-nodes/theora_glasses_daemon` would fail because the vendor
BLE stacks hide behind iOS frameworks we can't run on the desktop.

The right architecture:

```
[ Theora wristband ] --BLE--> [ iPhone: FeralNodeSDK + VeepooSDK ] --HUP WebSocket--> [ FERAL Brain ]
[ Health glasses  ] --BLE--> [ iPhone: FeralNodeSDK + JWBleSDK   ] --HUP WebSocket--> [ FERAL Brain ]
[ W610 glasses    ] --BLE--> [ iPhone: FeralNodeSDK + QCSDK      ] --HUP WebSocket--> [ FERAL Brain ]
```

The iPhone opens ONE WebSocket to the brain (`/v1/node`) and registers
itself as a `node_type="phone"` HUP daemon whose capabilities include
whichever vendor SDKs are linked into the app build. The three
vendor adapters run **concurrently** inside the same phone process —
the phone is a multi-sensor gateway, not a single-device bridge.

## Package layout

```
ios-node-sdk/
├── README.md                          <- this file
├── Package.swift                      <- Swift Package Manager manifest
├── Sources/
│   └── FeralNodeSDK/
│       ├── FeralNode.swift            <- public class: connect/disconnect/emit
│       ├── HUPFrame.swift             <- Codable wire-frame mirrors
│       ├── HUPWebSocket.swift         <- URLSessionWebSocketTask wrapper
│       ├── Adapters/
│       │   ├── VendorAdapter.swift    <- protocol every adapter implements
│       │   ├── VeepooAdapter.swift    <- wristband (status: awaiting SDK wire-up)
│       │   ├── JWBleAdapter.swift     <- health glasses (status: awaiting SDK wire-up)
│       │   └── QCSDKAdapter.swift     <- W610 glasses (status: awaiting SDK wire-up)
│       └── Info.swift                 <- version + build metadata
└── Tests/
    └── FeralNodeSDKTests/
        └── HUPFrameTests.swift        <- codable round-trip tests
```

## Public API

```swift
import FeralNodeSDK

let node = FeralNode(
    brainURL: URL(string: "wss://brain.local:9090/v1/node")!,
    apiKey: "<feral pairing token>",
    nodeID: "feral-phone-\(UIDevice.current.identifierForVendor!.uuidString.prefix(8))"
)

// Register the vendor adapters you want the phone to expose.
// Each adapter can be compiled out by omitting its framework from
// the target, so a build that only has VeepooSDK will register
// only the wristband.
node.register(adapter: VeepooAdapter())
node.register(adapter: JWBleAdapter())
node.register(adapter: QCSDKAdapter())

try await node.connect()
// Blocks the run loop. Adapters emit device_event frames directly;
// FeralNode handles reconnection + heartbeat + HUP ack/nak.
```

## Adapter contract

Every vendor adapter conforms to:

```swift
public protocol VendorAdapter {
    /// Short identifier surfaced in node_register.capabilities.
    /// Examples: "veepoo_wristband", "jw_health_glasses", "w610_glasses".
    var capability: String { get }

    /// Wire the vendor SDK callbacks onto the node's emit path.
    /// Called once after FeralNode has completed its node_register
    /// handshake with the brain. The node handle lets the adapter
    /// emit device_event frames (heart rate, audio_frame, video_frame)
    /// whenever the vendor SDK hands it data.
    func attach(to node: FeralNode) async throws

    /// Clean shutdown when the node disconnects or the app moves to
    /// background. Must release every BLE subscription the SDK owns.
    func detach() async
}
```

## Vendor adapter status

### VeepooAdapter (wristband)

**SDK:** `VeepooBleSDK.framework` — iOS Objective-C framework at
`~/Desktop/Theora-backend-ML/wristband/iOS_sdk_source/Framework/`.
Docs at `iOS_sdk_source/doc/VeepooSDK iOS Api_en.md`.

Public entry: `VPBleCentralManager.sharedBleManager` (singleton).
Peripheral management:
`VPBleCentralManager.peripheralManage = VPPeripheralManage.shareVPPeripheralManager()`.
Scan: `veepooSDKStartScanDeviceAndReceiveScanningDevice:`.
Data callbacks: heart-rate, SpO2, body-temp, ECG, steps all come
through the `VPPeripheralManage` delegate methods.

**Wire-up action items** (deferred — awaiting live hardware pairing):

- Bridge Obj-C SDK into the Swift package via an `@import` umbrella
  header or an ObjC-bridging-header in the Tests target.
- Translate Veepoo's per-metric delegate callbacks into HUP v1.1
  `device_event` frames with `event_type = "heart_rate"` /
  `"spo2"` / `"skin_temperature"` / `"steps"`.
- Haptic: Veepoo exposes vibration via its SDK — map an inbound
  `hup_action_request` with `name: "buzz"` to the SDK's vibration
  method (consult `doc/VeepooSDK iOS Api_en.md` §"Haptic feedback"
  when pairing).

### JWBleAdapter (health glasses — Ble-Demo-iOS)

**SDK:** `JWBle.framework` — iOS Objective-C framework at
`~/Desktop/Theora-backend-ML/Ble-Demo-iOS/iOS/SDK/JWBle.framework`.
Public entry: `JWBleManager.shareInstance`. Set-up:
`[JWBleManager.shareInstance setUpWithUid:@"programmer"];`.
FMDB + CocoaLumberjack + Realtek bluetooth audio frameworks ship
alongside.

**Wire-up action items:**

- Link JWBle + its dependencies (`CocoaLumberjack`, `FMDB`,
  `RTKAudioConnectSDK`, `RTKLEFoundation`, `RTKOTASDK`) into the
  app target.
- Call `setUpWithUid:` during adapter `attach(to:)`.
- Route device events (which JW's delegate surfaces) to
  `node.emit(eventType:data:)`.
- OTA updates are opt-in and gated behind a separate capability
  `glasses_ota` so the brain can refuse them by default.

### QCSDKAdapter (W610 — open-source glasses)

**SDK:** `QCSDK.framework` at `~/Desktop/Theora-backend-ML/W610/QCSDKDemo/
QCSDK.framework`. Doc: `W610/QCSDKDemo/iOS_SDK_Development_Guide.pdf`.
Also includes `moshi-swift` — likely the Moshi streaming-audio LLM
scaffolding for the W610's voice-first UX.

**Wire-up action items:**

- Link `QCSDK.framework` and (if the Moshi audio path is wanted)
  `moshi-swift`.
- Follow `iOS_SDK_Development_Guide.pdf` for the scan +
  connect sequence.
- Emit video frames as HUP v1.1 `video_frame` (§5.4.2) and audio
  frames as HUP v1.1 `audio_frame` (§5.4.1). Size caps: 512 KiB
  per JPEG, 64 KiB per Opus frame (both enforced by the brain's
  `_handle_video_frame` + `_handle_audio_frame`).

## Deferred-but-scaffolded

Each adapter's .swift file is in the package but its `attach(to:)`
implementation intentionally throws `FeralNodeError.adapterNotWired`
so the build fails loudly when someone tries to ship without
completing the integration. No fake heart-rate, no synthetic frames,
no pretend BLE writes. When the SDKs are linked and the hardware is
in reach, each adapter is ≤ 1 day of real work.

## Testing

Unit tests in `Tests/FeralNodeSDKTests/` exercise:

- HUP frame codable round-trip (node_register, device_event,
  heartbeat, node_bye).
- HUPWebSocket reconnect backoff against a `URLProtocol` fake.
- VendorAdapter protocol conformance of each adapter.
- `adapterNotWired` error is raised when `attach()` is called on a
  pre-wire-up adapter.

No live-hardware tests in the package itself — those live in the
host app's UI tests and are gated behind an environment flag the
same way the Python daemons use `FERAL_LIVE_WRISTBAND_TEST`.
