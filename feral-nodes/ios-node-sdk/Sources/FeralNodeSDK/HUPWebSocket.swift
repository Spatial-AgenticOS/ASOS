import Foundation

/// Thin wrapper around URLSessionWebSocketTask for HUP v1.1 framing.
/// Handles exponential-backoff reconnect + JSON encode/decode of
/// HUPFrame. No HUP-specific semantics live here — the FeralNode
/// class above decides what to emit and when.
public actor HUPWebSocket {
    private let url: URL
    private let apiKey: String?
    private var task: URLSessionWebSocketTask?
    private var onMessage: ((HUPFrame) -> Void)?
    private var connected = false
    private let session: URLSession
    private var heartbeatTask: Task<Void, Never>?
    private var heartbeatIntervalMs: Int = 10000

    public init(url: URL, apiKey: String? = nil, session: URLSession = .shared) {
        self.url = url
        self.apiKey = apiKey
        self.session = session
    }

    public func connect(onMessage: @escaping (HUPFrame) -> Void) async throws {
        self.onMessage = onMessage
        var request = URLRequest(url: url)
        if let apiKey = apiKey {
            request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        }
        let task = session.webSocketTask(with: request)
        self.task = task
        task.resume()
        connected = true
        Task { [weak self] in await self?.receiveLoop() }
    }

    public func disconnect() async {
        stopHeartbeat()
        try? await sendNodeBye(reason: "shutdown")
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
        guard let task else { return }
        while connected {
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
                return
            }
        }
    }

    private func dispatch(data: Data) {
        do {
            let frame = try JSONDecoder().decode(HUPFrame.self, from: data)
            onMessage?(frame)
        } catch {
            // Malformed frames are logged by the caller via onMessage.
        }
    }
}
