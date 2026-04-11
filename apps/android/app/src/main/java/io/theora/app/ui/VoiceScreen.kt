package io.theora.app.ui

import android.Manifest
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import io.theora.app.services.BrainClient
import io.theora.app.services.BrainConnectionState
import kotlinx.coroutines.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VoiceScreen(brainClient: BrainClient) {
    val connectionState by brainClient.connectionState.collectAsState()
    val transcript by brainClient.transcript.collectAsState()
    val streamingText by brainClient.streamingText.collectAsState()
    var isRecording by remember { mutableStateOf(false) }
    var hasPermission by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    var recordJob by remember { mutableStateOf<Job?>(null) }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> hasPermission = granted }

    LaunchedEffect(Unit) {
        permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
    }

    val pulseAnim = rememberInfiniteTransition(label = "pulse")
    val pulseScale by pulseAnim.animateFloat(
        initialValue = 1f,
        targetValue = 1.15f,
        animationSpec = infiniteRepeatable(
            animation = tween(800, easing = EaseInOut),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulseScale",
    )

    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        TopAppBar(title = { Text("Voice") })

        Spacer(modifier = Modifier.weight(1f))

        Box(contentAlignment = Alignment.Center) {
            if (isRecording) {
                Box(
                    modifier = Modifier
                        .size(160.dp)
                        .scale(pulseScale)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.15f)),
                )
                Box(
                    modifier = Modifier
                        .size(120.dp)
                        .scale(pulseScale * 0.9f)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.3f)),
                )
            }
            Icon(
                imageVector = if (isRecording) Icons.Default.Mic else Icons.Default.Mic,
                contentDescription = null,
                modifier = Modifier.size(48.dp),
                tint = MaterialTheme.colorScheme.primary,
            )
        }

        Spacer(modifier = Modifier.height(24.dp))

        if (transcript.isNotEmpty()) {
            Text(
                text = transcript,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = 32.dp),
            )
            Spacer(modifier = Modifier.height(12.dp))
        }

        if (streamingText.isNotEmpty()) {
            Surface(
                shape = MaterialTheme.shapes.medium,
                color = MaterialTheme.colorScheme.surfaceVariant,
                modifier = Modifier
                    .padding(horizontal = 24.dp)
                    .heightIn(max = 200.dp),
            ) {
                Text(
                    text = streamingText,
                    modifier = Modifier.padding(16.dp),
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }

        Spacer(modifier = Modifier.weight(1f))

        IconButton(
            onClick = {
                if (isRecording) {
                    isRecording = false
                    recordJob?.cancel()
                } else if (hasPermission && connectionState == BrainConnectionState.CONNECTED) {
                    isRecording = true
                    recordJob = scope.launch(Dispatchers.IO) {
                        captureAudio(brainClient) { isRecording }
                    }
                }
            },
            enabled = connectionState == BrainConnectionState.CONNECTED && hasPermission,
            modifier = Modifier
                .size(72.dp)
                .clip(CircleShape)
                .background(
                    if (isRecording) MaterialTheme.colorScheme.error
                    else MaterialTheme.colorScheme.primary,
                ),
        ) {
            Icon(
                imageVector = if (isRecording) Icons.Default.Stop else Icons.Default.Mic,
                contentDescription = if (isRecording) "Stop" else "Record",
                tint = MaterialTheme.colorScheme.onPrimary,
                modifier = Modifier.size(32.dp),
            )
        }

        Spacer(modifier = Modifier.height(8.dp))

        Text(
            text = if (isRecording) "Tap to stop" else "Tap to speak",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.outline,
        )

        Spacer(modifier = Modifier.height(32.dp))
    }
}

private suspend fun captureAudio(
    brainClient: BrainClient,
    isRecording: () -> Boolean,
) {
    val sampleRate = 24000
    val bufferSize = AudioRecord.getMinBufferSize(
        sampleRate,
        AudioFormat.CHANNEL_IN_MONO,
        AudioFormat.ENCODING_PCM_16BIT,
    ).coerceAtLeast(sampleRate * 2)

    val recorder = AudioRecord(
        MediaRecorder.AudioSource.MIC,
        sampleRate,
        AudioFormat.CHANNEL_IN_MONO,
        AudioFormat.ENCODING_PCM_16BIT,
        bufferSize,
    )

    recorder.startRecording()
    val chunkSamples = sampleRate / 10
    val buffer = ByteArray(chunkSamples * 2)
    var chunkIndex = 0

    try {
        while (isRecording()) {
            val bytesRead = recorder.read(buffer, 0, buffer.size)
            if (bytesRead > 0) {
                brainClient.sendAudioChunk(buffer.copyOf(bytesRead), chunkIndex++, false)
            }
        }
        brainClient.sendAudioChunk(ByteArray(0), chunkIndex, true)
    } finally {
        recorder.stop()
        recorder.release()
    }
}
