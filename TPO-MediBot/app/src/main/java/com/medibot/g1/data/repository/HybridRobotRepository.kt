package com.medibot.g1.data.repository

import com.medibot.g1.data.model.CommandExecutionState
import com.medibot.g1.data.model.MissionStatus
import com.medibot.g1.data.model.OperationalState
import com.medibot.g1.data.model.RobotCommand
import com.medibot.g1.data.model.RobotEvent
import com.medibot.g1.data.model.TelemetryState
import com.medibot.g1.data.remote.G1SdkClient
import com.medibot.g1.data.remote.G1SdkTelemetry
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Repositorio Híbrido (Opción C):
 * Conserva la lógica de misiones, seguridad y máquina de estados de MediBot,
 * pero sincroniza en tiempo real los actuadores e indicadores del robot con el simulador
 * Python FastAPI del Unitree G1 (LED RGB, síntesis de voz TTS, gestos y telemetría BMS/IMU).
 */
class HybridRobotRepository(
    private val underlying: SimulatedRobotRepository,
    val sdkClient: G1SdkClient,
    private val scope: CoroutineScope
) : RobotRepository, SimulatorControls {

    private val _isSdkConnected = MutableStateFlow(false)
    val isSdkConnected: StateFlow<Boolean> = _isSdkConnected.asStateFlow()

    private val _isSdkEnabled = MutableStateFlow(true)
    val isSdkEnabled: StateFlow<Boolean> = _isSdkEnabled.asStateFlow()

    private val _lastSdkTelemetry = MutableStateFlow<G1SdkTelemetry?>(null)
    val lastSdkTelemetry: StateFlow<G1SdkTelemetry?> = _lastSdkTelemetry.asStateFlow()

    private var syncJob: Job? = null
    private var telemetryObserverJob: Job? = null
    private var eventObserverJob: Job? = null

    init {
        startSyncLoops()
    }

    private fun startSyncLoops() {
        // 1. Bucle de consulta periódica al SDK FastAPI (cada 1.5s)
        syncJob = scope.launch {
            while (isActive) {
                if (_isSdkEnabled.value) {
                    val result = sdkClient.getTelemetry()
                    if (result.isSuccess) {
                        val sdkData = result.getOrNull()
                        _isSdkConnected.value = true
                        _lastSdkTelemetry.value = sdkData
                    } else {
                        _isSdkConnected.value = false
                    }
                } else {
                    _isSdkConnected.value = false
                }
                delay(1500)
            }
        }

        // 2. Observar cambios en la telemetría interna de MediBot para reflejarlos en el SDK
        telemetryObserverJob = scope.launch {
            var lastColor = ""
            var lastVoice = ""
            var lastState: OperationalState? = null

            underlying.telemetry.collect { telemetry ->
                if (!_isSdkEnabled.value || !_isSdkConnected.value) return@collect

                // Sincronizar color del LED si cambió
                if (telemetry.hriLedColor != lastColor) {
                    lastColor = telemetry.hriLedColor
                    sdkClient.setLedHex(lastColor)
                }

                // Sincronizar mensaje de voz HRI (TTS) si cambió
                if (telemetry.hriVoiceStatus != lastVoice && telemetry.hriVoiceStatus.isNotBlank()) {
                    lastVoice = telemetry.hriVoiceStatus
                    sdkClient.sendTts(lastVoice)
                }

                // Sincronizar gestos automáticos según el estado
                if (telemetry.operationalState != lastState) {
                    val previous = lastState
                    lastState = telemetry.operationalState

                    when (telemetry.operationalState) {
                        OperationalState.AWAITING_NFC_HANDOFF -> {
                            // Saludar al personal médico al llegar a destino
                            sdkClient.waveHand(turnFlag = false)
                        }
                        OperationalState.EMERGENCY_STOPPED -> {
                            // En detención operativa forzar LED rojo
                            sdkClient.setLed(255, 0, 0)
                        }
                        else -> Unit
                    }
                }

                // Informar a FastAPI sobre la misión activa para el panel web
                sdkClient.updateMediBotStatus(
                    state = telemetry.operationalState.displayName,
                    missionName = telemetry.currentMission?.name,
                    currentNode = telemetry.currentNode.displayName,
                    progressPct = telemetry.missionProgressPct,
                    voice = telemetry.hriVoiceStatus,
                    tamper = telemetry.servicePayload.smartLockState.name == "TAMPER_ALERT"
                )
            }
        }

        // 3. Observar eventos discretos de misiones
        eventObserverJob = scope.launch {
            underlying.events.collect { event ->
                if (!_isSdkEnabled.value || !_isSdkConnected.value) return@collect

                when (event) {
                    is RobotEvent.MissionFinished -> {
                        if (event.outcome.status == MissionStatus.COMPLETED) {
                            // Celebrar entrega exitosa con High Five (chocar los cinco)
                            scope.launch {
                                sdkClient.highFive()
                                delay(3200)
                                sdkClient.releaseArms()
                            }
                        }
                    }
                    else -> Unit
                }
            }
        }
    }

    // ---------- Controles del Puente SDK ----------

    fun setSdkEnabled(enabled: Boolean) {
        _isSdkEnabled.value = enabled
        if (!enabled) {
            _isSdkConnected.value = false
        }
    }

    fun setSdkUrl(url: String) {
        sdkClient.setBaseUrl(url)
    }

    suspend fun testSdkConnection(): Boolean {
        val ok = sdkClient.checkHealth().getOrDefault(false)
        _isSdkConnected.value = ok
        return ok
    }

    suspend fun triggerWaveHand(turnFlag: Boolean = false): Boolean {
        return sdkClient.waveHand(turnFlag).getOrDefault(false)
    }

    suspend fun triggerHighFive(): Boolean {
        return sdkClient.highFive().getOrDefault(false)
    }

    suspend fun triggerReleaseArms(): Boolean {
        return sdkClient.releaseArms().getOrDefault(false)
    }

    // ---------- Delegación de RobotRepository ----------

    override val telemetry: StateFlow<TelemetryState>
        get() = underlying.telemetry

    override val commandState: StateFlow<CommandExecutionState>
        get() = underlying.commandState

    override val events: Flow<RobotEvent>
        get() = underlying.events

    override suspend fun sendCommand(
        command: RobotCommand,
        operatorId: String
    ): CommandExecutionState {
        return underlying.sendCommand(command, operatorId)
    }

    // ---------- Delegación de SimulatorControls ----------

    override val forceRejectNext: StateFlow<Boolean>
        get() = underlying.forceRejectNext

    override val linkUp: StateFlow<Boolean>
        get() = underlying.linkUp

    override fun setForceRejectNext(value: Boolean) {
        underlying.setForceRejectNext(value)
    }

    override fun injectScenario(scenario: SimulationScenario) {
        underlying.injectScenario(scenario)
    }

    override fun restoreConnection() {
        underlying.restoreConnection()
    }

    override fun resetSimulation() {
        underlying.resetSimulation()
    }

    override fun physicalRearm() {
        underlying.physicalRearm()
    }

    override fun physicalBatterySwap() {
        underlying.physicalBatterySwap()
    }
}
