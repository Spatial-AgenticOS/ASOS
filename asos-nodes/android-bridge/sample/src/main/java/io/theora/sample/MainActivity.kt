package io.theora.sample

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import io.theora.bridge.TheoraBrainClient
import io.theora.bridge.TheoraBrainDelegate
import kotlinx.coroutines.*

class MainActivity : AppCompatActivity(), TheoraBrainDelegate {

    private lateinit var client: TheoraBrainClient
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
            val host = "10.0.2.2"  // Android emulator → host machine
            val port = 9090
            val apiKey = "dev-secret-key"
            client = TheoraBrainClient(host, port, apiKey)
            client.delegate = this
            scope.launch(Dispatchers.IO) {
                client.connect()
            }
            log("Connecting to THEORA Brain at $host:$port...")
        }

        sendBtn.setOnClickListener {
            val text = inputField.text.toString().trim()
            if (text.isNotEmpty() && ::client.isInitialized) {
                scope.launch(Dispatchers.IO) { client.sendTextCommand(text) }
                log("You: $text")
                inputField.text.clear()
            }
        }
    }

    override fun onConnected() {
        runOnUiThread { log("Connected to THEORA Brain") }
    }

    override fun onDisconnected() {
        runOnUiThread { log("Disconnected") }
    }

    override fun onTextResponse(text: String) {
        runOnUiThread { log("THEORA: $text") }
    }

    override fun onSduiResponse(json: String) {
        runOnUiThread { log("SDUI: ${json.take(100)}...") }
    }

    override fun onAudioResponse(base64Audio: String) {
        runOnUiThread { log("Audio received (${base64Audio.length} chars)") }
    }

    override fun onTranscript(text: String) {
        runOnUiThread { log("Transcript: $text") }
    }

    override fun onExecuteCommand(command: String, args: Map<String, Any>) {
        runOnUiThread { log("Execute: $command") }
    }

    private fun log(msg: String) {
        logView.append("$msg\n")
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}
