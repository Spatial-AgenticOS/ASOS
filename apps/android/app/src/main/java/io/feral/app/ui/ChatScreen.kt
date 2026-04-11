package ai.feral.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import ai.feral.app.services.BrainClient
import ai.feral.app.services.BrainConnectionState
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(brainClient: BrainClient) {
    val messages by brainClient.messages.collectAsState()
    val streamingText by brainClient.streamingText.collectAsState()
    val connectionState by brainClient.connectionState.collectAsState()
    var inputText by remember { mutableStateOf("") }
    val listState = rememberLazyListState()
    val coroutineScope = rememberCoroutineScope()

    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.lastIndex)
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(title = { Text("FERAL") })

        if (connectionState != BrainConnectionState.CONNECTED) {
            ConnectionBanner(connectionState)
        }

        LazyColumn(
            state = listState,
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(vertical = 12.dp),
        ) {
            items(messages) { msg ->
                MessageBubble(msg)
            }

            if (streamingText.isNotEmpty()) {
                item {
                    StreamingBubble(streamingText)
                }
            }
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = inputText,
                onValueChange = { inputText = it },
                modifier = Modifier.weight(1f),
                placeholder = { Text("Message FERAL...") },
                shape = RoundedCornerShape(24.dp),
                singleLine = true,
            )

            Spacer(modifier = Modifier.width(8.dp))

            IconButton(
                onClick = {
                    val text = inputText.trim()
                    if (text.isNotEmpty()) {
                        brainClient.sendTextCommand(text)
                        inputText = ""
                        coroutineScope.launch {
                            if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
                        }
                    }
                },
                enabled = inputText.isNotBlank() && connectionState == BrainConnectionState.CONNECTED,
                modifier = Modifier
                    .size(48.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.primary),
            ) {
                Icon(
                    Icons.Default.Send,
                    contentDescription = "Send",
                    tint = MaterialTheme.colorScheme.onPrimary,
                )
            }
        }
    }
}

@Composable
private fun ConnectionBanner(state: BrainConnectionState) {
    val color = when (state) {
        BrainConnectionState.DISCONNECTED -> MaterialTheme.colorScheme.error
        else -> MaterialTheme.colorScheme.tertiary
    }
    val label = when (state) {
        BrainConnectionState.DISCONNECTED -> "Disconnected from Brain"
        BrainConnectionState.CONNECTING, BrainConnectionState.REGISTERING -> "Connecting..."
        BrainConnectionState.RECONNECTING -> "Reconnecting..."
        else -> ""
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(color.copy(alpha = 0.85f))
            .padding(vertical = 6.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(14.dp),
            strokeWidth = 2.dp,
            color = MaterialTheme.colorScheme.onError,
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onError)
    }
}

@Composable
private fun MessageBubble(msg: ai.feral.app.services.ChatMessage) {
    val timeFormat = remember { SimpleDateFormat("h:mm a", Locale.getDefault()) }

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (msg.isUser) Arrangement.End else Arrangement.Start,
    ) {
        Column(horizontalAlignment = if (msg.isUser) Alignment.End else Alignment.Start) {
            Surface(
                shape = RoundedCornerShape(16.dp),
                color = if (msg.isUser) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.surfaceVariant,
                tonalElevation = if (msg.isUser) 0.dp else 1.dp,
            ) {
                Text(
                    text = msg.text,
                    modifier = Modifier.padding(12.dp),
                    color = if (msg.isUser) MaterialTheme.colorScheme.onPrimary
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                text = timeFormat.format(Date(msg.timestamp)),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.outline,
                modifier = Modifier.padding(top = 2.dp, start = 4.dp, end = 4.dp),
            )
        }
    }
}

@Composable
private fun StreamingBubble(text: String) {
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
    ) {
        Text(
            text = text,
            modifier = Modifier.padding(12.dp),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
