package com.medibot.g1.data.repository

import com.medibot.g1.data.model.CommandExecutionState
import com.medibot.g1.data.model.MissionCatalog
import com.medibot.g1.data.model.RobotCommand
import com.medibot.g1.data.remote.G1SdkClient
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class HybridRobotRepositoryTest {

    @Test
    fun `hybrid repository delegates commands to underlying simulation`() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        val underlying = SimulatedRobotRepository(dispatcher = dispatcher, clock = { testScheduler.currentTime })
        val client = G1SdkClient(G1SdkClient.DEFAULT_BASE_URL)
        val hybrid = HybridRobotRepository(underlying, client, TestScope(dispatcher))

        try {
            // Verify initial state
            assertEquals(underlying.telemetry.value, hybrid.telemetry.value)

            // Verify delegation of sendCommand
            val command = RobotCommand.StartMission(MissionCatalog.bloodGas)
            val result = hybrid.sendCommand(command, "OP-TEST")
            assertTrue(result is CommandExecutionState.Confirmed)
            assertEquals("OP-TEST", (result as CommandExecutionState.Confirmed).operatorId)

            // Verify bridge controls
            assertTrue(hybrid.isSdkEnabled.value)
            hybrid.setSdkEnabled(false)
            assertFalse(hybrid.isSdkEnabled.value)
            assertFalse(hybrid.isSdkConnected.value)

            hybrid.setSdkUrl("http://localhost:8000")
            assertEquals("http://localhost:8000", client.getBaseUrl())
        } finally {
            underlying.shutdown()
        }
    }

    @Test
    fun `sdk client parses hex colors properly`() = runTest {
        val client = G1SdkClient("http://127.0.0.1:8000")
        // Invalid hex
        val invalidResult = client.setLedHex("invalid")
        assertTrue(invalidResult.isFailure)

        // Valid hex format validation (fails with network error since no server is running in unit test, but doesn't throw IllegalArgumentException)
        val validResult = client.setLedHex("#00F5D4")
        assertTrue(validResult.isFailure) // Network failure, not syntax failure
        assertFalse(validResult.exceptionOrNull() is IllegalArgumentException)
    }
}
