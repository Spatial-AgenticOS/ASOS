import SwiftUI

struct ChatMessage: Identifiable {
    let id = UUID()
    let text: String
    let isUser: Bool
    let timestamp: Date
}

struct ChatView: View {

    @ObservedObject var brainClient: BrainClient
    @State private var inputText = ""
    @State private var messages: [ChatMessage] = []
    @State private var streamingText = ""
    @FocusState private var inputFocused: Bool

    var body: some View {
        NavigationView {
            VStack(spacing: 0) {
                connectionBanner

                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 12) {
                            ForEach(messages) { msg in
                                MessageBubble(message: msg)
                                    .id(msg.id)
                            }

                            if !streamingText.isEmpty {
                                streamingBubble
                            }
                        }
                        .padding()
                    }
                    .onChange(of: messages.count) { _ in
                        if let last = messages.last {
                            withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                        }
                    }
                }

                inputBar
            }
            .navigationTitle("FERAL")
            .navigationBarTitleDisplayMode(.inline)
            .onAppear(perform: setupCallbacks)
        }
    }

    // MARK: - Subviews

    @ViewBuilder
    private var connectionBanner: some View {
        if brainClient.connectionState != .connected {
            HStack(spacing: 8) {
                ProgressView()
                    .tint(.white)
                Text(brainClient.connectionState == .disconnected
                     ? "Disconnected from Brain"
                     : "Connecting...")
                    .font(.caption)
                    .foregroundColor(.white)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 6)
            .background(brainClient.connectionState == .disconnected ? Color.red.opacity(0.85) : Color.orange.opacity(0.85))
        }
    }

    private var streamingBubble: some View {
        HStack {
            Text(streamingText)
                .padding(12)
                .background(Color(.systemGray5))
                .cornerRadius(16)
            Spacer()
        }
    }

    private var inputBar: some View {
        HStack(spacing: 12) {
            TextField("Message FERAL...", text: $inputText)
                .textFieldStyle(.plain)
                .padding(10)
                .background(Color(.systemGray6))
                .cornerRadius(20)
                .focused($inputFocused)
                .onSubmit(sendMessage)

            Button(action: sendMessage) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 32))
                    .foregroundColor(inputText.isEmpty ? .gray : .accentColor)
            }
            .disabled(inputText.isEmpty || !brainClient.isConnected)
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(Color(.systemBackground))
    }

    // MARK: - Actions

    private func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }

        messages.append(ChatMessage(text: text, isUser: true, timestamp: Date()))
        brainClient.sendTextCommand(text)
        inputText = ""
        streamingText = ""
    }

    private func setupCallbacks() {
        brainClient.onTextResponse = { response in
            messages.append(ChatMessage(text: response.text, isUser: false, timestamp: Date()))
            streamingText = ""
        }
        brainClient.onStreamDelta = { delta in
            streamingText += delta
        }
    }
}

// MARK: - Message Bubble

struct MessageBubble: View {
    let message: ChatMessage

    var body: some View {
        HStack {
            if message.isUser { Spacer(minLength: 48) }

            VStack(alignment: message.isUser ? .trailing : .leading, spacing: 4) {
                Text(message.text)
                    .padding(12)
                    .background(message.isUser ? Color.accentColor : Color(.systemGray5))
                    .foregroundColor(message.isUser ? .white : .primary)
                    .cornerRadius(16)

                Text(message.timestamp, style: .time)
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }

            if !message.isUser { Spacer(minLength: 48) }
        }
    }
}
