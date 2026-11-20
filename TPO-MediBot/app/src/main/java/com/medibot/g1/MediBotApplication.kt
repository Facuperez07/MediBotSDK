package com.medibot.g1

import android.app.Application
import android.content.Context
import com.medibot.g1.data.local.AppDatabase
import com.medibot.g1.data.remote.G1SdkClient
import com.medibot.g1.data.repository.AuditRepository
import com.medibot.g1.data.repository.HybridRobotRepository
import com.medibot.g1.data.repository.RobotEventRecorder
import com.medibot.g1.data.repository.RobotRepository
import com.medibot.g1.data.repository.RoomAuditRepository
import com.medibot.g1.data.repository.SimulatedRobotRepository
import com.medibot.g1.data.repository.SimulatorControls
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

/**
 * Contenedor de dependencias manual (inyección por constructor sin Hilt).
 * En modo híbrido (Opción C), utiliza [HybridRobotRepository] para sincronizar
 * actuadores e indicadores con el simulador Python FastAPI del Unitree G1.
 */
class AppContainer(context: Context) {
    private val applicationScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val database = AppDatabase.getInstance(context)
    private val simulator = SimulatedRobotRepository()

    val sdkClient = G1SdkClient()
    val hybridRepository = HybridRobotRepository(simulator, sdkClient, applicationScope)

    val robotRepository: RobotRepository = hybridRepository
    val simulatorControls: SimulatorControls = hybridRepository
    val auditRepository: AuditRepository =
        RoomAuditRepository(database.missionHistoryDao(), database.eventLogDao())

    init {
        RobotEventRecorder(robotRepository, auditRepository, applicationScope).start()
    }
}

class MediBotApplication : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }
}
