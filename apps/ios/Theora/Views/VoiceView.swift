import SwiftUI
import AVFoundation

struct VoiceView: View {

    @ObservedObject var brainClient: BrainClient
    @State private var isRecording = false
    @State private var transcript = ""
    @State private var responseText = ""
    @State private var audioEngine = AVAudioEngine()
    @State private var chunkIndex = 0
    @State private var pulseAmount: CGFloat = 1.0

    var body: some View {
        NavigationView {
            VStack(spacing: 32) {
                Spacer()

                statusIndicator

                if !transcript.isEmpty {
                    Text(transcript)
                        .font(.body)
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 32)
                        .transition(.opacity)
                }

                if !responseText.isEmpty {
                    ScrollView {
                        Text(responseText)
                            .font(.body)
                            .padding()
                    }
                    .frame(maxHeight: 200)
                    .background(Color(.systemGray6))
                    .cornerRadius(16)
                    .padding(.horizontal)
                }

                Spacer()

                recordButton

                Text(isRecording ? "Tap to stop" : "Tap to speak")
                    .font(.caption)
                    .foregroundColor(.secondary)

                Spacer()
            }
            .navigationTitle("Voice")
            .navigationBarTitleDisplayMode(.inline)
            .onAppear(perform: setupCallbacks)
        }
    }

    // MARK: - Subviews

    private var statusIndicator: some View {
        ZStack {
            Circle()
                .fill(Color.accentColor.opacity(0.15))
                .frame(width: 160, height: 160)
                .scaleEffect(pulseAmount)

            Circle()
                .fill(Color.accentColor.opacity(0.3))
                .frame(width: 120, height: 120)
                .scaleEffect(pulseAmount * 0.9)

            Image(systemName: isRecording ? "waveform" : "mic.fill")
                .font(.system(size: 40))
                .foregroundColor(.accentColor)
        }
        .animation(.easeInOut(duration: 1.0).repeatForever(autoreverses: true), value: isRecording)
        .onChange(of: isRecording) { recording in
            pulseAmount = recording ? 1.2 : 1.0
        }
    }

    private var recordButton: some View {
        Button(action: toggleRecording) {
            ZStack {
                Circle()
                    .fill(isRecording ? Color.red : Color.accentColor)
                    .frame(width: 72, height: 72)

                Image(systemName: isRecording ? "stop.fill" : "mic.fill")
                    .font(.system(size: 28))
                    .foregroundColor(.white)
            }
        }
        .disabled(!brainClient.isConnected)
    }

    // MARK: - Audio Capture

    private func toggleRecording() {
        if isRecording {
            stopRecording()
        } else {
            startRecording()
        }
    }

    private func startRecording() {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
            try session.setActive(true)
        } catch {
            return
        }

        transcript = ""
        responseText = ""
        chunkIndex = 0

        let inputNode = audioEngine.inputNode
        let recordingFormat = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: 24000,
            channels: 1,
            interleaved: true
        )!

        inputNode.installTap(onBus: 0, bufferSize: 2400, format: recordingFormat) { buffer, _ in
            guard let channelData = buffer.int16ChannelData else { return }
            let frameLength = Int(buffer.frameLength)
            let data = Data(bytes: channelData[0], count: frameLength * 2)
            let b64 = data.base64EncodedString()
            brainClient.sendAudioChunk(base64: b64, chunkIndex: chunkIndex)
            chunkIndex += 1
        }

        do {
            try audioEngine.start()
            isRecording = true
        } catch {
            isRecording = false
        }
    }

    private func stopRecording() {
        audioEngine.inputNode.removeTap(onBus: 0)
        audioEngine.stop()
        isRecording = false

        brainClient.sendAudioChunk(base64: "", chunkIndex: chunkIndex, isFinal: true)
    }

    // MARK: - Callbacks

    private func setupCallbacks() {
        brainClient.onTextResponse = { response in
            responseText = response.text
        }

        brainClient.onStreamDelta = { delta in
            responseText += delta
        }
    }
}
