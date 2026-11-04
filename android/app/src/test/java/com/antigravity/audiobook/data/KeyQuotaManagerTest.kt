package com.antigravity.audiobook.data

import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class KeyQuotaManagerTest {

    @get:Rule
    val tempFolder = TemporaryFolder()

    private lateinit var storageDir: File
    private lateinit var quotaManager: KeyQuotaManager

    private val testKey1 = "AIzaSyKey111111111111111111111111"
    private val testKey2 = "AIzaSyKey222222222222222222222222"
    private val modelId = "gemini-3.8-flash-tts"

    @Before
    fun setUp() {
        storageDir = tempFolder.newFolder("quota_test")
        quotaManager = KeyQuotaManager(storageDir)
    }

    @Test
    fun testComputeKeyIdAndMask() {
        val keyId = KeyQuotaManager.computeKeyId(testKey1)
        assertEquals(16, keyId.length)

        val masked = KeyQuotaManager.maskKey(testKey1)
        assertTrue(masked.startsWith("AIzaSy..."))
        assertTrue(masked.endsWith("1111"))
    }

    @Test
    fun testParseRetryDelayFromJson() {
        val jsonError = """
            {
              "error": {
                "code": 429,
                "message": "Resource exhausted",
                "details": [
                  {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "45s"
                  }
                ]
              }
            }
        """.trimIndent()

        val delay = KeyQuotaManager.parseRetryDelay(jsonError)
        assertEquals(45L, delay)
    }

    @Test
    fun testParseRetryDelayFromRegex() {
        val textError = "Quota exceeded for project. Please retry in 1m 30s."
        val delay = KeyQuotaManager.parseRetryDelay(textError)
        assertEquals(90L, delay)
    }

    @Test
    fun testSecondsUntilPacificMidnight() {
        val seconds = KeyQuotaManager.getSecondsUntilPacificMidnight()
        assertTrue("Seconds until Pacific midnight should be positive", seconds > 0)
        assertTrue("Seconds until Pacific midnight should be <= 86400", seconds <= 86400)
    }

    @Test
    fun testKeyAvailabilityAnd429Exhaustion() {
        assertTrue(quotaManager.isKeyAvailable(testKey1, modelId))

        // Record 429 with 3600s delay
        quotaManager.record429Exhaustion(testKey1, modelId, retryDelaySeconds = 3600L, errorMessage = "Rate limited")
        assertFalse(quotaManager.isKeyAvailable(testKey1, modelId))

        // Persistence test: new instance from same directory reads exhausted state
        val reloadedManager = KeyQuotaManager(storageDir)
        assertFalse(reloadedManager.isKeyAvailable(testKey1, modelId))
    }

    @Test
    fun testAutoRenewalWhenResetTimePassed() {
        // Record exhaustion that expired 10 seconds ago
        quotaManager.record429Exhaustion(testKey1, modelId, retryDelaySeconds = -10L)

        // Should automatically renew to AVAILABLE
        assertTrue(quotaManager.isKeyAvailable(testKey1, modelId))
    }

    @Test
    fun testKeyRotationSelection() {
        val keys = listOf(testKey1, testKey2)

        // Both available -> first index
        assertEquals(0, quotaManager.findFirstAvailableKeyIndex(keys, modelId))

        // Key 1 exhausted -> advances to Key 2
        quotaManager.record429Exhaustion(testKey1, modelId, retryDelaySeconds = 3600L)
        assertEquals(1, quotaManager.findFirstAvailableKeyIndex(keys, modelId))

        val (nextIdx, nextKey) = quotaManager.getNextAvailableKey(keys, 0, modelId)
        assertEquals(1, nextIdx)
        assertEquals(testKey2, nextKey)
    }
}
