import Foundation

/// Public class vendor apps instantiate. Wraps the HUP WebSocket +
/// vendor adapter lifecycle. A single FeralNode can host multiple
/// adapters concurrently — the phone is a multi-sensor gateway.
public actor FeralNode {
    private let brainURL: URL
    private let apiKey: String
    private let nodeId: String
    private var socket: HUPWebSocket?
    private var adapters: [VendorAdapter] = []
    private var connected = false

    public init(brainURL: URL, apiKey: String, nodeID: String) {
        self.brainURL = brainURL
        self.apiKey = apiKey
        self.nodeId = nodeID
    }

    /// Register an adapter. Must be called before ``connect()``.
    public func register(adapter: VendorAdapter) {
        adapters.append(adapter)
    }

    /// Open the WebSocket, send node_register with the union of
    /// every adapter's capability strings, then call attach() on
    /// each adapter so they can wire the vendor SDK callbacks.
    public func connect() async throws {
        let ws = HUPWebSocket(url: brainURL, apiKey: apiKey)
        self.socket = ws
        try await ws.connect { [weak self] frame in
            Task { await self?.handleInbound(frame) }
        }

        let capabilities = adapters.map(\.capability)
        let registerPayload = NodeRegisterPayload(
            nodeId: nodeId,
            capabilities: capabilities
        )
        let encoder = JSONEncoder()
        let data = try encoder.encode(registerPayload)
        guard let dict = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw FeralNodeError.malformedFrame(underlying: NSError(
                domain: "FeralNode", code: -1,
                userInfo: [NSLocalizedDescriptionKey: "node_register serialisation failed"]
            ))
        }
        try await ws.send(HUPFrame(
            type: "node_register",
            payload: FeralNode.encodedPayload(dict)
        ))
        connected = true

        for adapter in adapters {
            try await adapter.attach(to: self)
        }
    }

    public func disconnect() async {
        for adapter in adapters { await adapter.detach() }
        await socket?.disconnect()
        connected = false
    }

    /// Send a node_bye frame for graceful shutdown.
    public func sendNodeBye(reason: String = "shutdown") async throws {
        guard let socket, connected else { throw FeralNodeError.notConnected }
        try await socket.send(HUPFrame(
            type: "node_bye",
            payload: [
                "reason": .string(reason),
                "restart_in_s": .int(0),
            ]
        ))
    }

    /// Used by adapters to emit a ``device_event`` frame.
    public func emit(eventType: String, data: [String: AnyCodable]) async throws {
        guard let socket, connected else { throw FeralNodeError.notConnected }
        let payload: [String: AnyCodable] = [
            "event_type": .string(eventType),
            "node_id": .string(nodeId),
            "data": .object(data),
            "ts": .double(Date().timeIntervalSince1970),
        ]
        try await socket.send(HUPFrame(type: "device_event", payload: payload))
    }

    /// Ergonomic helper for HUP v1.1 ``video_frame``. Matches
    /// the Python SDK's emit_video_frame signature.
    public func emitVideoFrame(
        jpegBase64: String,
        width: Int,
        height: Int,
        sequence: Int = 0,
        keyframe: Bool = true
    ) async throws {
        try await emit(eventType: "video_frame", data: [
            "codec": .string("jpeg"),
            "width": .int(width),
            "height": .int(height),
            "sequence": .int(sequence),
            "keyframe": .bool(keyframe),
            "data_b64": .string(jpegBase64),
        ])
    }

    /// Ergonomic helper for HUP v1.1 ``audio_frame``.
    public func emitAudioFrame(
        opusBase64: String,
        sampleRate: Int = 24000,
        channels: Int = 1,
        sequence: Int = 0,
        frameMs: Int = 20
    ) async throws {
        try await emit(eventType: "audio_frame", data: [
            "codec": .string("opus"),
            "sample_rate": .int(sampleRate),
            "channels": .int(channels),
            "sequence": .int(sequence),
            "frame_ms": .int(frameMs),
            "data_b64": .string(opusBase64),
        ])
    }

    private func handleInbound(_ frame: HUPFrame) async {
        if frame.type == "node_ack" {
            var intervalMs = 10000
            if case .int(let ms) = frame.payload["heartbeat_ms"] {
                intervalMs = ms
            }
            await socket?.startHeartbeat(intervalMs: intervalMs)
            return
        }

        if frame.type == "hup_action_request" {
            let actionName: String? = {
                if case .string(let s) = frame.payload["name"] ?? .null { return s }
                return nil
            }()
            guard let action = actionName else { return }
            for adapter in adapters {
                if await adapter.canHandleAction(named: action) {
                    await adapter.handleAction(frame: frame, node: self)
                    return
                }
            }
        }
    }

    private static func encodedPayload(_ dict: [String: Any]) -> [String: AnyCodable] {
        var out: [String: AnyCodable] = [:]
        for (k, v) in dict {
            if let s = v as? String { out[k] = .string(s); continue }
            if let b = v as? Bool { out[k] = .bool(b); continue }
            if let i = v as? Int { out[k] = .int(i); continue }
            if let d = v as? Double { out[k] = .double(d); continue }
            if let a = v as? [Any] {
                out[k] = .array(a.compactMap { AnyCodable.from($0) })
                continue
            }
            if let nested = v as? [String: Any] {
                out[k] = .object(encodedPayload(nested))
                continue
            }
            out[k] = .null
        }
        return out
    }
}

extension AnyCodable {
    static func from(_ value: Any) -> AnyCodable? {
        if let s = value as? String { return .string(s) }
        if let b = value as? Bool { return .bool(b) }
        if let i = value as? Int { return .int(i) }
        if let d = value as? Double { return .double(d) }
        return nil
    }
}
