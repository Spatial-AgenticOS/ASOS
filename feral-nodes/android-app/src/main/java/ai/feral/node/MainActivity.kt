package ai.feral.node

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme()) {
                FeralNodeApp()
            }
        }
    }
}

@Composable
fun FeralNodeApp() {
    var isConnected by remember { mutableStateOf(false) }
    var host by remember { mutableStateOf("") }
    var port by remember { mutableStateOf("9090") }
    var apiKey by remember { mutableStateOf("") }
    var statusText by remember { mutableStateOf("Not connected") }
    
    Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(
            modifier = Modifier.fillMaxSize().padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Text("FERAL Node", style = MaterialTheme.typography.headlineLarge)
            
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Surface(modifier = Modifier.size(12.dp), shape = MaterialTheme.shapes.small,
                    color = if (isConnected) Color.Green else Color.Red) {}
                Text(statusText, style = MaterialTheme.typography.bodyLarge)
            }
            
            Spacer(modifier = Modifier.height(16.dp))
            
            if (!isConnected) {
                OutlinedTextField(value = host, onValueChange = { host = it },
                    label = { Text("Brain Host") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(value = port, onValueChange = { port = it },
                    label = { Text("Port") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(value = apiKey, onValueChange = { apiKey = it },
                    label = { Text("API Key") }, modifier = Modifier.fillMaxWidth())
                
                Button(onClick = {
                    statusText = "Connecting..."
                    // TODO: Wire to FeralBrainClient
                    isConnected = true
                    statusText = "Connected to $host:$port"
                }, modifier = Modifier.fillMaxWidth()) {
                    Text("Connect")
                }
                
                OutlinedButton(onClick = {
                    // TODO: Launch QR scanner
                }, modifier = Modifier.fillMaxWidth()) {
                    Text("Scan QR Code to Pair")
                }
            } else {
                Button(onClick = {
                    isConnected = false
                    statusText = "Disconnected"
                }, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                    modifier = Modifier.fillMaxWidth()) {
                    Text("Disconnect")
                }
            }
        }
    }
}
