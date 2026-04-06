package io.theora.bridge

/**
 * THEORA Voice Configuration for Android bridge.
 * Declares the node's voice capabilities to the Brain.
 */
data class VoiceConfig(
    val supportsRealtime: Boolean = true,
    val mode: String = "auto",         // "realtime", "whisper", "auto"
    val preferredModel: String = "",
    val sampleRate: Int = 24000,
    val encoding: String = "pcm16",
)
