import SwiftUI

struct ChatView: View {
    @EnvironmentObject var connection: ConnectionManager
    @State private var inputText = ""
    @State private var messages: [(role: String, text: String, timestamp: Date)] = []
    
    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        ForEach(Array(messages.enumerated()), id: \.offset) { index, msg in
                            HStack(alignment: .top) {
                                if msg.role == "user" {
                                    Spacer()
                                    Text(msg.text)
                                        .padding(12)
                                        .background(Color.cyan.opacity(0.2))
                                        .cornerRadius(16)
                                        .foregroundColor(.white)
                                } else {
                                    Text(msg.text)
                                        .padding(12)
                                        .background(Color(.systemGray6).opacity(0.3))
                                        .cornerRadius(16)
                                        .foregroundColor(.white)
                                    Spacer()
                                }
                            }
                            .id(index)
                        }
                    }
                    .padding()
                }
                .onChange(of: messages.count) { _ in
                    withAnimation { proxy.scrollTo(messages.count - 1, anchor: .bottom) }
                }
            }
            
            Divider()
            
            HStack(spacing: 8) {
                TextField("Message FERAL...", text: $inputText)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { sendMessage() }
                
                Button(action: sendMessage) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.title2)
                        .foregroundColor(.cyan)
                }
                .disabled(inputText.isEmpty)
            }
            .padding()
        }
        .background(Color.black)
    }
    
    private func sendMessage() {
        guard !inputText.isEmpty else { return }
        messages.append((role: "user", text: inputText, timestamp: Date()))
        connection.sendText(inputText)
        inputText = ""
    }
}
