import AVFoundation
import Foundation

class VoiceManager: ObservableObject {
    @Published var isRecording = false
    @Published var isPlaying = false
    
    private var audioEngine: AVAudioEngine?
    private var inputNode: AVAudioInputNode?
    private var brainClient: FeralBrainClient?
    private var audioPlayer: AVAudioPlayer?
    
    func setBrainClient(_ client: FeralBrainClient) {
        self.brainClient = client
    }
    
    func startRecording() {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetooth])
            try session.setActive(true)
        } catch { return }
        
        audioEngine = AVAudioEngine()
        inputNode = audioEngine?.inputNode
        
        guard let inputNode = inputNode else { return }
        
        let format = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 24000, channels: 1, interleaved: true)!
        let _ = format // keep reference for documentation of target format
        
        inputNode.installTap(onBus: 0, bufferSize: 2400, format: inputNode.outputFormat(forBus: 0)) { [weak self] buffer, _ in
            guard let channelData = buffer.floatChannelData?[0] else { return }
            let frameCount = Int(buffer.frameLength)
            var pcm16 = [Int16](repeating: 0, count: frameCount)
            for i in 0..<frameCount {
                pcm16[i] = Int16(max(-1, min(1, channelData[i])) * 32767)
            }
            let data = Data(bytes: pcm16, count: frameCount * 2)
            self?.brainClient?.sendAudioChunk(data)
        }
        
        do {
            try audioEngine?.start()
            isRecording = true
        } catch {}
    }
    
    func stopRecording() {
        inputNode?.removeTap(onBus: 0)
        audioEngine?.stop()
        isRecording = false
    }
    
    func playAudioData(_ data: Data) {
        do {
            audioPlayer = try AVAudioPlayer(data: data)
            audioPlayer?.play()
            isPlaying = true
        } catch {}
    }
}
