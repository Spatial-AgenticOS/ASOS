package ai.feral.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.feral.app.services.BrainClient

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HealthScreen(brainClient: BrainClient) {
    var heartRate by remember { mutableIntStateOf(0) }
    var spo2 by remember { mutableIntStateOf(0) }
    var steps by remember { mutableIntStateOf(0) }
    var calories by remember { mutableIntStateOf(0) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
    ) {
        TopAppBar(title = { Text("Health") })

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            MetricCard(
                modifier = Modifier.weight(1f),
                title = "Heart Rate",
                value = if (heartRate > 0) "$heartRate" else "--",
                unit = "BPM",
                icon = Icons.Default.Favorite,
                color = Color(0xFFE53935),
            )
            MetricCard(
                modifier = Modifier.weight(1f),
                title = "SpO\u2082",
                value = if (spo2 > 0) "$spo2" else "--",
                unit = "%",
                icon = Icons.Default.Air,
                color = Color(0xFF1E88E5),
            )
        }

        Spacer(modifier = Modifier.height(12.dp))

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            MetricCard(
                modifier = Modifier.weight(1f),
                title = "Steps",
                value = if (steps > 0) "$steps" else "--",
                unit = "today",
                icon = Icons.Default.DirectionsWalk,
                color = Color(0xFF43A047),
            )
            MetricCard(
                modifier = Modifier.weight(1f),
                title = "Calories",
                value = if (calories > 0) "$calories" else "--",
                unit = "kcal",
                icon = Icons.Default.LocalFireDepartment,
                color = Color(0xFFFB8C00),
            )
        }

        Spacer(modifier = Modifier.height(24.dp))

        WristbandCard()

        Spacer(modifier = Modifier.height(24.dp))

        HealthConnectCard()
    }
}

@Composable
private fun MetricCard(
    modifier: Modifier = Modifier,
    title: String,
    value: String,
    unit: String,
    icon: ImageVector,
    color: Color,
) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(18.dp))
                Spacer(modifier = Modifier.width(6.dp))
                Text(title, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
            }
            Spacer(modifier = Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    text = value,
                    fontSize = 32.sp,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text(
                    text = unit,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                    modifier = Modifier.padding(bottom = 4.dp),
                )
            }
        }
    }
}

@Composable
private fun WristbandCard() {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Watch, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                Spacer(modifier = Modifier.width(8.dp))
                Text("FERAL Wristband", style = MaterialTheme.typography.titleSmall)
            }
            Spacer(modifier = Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .padding(0.dp),
                ) {
                    Surface(
                        shape = MaterialTheme.shapes.extraSmall,
                        color = MaterialTheme.colorScheme.outline,
                        modifier = Modifier.size(8.dp),
                    ) {}
                }
                Spacer(modifier = Modifier.width(8.dp))
                Text("Not connected", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
            }
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                "Connect your FERAL wristband via Bluetooth to stream real-time sensor data to the Brain.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )
        }
    }
}

@Composable
private fun HealthConnectCard() {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.HealthAndSafety, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                Spacer(modifier = Modifier.width(8.dp))
                Text("Health Connect", style = MaterialTheme.typography.titleSmall)
            }
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                "Install Google Health Connect to sync health data from wearables and other fitness apps.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )
        }
    }
}
