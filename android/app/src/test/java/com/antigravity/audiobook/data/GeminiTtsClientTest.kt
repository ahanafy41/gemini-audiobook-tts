package com.antigravity.audiobook.data

import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class GeminiTtsClientTest {

    @get:Rule
    val tempFolder = TemporaryFolder()

    private lateinit var quotaManager: KeyQuotaManager
    private val key1 = "AIzaSyKey111111111111111111111111"
    private val key2 = "AIzaSyKey222222222222222222222222"

    @Before
    fun setUp() {
        val storageDir = tempFolder.newFolder("client_test")
        quotaManager = KeyQuotaManager(storageDir)
    }

    @Test
    fun testMultiKeyInitialization() {
        val client = GeminiTtsClient(
            apiKeys = listOf(key1, key2),
            quotaManager = quotaManager
        )

        assertTrue(client.hasApiKey())
        assertEquals(2, client.getApiKeys().size)
        assertEquals(key1, client.getActiveApiKey())
    }

    @Test
    fun testBackwardCompatibilityConstructor() {
        val client = GeminiTtsClient(key1)
        assertTrue(client.hasApiKey())
        assertEquals(1, client.getApiKeys().size)
        assertEquals(key1, client.getActiveApiKey())
    }

    @Test
    fun testKeyRotationWhenFirstKeyExhausted() {
        val client = GeminiTtsClient(
            apiKeys = listOf(key1, key2),
            quotaManager = quotaManager
        )

        // Mark key1 exhausted
        quotaManager.record429Exhaustion(key1, client.modelId, retryDelaySeconds = 3600L)

        // Active key should now automatically be key2
        assertEquals(key2, client.getActiveApiKey())
    }
}
