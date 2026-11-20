package com.medibot.g1.data.remote

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

/**
 * Datos de telemetría devueltos por el SDK2 FastAPI del Unitree G1.
 */
data class G1SdkTelemetry(
    val connected: Boolean,
    val mode: String,
    val action: String?,
    val batteryPercent: Int,
    val temperatureC: Float,
    val ledR: Int,
    val ledG: Int,
    val ledB: Int,
    val volume: Int,
    val lastTts: String?,
    val imuRollDeg: Float,
    val imuPitchDeg: Float,
    val imuYawDeg: Float,
    val bmsSoc: Int,
    val bmsSoh: Int,
    val bmsCurrent: Int
)

/**
 * Cliente HTTP para comunicarse con el simulador FastAPI del Unitree G1.
 * Funciona de manera nativa en Android con HttpURLConnection (sin dependencias adicionales).
 */
class G1SdkClient(
    private var baseUrl: String = DEFAULT_BASE_URL
) {
    fun setBaseUrl(url: String) {
        baseUrl = url.trimEnd('/')
    }

    fun getBaseUrl(): String = baseUrl

    /**
     * Verifica conectividad con el backend FastAPI del G1.
     */
    suspend fun checkHealth(): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val response = executeRequest("GET", "/api/robots/g1/state", null, timeoutMs = 1500)
            response.has("id") && response.optString("id") == "g1"
        }
    }

    /**
     * Obtiene la telemetría actual del G1 desde el SDK FastAPI.
     */
    suspend fun getTelemetry(): Result<G1SdkTelemetry> = withContext(Dispatchers.IO) {
        runCatching {
            val json = executeRequest("GET", "/api/robots/g1/telemetry", null, timeoutMs = 2000)

            val ledObj = json.optJSONObject("led")
            val ttsObj = json.optJSONObject("last_tts")
            val sensorsObj = json.optJSONObject("sensors")
            val bmsObj = sensorsObj?.optJSONObject("bms_state")
            val lowStateObj = sensorsObj?.optJSONObject("low_state")
            val imuObj = lowStateObj?.optJSONObject("imu_state")
            val rpyArray = imuObj?.optJSONArray("rpy")

            val deg = 180.0f / Math.PI.toFloat()
            val roll = (rpyArray?.optDouble(0, 0.0) ?: 0.0).toFloat() * deg
            val pitch = (rpyArray?.optDouble(1, 0.0) ?: 0.0).toFloat() * deg
            val yaw = (rpyArray?.optDouble(2, 0.0) ?: 0.0).toFloat() * deg

            G1SdkTelemetry(
                connected = json.optBoolean("connected", true),
                mode = json.optString("mode", "idle"),
                action = if (json.isNull("action")) null else json.optString("action"),
                batteryPercent = json.optInt("battery_percent", 85),
                temperatureC = json.optDouble("temperature_c", 32.0).toFloat(),
                ledR = ledObj?.optInt("r", 0) ?: 0,
                ledG = ledObj?.optInt("g", 0) ?: 0,
                ledB = ledObj?.optInt("b", 0) ?: 0,
                volume = json.optInt("volume", 50),
                lastTts = ttsObj?.optString("text"),
                imuRollDeg = roll,
                imuPitchDeg = pitch,
                imuYawDeg = yaw,
                bmsSoc = bmsObj?.optInt("soc", 85) ?: 85,
                bmsSoh = bmsObj?.optInt("soh", 98) ?: 98,
                bmsCurrent = bmsObj?.optInt("current", 0) ?: 0
            )
        }
    }

    /**
     * PUT /api/robots/g1/led
     * Sincroniza el color del LED RGB del G1.
     */
    suspend fun setLed(r: Int, g: Int, b: Int): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val body = JSONObject().apply {
                put("r", r.coerceIn(0, 255))
                put("g", g.coerceIn(0, 255))
                put("b", b.coerceIn(0, 255))
            }
            val res = executeRequest("PUT", "/api/robots/g1/led", body.toString())
            res.optBoolean("ok", false)
        }
    }

    /**
     * Convierte un código hexadecimal (#RRGGBB) a RGB y lo envía al G1.
     */
    suspend fun setLedHex(hexColor: String): Result<Boolean> {
        val clean = hexColor.removePrefix("#")
        return if (clean.length == 6) {
            val r = clean.substring(0, 2).toIntOrNull(16) ?: 0
            val g = clean.substring(2, 4).toIntOrNull(16) ?: 0
            val b = clean.substring(4, 6).toIntOrNull(16) ?: 0
            setLed(r, g, b)
        } else {
            Result.failure(IllegalArgumentException("Formato hex no válido: $hexColor"))
        }
    }

    /**
     * POST /api/robots/g1/audio/tts
     * Envía una solicitud de síntesis de voz al simulador del G1.
     */
    suspend fun sendTts(text: String, speakerId: Int = 0): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val trimmed = text.take(200)
            val body = JSONObject().apply {
                put("text", trimmed)
                put("speaker_id", speakerId.coerceIn(0, 255))
            }
            val res = executeRequest("POST", "/api/robots/g1/audio/tts", body.toString())
            res.optBoolean("ok", false)
        }
    }

    /**
     * PUT /api/robots/g1/audio/volume
     */
    suspend fun setVolume(volume: Int): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val body = JSONObject().apply {
                put("volume", volume.coerceIn(0, 100))
            }
            val res = executeRequest("PUT", "/api/robots/g1/audio/volume", body.toString())
            res.optBoolean("ok", false)
        }
    }

    /**
     * POST /api/robots/g1/commands/greeting (WaveHand)
     */
    suspend fun waveHand(turnFlag: Boolean = false): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val body = JSONObject().apply {
                put("turn_flag", turnFlag)
            }
            val res = executeRequest("POST", "/api/robots/g1/commands/greeting", body.toString())
            res.optBoolean("accepted", false)
        }
    }

    /**
     * POST /api/robots/g1/commands/handshake (ShakeHand)
     */
    suspend fun handshake(stage: Int = -1): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val body = JSONObject().apply {
                put("stage", stage)
            }
            val res = executeRequest("POST", "/api/robots/g1/commands/handshake", body.toString())
            res.optBoolean("accepted", false)
        }
    }

    /**
     * POST /api/robots/g1/commands/high-five (ExecuteAction 18)
     */
    suspend fun highFive(): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val res = executeRequest("POST", "/api/robots/g1/commands/high-five", null)
            res.optBoolean("accepted", false)
        }
    }

    /**
     * POST /api/robots/g1/commands/release-arms (ExecuteAction 99)
     */
    suspend fun releaseArms(): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val res = executeRequest("POST", "/api/robots/g1/commands/release-arms", null)
            res.optBoolean("accepted", false)
        }
    }

    /**
     * POST /api/robots/g1/medibot/status
     * Notifica al SDK FastAPI sobre el estado de la misión hospitalaria en MediBot.
     */
    suspend fun updateMediBotStatus(
        state: String,
        missionName: String?,
        currentNode: String?,
        progressPct: Int,
        voice: String?,
        tamper: Boolean = false
    ): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val body = JSONObject().apply {
                put("operational_state", state)
                put("mission_name", missionName ?: JSONObject.NULL)
                put("current_node", currentNode ?: JSONObject.NULL)
                put("progress_pct", progressPct.coerceIn(0, 100))
                put("hri_voice", voice ?: JSONObject.NULL)
                put("tamper_alert", tamper)
            }
            val res = executeRequest("POST", "/api/robots/g1/medibot/status", body.toString(), timeoutMs = 1500)
            res.optBoolean("ok", false)
        }
    }

    private fun executeRequest(
        method: String,
        path: String,
        jsonBody: String?,
        timeoutMs: Int = 2500
    ): JSONObject {
        val targetUrl = "$baseUrl$path"
        val connection = (URL(targetUrl).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = timeoutMs
            readTimeout = timeoutMs
            setRequestProperty("Accept", "application/json")
            if (jsonBody != null) {
                setRequestProperty("Content-Type", "application/json")
                doOutput = true
            }
        }

        try {
            if (jsonBody != null) {
                OutputStreamWriter(connection.outputStream, "UTF-8").use { writer ->
                    writer.write(jsonBody)
                    writer.flush()
                }
            }

            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val responseText = stream?.let {
                BufferedReader(InputStreamReader(it, "UTF-8")).use { reader ->
                    reader.readText()
                }
            } ?: "{}"

            return if (responseText.isNotBlank() && responseText.startsWith("{")) {
                JSONObject(responseText)
            } else {
                JSONObject().apply { put("statusCode", status) }
            }
        } finally {
            connection.disconnect()
        }
    }

    companion object {
        /**
         * IP por defecto del anfitrión vista desde el emulador de Android (10.0.2.2).
         * Si se usa un dispositivo físico en la misma red Wi-Fi, se reemplaza por la IP local de la PC.
         */
        const val DEFAULT_BASE_URL = "http://10.0.2.2:8000"
        const val LOCALHOST_URL = "http://127.0.0.1:8000"
    }
}
