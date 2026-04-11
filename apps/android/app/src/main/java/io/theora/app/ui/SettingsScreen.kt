package io.theora.app.ui

import android.content.SharedPreferences
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Cloud
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import io.theora.app.services.BrainClient
import io.theora.app.services.BrainConnectionState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    brainClient: BrainClient,
    prefs: SharedPreferences,
) {
    val connectionState by brainClient.connectionState.collectAsState()
    var host by remember { mutableStateOf(prefs.getString("brain_host", "10.0.2.2") ?: "10.0.2.2") }
    var port by remember { mutableStateOf(prefs.getInt("brain_port", 9090).toString()) }
    var apiKey by remember { mutableStateOf(prefs.getString("brain_api_key", "") ?: "") }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(title = { Text("Settings") })

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            // Connection status
            Card(
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        imageVector = if (connectionState == BrainConnectionState.CONNECTED)
                            Icons.Default.Cloud else Icons.Default.CloudOff,
                        contentDescription = null,
                        tint = when (connectionState) {
                            BrainConnectionState.CONNECTED -> MaterialTheme.colorScheme.primary
                            BrainConnectionState.DISCONNECTED -> MaterialTheme.colorScheme.error
                            else -> MaterialTheme.colorScheme.tertiary
                        },
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                    Column {
                        Text("Brain Connection", style = MaterialTheme.typography.titleSmall)
                        Text(
                            connectionState.name.lowercase().replaceFirstChar { it.uppercase() },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.outline,
                        )
                    }
                    Spacer(modifier = Modifier.weight(1f))
                    if (connectionState == BrainConnectionState.CONNECTED) {
                        OutlinedButton(onClick = { brainClient.disconnect() }) {
                            Text("Disconnect")
                        }
                    } else {
                        Button(onClick = { brainClient.connect() }) {
                            Text("Connect")
                        }
                    }
                }
            }

            // Brain configuration
            Text("Brain Configuration", style = MaterialTheme.typography.titleSmall)

            OutlinedTextField(
                value = host,
                onValueChange = { host = it },
                label = { Text("Host") },
                placeholder = { Text("192.168.1.100") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )

            OutlinedTextField(
                value = port,
                onValueChange = { port = it },
                label = { Text("Port") },
                placeholder = { Text("9090") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )

            OutlinedTextField(
                value = apiKey,
                onValueChange = { apiKey = it },
                label = { Text("API Key") },
                placeholder = { Text("your-api-key") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(),
            )

            Button(
                onClick = {
                    val portInt = port.toIntOrNull() ?: 9090
                    prefs.edit()
                        .putString("brain_host", host)
                        .putInt("brain_port", portInt)
                        .putString("brain_api_key", apiKey)
                        .apply()
                    brainClient.configure(host, portInt, apiKey)
                    brainClient.disconnect()
                    brainClient.connect()
                },
                modifier = Modifier.fillMaxWidth(),
                enabled = host.isNotBlank(),
            ) {
                Text("Save & Reconnect")
            }

            Text(
                "Enter the IP address and port of the THEORA Brain running on your local network.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )

            HorizontalDivider()

            // About
            Text("About THEORA", style = MaterialTheme.typography.titleSmall)

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("Version")
                Text("1.0.0", color = MaterialTheme.colorScheme.outline)
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("Platform")
                Text("Android ${android.os.Build.VERSION.RELEASE}", color = MaterialTheme.colorScheme.outline)
            }
        }
    }
}
