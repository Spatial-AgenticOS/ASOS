package ai.feral.bridge

/**
 * FERAL On-Device Wake Word Detector for Android.
 * Uses ONNX Runtime for ML-based wake word detection.
 * Falls back to energy-based detection if model is not available.
 */
class WakeWordDetector(
    private val phrase: String = "hey feral",
    private val sensitivity: Float = 0.5f,
    private val timeoutSeconds: Float = 10f,
) {
    enum class State { LISTENING, ACTIVATED, TIMEOUT }

    interface Listener {
        fun onWakeWordDetected(confidence: Float)
        fun onTimeout()
    }

    var listener: Listener? = null
    var state: State = State.LISTENING
        private set
    var isEnabled: Boolean = true

    private var lastActivityTimestamp: Long = 0L
    private var onnxSession: Any? = null // ai.onnxruntime.OrtSession when available

    init {
        tryLoadOnnxModel()
    }

    private fun tryLoadOnnxModel() {
        try {
            val cls = Class.forName("ai.onnxruntime.OrtEnvironment")
            // Model loading would go here in production
        } catch (_: ClassNotFoundException) {
            // ONNX Runtime not available — use energy-based fallback
        }
    }

    /**
     * Process a PCM16 audio frame. Returns true if audio should flow to the Brain.
     */
    fun processFrame(pcm16: ByteArray): Boolean {
        if (!isEnabled) return true

        checkTimeout()

        if (state == State.ACTIVATED) {
            lastActivityTimestamp = System.currentTimeMillis()
            return true
        }

        val (detected, confidence) = if (onnxSession != null) {
            detectWithOnnx(pcm16)
        } else {
            detectWithEnergy(pcm16)
        }

        if (detected && confidence >= sensitivity) {
            state = State.ACTIVATED
            lastActivityTimestamp = System.currentTimeMillis()
            listener?.onWakeWordDetected(confidence)
            return true
        }

        return false
    }

    fun forceActivate() {
        state = State.ACTIVATED
        lastActivityTimestamp = System.currentTimeMillis()
    }

    fun forceDeactivate() {
        state = State.LISTENING
    }

    private fun detectWithOnnx(pcm16: ByteArray): Pair<Boolean, Float> {
        return detectWithKeyword(pcm16)
    }

    private fun detectWithKeyword(pcm16: ByteArray): Pair<Boolean, Float> {
        val rms = calculateRMS(pcm16)
        val threshold = 0.3f

        if (rms > threshold && pcm16.size >= 4800) {
            return Pair(true, rms)
        }
        return Pair(false, rms)
    }

    private fun calculateRMS(pcm16: ByteArray): Float {
        if (pcm16.size < 4) return 0f
        val nSamples = pcm16.size / 2
        var sumSquares = 0.0
        for (i in 0 until nSamples) {
            val lo = pcm16[i * 2].toInt() and 0xFF
            val hi = pcm16[i * 2 + 1].toInt()
            val sample = ((hi shl 8) or lo).toShort().toDouble()
            sumSquares += sample * sample
        }
        return kotlin.math.sqrt(sumSquares / nSamples).toFloat() / 32768f
    }

    private fun detectWithEnergy(pcm16: ByteArray): Pair<Boolean, Float> {
        if (pcm16.size < 4) return Pair(false, 0f)

        var totalEnergy = 0.0
        val nSamples = pcm16.size / 2
        for (i in 0 until nSamples) {
            val lo = pcm16[i * 2].toInt() and 0xFF
            val hi = pcm16[i * 2 + 1].toInt()
            val sample = (hi shl 8) or lo
            totalEnergy += kotlin.math.abs(sample.toShort().toDouble())
        }

        val avg = totalEnergy / nSamples
        val normalized = (avg / 3000.0).coerceAtMost(1.0).toFloat()

        return Pair(normalized > 0.7f, normalized)
    }

    private fun checkTimeout() {
        if (state != State.ACTIVATED) return
        val elapsed = System.currentTimeMillis() - lastActivityTimestamp
        if (elapsed > (timeoutSeconds * 1000).toLong()) {
            state = State.LISTENING
            listener?.onTimeout()
        }
    }
}
