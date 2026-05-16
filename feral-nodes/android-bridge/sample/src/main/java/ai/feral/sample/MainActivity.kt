package ai.feral.sample

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import ai.feral.bridge.FeralBrainClient
import ai.feral.bridge.FeralBrainDelegate
import kotlinx.coroutines.*
import kotlinx.serialization.json.JsonObject

class MainActivity : AppCompatActivity(), FeralBrainDelegate {

    private var client: FeralBrainClient? = null
    private lateinit var logView: TextView
    private lateinit var inputField: EditText
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        logView = findViewById(R.id.logView)
        inputField = findViewById(R.id.inputField)
        val connectBtn = findViewById<Button>(R.id.connectBtn)
        val sendBtn = findViewById<Button>(R.id.sendBtn)

        connectBtn.setOnClickListener {
            val host = "10.0.2.2"
            val port = 9090
            val apiKey = BuildConfig.NODE_API_KEY
            client = FeralBrainClient(host, port, apiKey, delegate = this)
            scope.launch(Dispatchers.IO) {
                client?.connect()
            }
            log("Connecting to FERAL Brain at $host:$port...")
        }

        sendBtn.setOnClickListener {
            val text = inputField.text.toString().trim()
            if (text.isNotEmpty() && client != null) {
                scope.launch(Dispatchers.IO) { client?.sendTextCommand(text) }
                log("You: $text")
                inputField.text.clear()
            }
        }
    }

    override fun brainDidConnect() {
        runOnUiThread { log("Connected to FERAL Brain") }
    }

    override fun brainDidDisconnect(reason: String) {
        runOnUiThread { log("Disconnected: $reason") }
    }

    override fun brainDidReceiveText(text: String) {
        runOnUiThread { log("FERAL: $text") }
    }

    override fun brainDidReceiveSDUI(json: JsonObject) {
        runOnUiThread { log("SDUI: ${json.toString().take(100)}...") }
    }

    override fun brainDidReceiveAudio(data: ByteArray, encoding: String, sampleRate: Int) {
        runOnUiThread { log("Audio received (${data.size} bytes, $encoding)") }
    }

    override fun brainDidRequestStopPlayback() {
        runOnUiThread { log("Stop playback requested") }
    }

    override fun brainDidReceiveTranscript(text: String, isPartial: Boolean) {
        runOnUiThread { log("Transcript: $text${if (isPartial) " ..." else ""}") }
    }

    override fun brainDidReceiveExecute(executor: String, action: String, args: JsonObject) {
        runOnUiThread { log("Execute: $executor/$action") }
    }

    private fun log(msg: String) {
        logView.append("$msg\n")
    }

    override fun onDestroy() {
        client?.destroy()
        scope.cancel()
        super.onDestroy()
    }
}
