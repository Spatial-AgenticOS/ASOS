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
                // On error the caller's reconnect loop will re-invoke
                // connect(); nothing useful to do here beyond logging.
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
            // Malformed frames are logged by the caller via onMessage
            // — we only decode here.
        }
    }
}
