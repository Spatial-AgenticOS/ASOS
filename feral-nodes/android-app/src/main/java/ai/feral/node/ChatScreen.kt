package ai.feral.node

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

data class ChatMessage(val role: String, val text: String, val timestamp: Long = System.currentTimeMillis())

@Composable
fun ChatScreen(onSend: (String) -> Unit, messages: List<ChatMessage>) {
    var inputText by remember { mutableStateOf("") }
    val listState = rememberLazyListState()
    
    Column(modifier = Modifier.fillMaxSize().background(Color(0xFF0A0A0B))) {
        LazyColumn(
            modifier = Modifier.weight(1f).padding(horizontal = 16.dp),
            state = listState,
            verticalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(vertical = 16.dp)
        ) {
            items(messages) { msg ->
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = if (msg.role == "user") Arrangement.End else Arrangement.Start
                ) {
                    Surface(
                        shape = RoundedCornerShape(16.dp),
                        color = if (msg.role == "user") Color(0xFF06B6D4).copy(alpha = 0.2f) else Color(0xFF1A1A2E),
                        modifier = Modifier.widthIn(max = 300.dp)
                    ) {
                        Text(msg.text, modifier = Modifier.padding(12.dp), color = Color.White)
                    }
                }
            }
        }
        
        Divider(color = Color(0xFF333333))
        
        Row(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            OutlinedTextField(
                value = inputText,
                onValueChange = { inputText = it },
                modifier = Modifier.weight(1f),
                placeholder = { Text("Message FERAL...") },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Color(0xFF06B6D4),
                    unfocusedBorderColor = Color(0xFF333333),
                    focusedTextColor = Color.White,
                    unfocusedTextColor = Color.White,
                )
            )
            Spacer(modifier = Modifier.width(8.dp))
            IconButton(
                onClick = {
                    if (inputText.isNotBlank()) {
                        onSend(inputText)
                        inputText = ""
                    }
                }
            ) {
                Text("↑", color = Color(0xFF06B6D4), style = MaterialTheme.typography.headlineMedium)
            }
        }
    }
}
