package io.feral.bridge

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.core.app.ActivityCompat
import com.google.android.gms.location.*

class LocationManager(
    private val context: Context,
    private val onLocation: (Map<String, Any>) -> Unit
) {
    private val fusedClient = LocationServices.getFusedLocationProviderClient(context)
    private val callback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            result.lastLocation?.let { location ->
                onLocation(mapOf(
                    "latitude" to location.latitude,
                    "longitude" to location.longitude,
                    "altitude" to location.altitude,
                    "accuracy" to location.accuracy,
                    "speed" to location.speed,
                    "timestamp" to (location.time / 1000.0)
                ))
            }
        }
    }

    fun start() {
        if (ActivityCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION)
            != PackageManager.PERMISSION_GRANTED) return

        val request = LocationRequest.Builder(Priority.PRIORITY_BALANCED_POWER_ACCURACY, 60000)
            .setMinUpdateDistanceMeters(100f)
            .build()
        fusedClient.requestLocationUpdates(request, callback, context.mainLooper)
    }

    fun stop() {
        fusedClient.removeLocationUpdates(callback)
    }
}
