import Foundation

/// Thin wrapper around URLSessionWebSocketTask for HUP v1.x framing.
/// Handles JSON encode/decode of HUPFrame plus jittered exponential
/// backoff reconnect (HUP_SPEC §2: initial 100 ms, factor 2, cap 30 s,
/// full jitter). No HUP-specific semantics live here — the FeralNode
/// class above decides what to emit and when.
public actor HUPWebSocket {
    private let url: URL
    private let apiKey: String?
    private var task: URLSessionWebSocketTask?
    private var onMessage: ((HUPFrame) -> Void)?
    /// Optional hook invoked when the socket has fully reconnected
    /// after a drop. The host (FeralNode) re-issues `node_register`
    /// in response so the brain rebinds the session.
    private var onReconnect: (() async -> Void)?
    private var connected = false
    /// Set once `disconnect()` is called — disables reconnect so a
    /// graceful shutdown stays shut down.
    private var stopped = false
    private let session: URLSession
    private var heartbeatTask: Task<Void, Never>?
    private var heartbeatIntervalMs: Int = 10000
    private var reconnectTask: Task<Void, Never>?

    /// Backoff parameters (per HUP_SPEC §2). Exposed `internal` for
    /// the unit-test target so deterministic-time tests can shrink
    /// the upper bound; default values match the spec exactly.
    public struct BackoffPolicy: Sendable {
        public var initialMs: Int
        public var capMs: Int
        public var factor: Double

        public static let spec = BackoffPolicy(initialMs: 100, capMs: 30_000, factor: 2.0)

        public init(initialMs: Int, capMs: Int, factor: Double) {
            self.initialMs = initialMs
            self.capMs = capMs
            self.factor = factor
        }
    }
    private let backoff: BackoffPolicy

    public init(
        url: URL,
        apiKey: String? = nil,
        session: URLSession = .shared,
        backoff: BackoffPolicy = .spec
    ) {
        self.url = url
        self.apiKey = apiKey
        self.session = session
        self.backoff = backoff
    }

    public func connect(
        onMessage: @escaping (HUPFrame) -> Void,
        onReconnect: (() async -> Void)? = nil
    ) async throws {
        self.onMessage = onMessage
        self.onReconnect = onReconnect
        self.stopped = false
        try await openSocket()
        Task { [weak self] in await self?.receiveLoop() }
    }

    private func openSocket() async throws {
        var request = URLRequest(url: url)
        if let apiKey = apiKey {
            request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        }
        let task = session.webSocketTask(with: request)
        self.task = task
        task.resume()
        connected = true
    }

    /// Tear down the socket and emit a single ``node_bye`` frame with
    /// the supplied reason. Defaults to ``"shutdown"`` for the
    /// generic SDK consumer; callers that know the disconnect was
    /// user-initiated (e.g. companion ``BrainClient.disconnect``)
    /// should pass ``"user_disconnect"`` so the brain log reflects
    /// intent instead of forcing every disconnect to read as a
    /// crash-style shutdown. Pinned by HeartbeatTests +
    /// ConnectionStore-level integration in the companion app.
    public func disconnect(reason: String = "shutdown") async {
        stopped = true
        stopHeartbeat()
        reconnectTask?.cancel()
        reconnectTask = nil
        try? await sendNodeBye(reason: reason)
        task?.cancel(with: .goingAway, reason: nil)
        connected = false
    }

    public func send(_ frame: HUPFrame) async throws {
        guard let task else { throw FeralNodeError.notConnected }
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .useDefaultKeys
        let data = try encoder.encode(frame)
        try await task.send(.data(data))
    }

    /// Start the heartbeat loop with the interval from node_ack.
    public func startHeartbeat(intervalMs: Int) {
        stopHeartbeat()
        heartbeatIntervalMs = max(1000, intervalMs)
        heartbeatTask = Task { [weak self] in
            while !Task.isCancelled {
                let ms = await self?.heartbeatIntervalMs ?? 10000
                try? await Task.sleep(nanoseconds: UInt64(ms) * 1_000_000)
                guard !Task.isCancelled else { return }
                let frame = HUPFrame(
                    type: "node_heartbeat",
                    payload: ["ts": .double(Date().timeIntervalSince1970)]
                )
                try? await self?.send(frame)
            }
        }
    }

    /// Stop the heartbeat timer.
    public func stopHeartbeat() {
        heartbeatTask?.cancel()
        heartbeatTask = nil
    }

    /// Public for tests; production code triggers reconnect via the
    /// receive loop on socket failure.
    public func isConnected() -> Bool { connected && !stopped }

    private func sendNodeBye(reason: String) async throws {
        let frame = HUPFrame(
            type: "node_bye",
            payload: [
                "reason": .string(reason),
                "restart_in_s": .int(0),
            ]
        )
        try await send(frame)
    }

    private func receiveLoop() async {
        while !stopped {
            guard let task else { return }
            do {
                let msg = try await task.receive()
                switch msg {
                case .data(let data):
                    dispatch(data: data)
                case .string(let s):
                    dispatch(data: Data(s.utf8))
                @unknown default:
                    continue
                }
            } catch {
                connected = false
                if stopped { return }
                // Per HUP_SPEC §2 — jittered exponential backoff.
                await reconnectWithBackoff()
                if stopped { return }
                // Continue the receive loop on the new socket.
            }
        }
    }

    /// Reconnect with full-jitter exponential backoff. Returns once
    /// either (a) the socket is open again, or (b) `disconnect()` was
    /// called and we should give up.
    private func reconnectWithBackoff() async {
        stopHeartbeat()
        var delayMs = backoff.initialMs
        while !stopped {
            // Full jitter: random in [0, delayMs].
            let jitterMs = Int.random(in: 0...delayMs)
            try? await Task.sleep(nanoseconds: UInt64(jitterMs) * 1_000_000)
            if stopped { return }
            do {
                try await openSocket()
                // Notify host so it can re-send `node_register`.
                if let cb = onReconnect {
                    await cb()
                }
                return
            } catch {
                delayMs = min(Int(Double(delayMs) * backoff.factor), backoff.capMs)
            }
        }
    }

    private func dispatch(data: Data) {
        do {
            let frame = try JSONDecoder().decode(HUPFrame.self, from: data)
            onMessage?(frame)
        } catch {
            // Malformed frames are dropped silently. Hosts that need
            // visibility into protocol errors can subscribe to the
            // brain's `error` frames via FeralNode.inboundFrames.
        }
    }
}
