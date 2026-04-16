package ai.feral.node

import android.app.*
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat

class FeralForegroundService : Service() {
    companion object {
        const val CHANNEL_ID = "feral_service"
        const val NOTIFICATION_ID = 1001
    }
    
    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("FERAL Node")
            .setContentText("Connected to Brain — relaying health data")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .build()
        startForeground(NOTIFICATION_ID, notification)
    }
    
    override fun onBind(intent: Intent?): IBinder? = null
    
    private fun createNotificationChannel() {
        val channel = NotificationChannel(CHANNEL_ID, "FERAL Service", NotificationManager.IMPORTANCE_LOW)
        channel.description = "Keeps FERAL connected to the Brain"
        getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
    }
}
