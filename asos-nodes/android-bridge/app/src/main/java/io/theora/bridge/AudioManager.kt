package io.theora.bridge

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import kotlinx.coroutines.*

/**
 * THEORA Audio Manager for Android.
 * Captures PCM16 24kHz mic audio and plays received audio responses.
 */
class AudioManager(
    private val brainClient: TheoraBrainClient,
    private val wakeWordDetector: WakeWordDetector? = null,
) {
    companion object {
        const val SAMPLE_RATE = 24000
        const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
        const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
        const val CHUNK_DURATION_MS = 100
    }

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var captureJob: Job? = null
    private var audioRecord: AudioRecord? = null
    private var audioTrack: AudioTrack? = null
    private var chunkIndex = 0

    var isCapturing: Boolean = false
        private set

    fun startCapture() {
        if (isCapturing) return

        val bufferSize = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT)
        audioRecord = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            SAMPLE_RATE,
            CHANNEL_CONFIG,
            AUDIO_FORMAT,
            bufferSize.coerceAtLeast(SAMPLE_RATE * 2),
        )

        isCapturing = true
        chunkIndex = 0

        captureJob = scope.launch {
            audioRecord?.startRecording()
            val chunkSamples = SAMPLE_RATE * CHUNK_DURATION_MS / 1000
            val buffer = ByteArray(chunkSamples * 2) // 16-bit = 2 bytes per sample

            while (isActive && isCapturing) {
                val bytesRead = audioRecord?.read(buffer, 0, buffer.size) ?: -1
                if (bytesRead > 0) {
                    val chunk = buffer.copyOf(bytesRead)

                    val shouldSend = if (wakeWordDetector != null && wakeWordDetector.isEnabled) {
                        wakeWordDetector.processFrame(chunk)
                    } else {
                        true
                    }

                    if (shouldSend) {
                        brainClient.sendAudioChunk(chunk, chunkIndex++, false)
                    }
                }
            }
        }
    }

    fun stopCapture() {
        isCapturing = false
        captureJob?.cancel()
        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null

        // Send final chunk marker
        brainClient.sendAudioChunk(ByteArray(0), chunkIndex, true)
    }

    fun playAudio(data: ByteArray, encoding: String = "pcm16", sampleRate: Int = SAMPLE_RATE) {
        scope.launch {
            try {
                if (encoding == "pcm16") {
                    playPCM(data, sampleRate)
                }
                // For mp3/opus, use MediaPlayer or decoder — simplified to PCM here
            } catch (_: Exception) {}
        }
    }

    private fun playPCM(data: ByteArray, sampleRate: Int) {
        val track = AudioTrack.Builder()
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(sampleRate)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build()
            )
            .setBufferSizeInBytes(data.size)
            .setTransferMode(AudioTrack.MODE_STATIC)
            .build()

        track.write(data, 0, data.size)
        track.play()
        audioTrack = track
    }

    fun stopPlayback() {
        audioTrack?.stop()
        audioTrack?.release()
        audioTrack = null
    }

    fun destroy() {
        stopCapture()
        stopPlayback()
        scope.cancel()
    }
}
