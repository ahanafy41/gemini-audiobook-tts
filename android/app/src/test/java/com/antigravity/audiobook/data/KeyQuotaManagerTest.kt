package com.antigravity.audiobook.data

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.charset.StandardCharsets

class KeyQuotaManagerTest {

    @get:Rule
    val tempFolder = TemporaryFolder()

    private lateinit var storageDir: File
    private lateinit var quotaManager: KeyQuotaManager

    private val testKey1 = "AIzaSyKey111111111111111111111111"
    private val testKey2 = "AIzaSyKey222222222222222222222222"
    private val testKey3 = "AIzaSyKey333333333333333333333333"
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

    @Test
    fun testNextAvailableKeyWrapAroundModulo() {
        val keys = listOf(testKey1, testKey2, testKey3)

        // currentIndex is the last element (2).
        // Keys 0 and 1 are available.
        // It must wrap around modulo and return index 0 (testKey1).
        val (wrappedIdx, wrappedKey) = quotaManager.getNextAvailableKey(keys, currentIndex = 2, modelId = modelId)
        assertEquals(0, wrappedIdx)
        assertEquals(testKey1, wrappedKey)

        // Now exhaust Key 1 (index 0). Wrapping from index 2 should find index 1 (testKey2).
        quotaManager.record429Exhaustion(testKey1, modelId, retryDelaySeconds = 3600L)
        val (wrappedIdx2, wrappedKey2) = quotaManager.getNextAvailableKey(keys, currentIndex = 2, modelId = modelId)
        assertEquals(1, wrappedIdx2)
        assertEquals(testKey2, wrappedKey2)

        // Now exhaust Key 2 as well.
        quotaManager.record429Exhaustion(testKey2, modelId, retryDelaySeconds = 3600L)
        val (wrappedIdx3, wrappedKey3) = quotaManager.getNextAvailableKey(keys, currentIndex = 2, modelId = modelId)
        assertEquals(-1, wrappedIdx3)
        assertNull(wrappedKey3)
    }

    @Test
    fun test429TransientFallbackVsPacificMidnight() {
        val now = System.currentTimeMillis() / 1000

        // 1. Transient 429 without retryDelaySeconds and with generic error message:
        // Must fallback to 60s transient backoff instead of locking out until Pacific midnight.
        val transientReset = quotaManager.record429Exhaustion(
            testKey1,
            modelId,
            retryDelaySeconds = null,
            errorMessage = "HTTP 429 Too Many Requests"
        )
        val transientDelay = transientReset - now
        assertTrue("Transient delay should be close to 60s", transientDelay in 55..65)

        // 2. Explicit retryDelaySeconds:
        val explicitReset = quotaManager.record429Exhaustion(
            testKey2,
            modelId,
            retryDelaySeconds = 42L,
            errorMessage = "Please wait"
        )
        val explicitDelay = explicitReset - now
        assertTrue("Explicit delay should be close to 42s", explicitDelay in 40..45)

        // 3. Quota exhaustion message without explicit retryDelay:
        // Must lock until Pacific midnight.
        val midnightReset = quotaManager.record429Exhaustion(
            testKey3,
            modelId,
            retryDelaySeconds = null,
            errorMessage = "RESOURCE_EXHAUSTED: Quota exceeded for model"
        )
        val midnightDelay = midnightReset - now
        val expectedMinDelay = KeyQuotaManager.getSecondsUntilPacificMidnight() - 5
        assertTrue("Quota error should lock until Pacific midnight", midnightDelay >= expectedMinDelay - 5)
    }

    @Test
    fun testNextDayPacificDateCounterReset() {
        // Record success today
        quotaManager.recordSuccess(testKey1, modelId)
        assertEquals(1, quotaManager.getRequestsToday(testKey1, modelId))
        val todayStr = KeyQuotaManager.getPacificDateString()
        assertEquals(todayStr, quotaManager.getLastRequestDate(testKey1, modelId))

        // Simulate day rollover by altering the persisted file to an older date
        val jsonFile = File(storageDir, KeyQuotaManager.DEFAULT_FILENAME)
        assertTrue(jsonFile.exists())
        val json = JSONObject(jsonFile.readText(StandardCharsets.UTF_8))
        val keyId = KeyQuotaManager.computeKeyId(testKey1)
        val modelRec = json.getJSONObject("keys").getJSONObject(keyId).getJSONObject("models").getJSONObject(modelId)
        modelRec.put("last_request_date", "2020-01-01")
        modelRec.put("requests_today", 85)
        jsonFile.writeText(json.toString(2), StandardCharsets.UTF_8)

        // Reload fresh instance
        val reloaded = KeyQuotaManager(storageDir)
        // isKeyAvailable should detect day rollover and reset requests_today to 0
        assertTrue(reloaded.isKeyAvailable(testKey1, modelId))
        assertEquals(0, reloaded.getRequestsToday(testKey1, modelId))
        assertEquals(todayStr, reloaded.getLastRequestDate(testKey1, modelId))

        // Subsequent success increments from 0 to 1
        reloaded.recordSuccess(testKey1, modelId)
        assertEquals(1, reloaded.getRequestsToday(testKey1, modelId))
    }

    @Test
    fun testPaidAccountNotBlockedByArtificialLimit() {
        // Ensure paid users can make more than the old 100 daily limit without artificial blocking
        repeat(110) {
            quotaManager.recordSuccess(testKey1, modelId)
        }
        assertEquals(110, quotaManager.getRequestsToday(testKey1, modelId))
        assertTrue("Key should remain available after >100 requests for paid tier", quotaManager.isKeyAvailable(testKey1, modelId))
    }
}
