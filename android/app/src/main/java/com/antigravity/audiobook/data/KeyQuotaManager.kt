package com.antigravity.audiobook.data

import android.util.Log
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.time.Duration
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.Locale
import java.util.regex.Pattern

/**
 * مدير الحصص المستمر وإدارة المفاتيح الذكية لنماذج Gemini TTS على الأندرويد.
 * يحفظ حالة وحصص المفاتيح في ملف key_quotas.json بشكل ذري وآمن،
 * ويحسب توقيت التصفير الرسمي لجوجل (منتصف الليل بتوقيت المحيط الهادئ Pacific Time)،
 * ويستخرج فترات الانتظار retryDelay من أخطاء HTTP 429 تلقائياً.
 */
class KeyQuotaManager(private val storageDir: File) {

    companion object {
        private const val TAG = "KeyQuotaManager"
        const val DEFAULT_FILENAME = "key_quotas.json"
        const val DEFAULT_TRANSIENT_RETRY_DELAY = 60L
        val PACIFIC_ZONE: ZoneId = ZoneId.of("America/Los_Angeles")

        @Deprecated("Artificial cap removed; Google Cloud server enforces quota limits via 429")
        val MODEL_DAILY_CAPS = mapOf(
            "gemini-3.8-flash-tts" to 100,
            "gemini-3.8-flash-lite-tts" to 100,
            "gemini-3.1-flash-tts-preview" to 10,
            "gemini-2.5-flash-preview-tts" to 10,
            "gemini-2.5-pro-preview-tts" to 10
        )
        @Deprecated("Artificial cap removed; Google Cloud server enforces quota limits via 429")
        const val DEFAULT_DAILY_CAP = 10

        fun computeKeyId(apiKey: String): String {
            val clean = apiKey.trim()
            if (clean.isEmpty()) return ""
            return try {
                val digest = MessageDigest.getInstance("SHA-256")
                val hashBytes = digest.digest(clean.toByteArray(StandardCharsets.UTF_8))
                hashBytes.joinToString("") { "%02x".format(it) }.take(16)
            } catch (e: Exception) {
                clean.take(16)
            }
        }

        fun maskKey(apiKey: String): String {
            val clean = apiKey.trim()
            return when {
                clean.length > 10 -> "${clean.take(6)}...${clean.takeLast(4)}"
                clean.isNotEmpty() -> "***"
                else -> ""
            }
        }

        @Deprecated("Artificial cap removed; returns default cap for informational purposes")
        fun getModelDailyCap(modelId: String): Int {
            for ((knownModel, cap) in MODEL_DAILY_CAPS) {
                if (modelId.contains(knownModel)) {
                    return cap
                }
            }
            return DEFAULT_DAILY_CAP
        }

        fun getPacificDateString(zonedDateTime: ZonedDateTime = ZonedDateTime.now(PACIFIC_ZONE)): String {
            return try {
                zonedDateTime.toLocalDate().toString()
            } catch (e: Exception) {
                ""
            }
        }

        fun getSecondsUntilPacificMidnight(): Long {
            return try {
                val nowPacific = ZonedDateTime.now(PACIFIC_ZONE)
                val midnightPacific = nowPacific.toLocalDate().plusDays(1).atStartOfDay(PACIFIC_ZONE)
                val seconds = Duration.between(nowPacific, midnightPacific).seconds
                seconds.coerceAtLeast(60L)
            } catch (e: Exception) {
                // Fallback: approximately 8 hours (28800s)
                28800L
            }
        }

        fun parseRetryDelay(errorBody: String): Long? {
            if (errorBody.isBlank()) return null

            // 1. فحص كائن الخطأ المهيكل JSON من Google: error.details[].retryDelay
            try {
                val json = JSONObject(errorBody)
                val errorObj = json.optJSONObject("error")
                val details = errorObj?.optJSONArray("details")
                if (details != null) {
                    for (i in 0 until details.length()) {
                        val detail = details.optJSONObject(i) ?: continue
                        val type = detail.optString("@type", "")
                        if (type.contains("RetryInfo")) {
                            val rawDelay = detail.optString("retryDelay", "").trim()
                            if (rawDelay.endsWith("s")) {
                                val secStr = rawDelay.removeSuffix("s")
                                val seconds = secStr.toDoubleOrNull()?.toLong()
                                if (seconds != null && seconds > 0) {
                                    return seconds
                                }
                            }
                        }
                    }
                }
            } catch (_: Exception) {
                // ليس JSON صالحاً، ننتقل للـ Regex
            }

            // 2. فحص الأنماط النصية (Regex): e.g. "retry in 1h 20m 15s" or "45s"
            val hmsPattern = Pattern.compile("(\\d+)\\s*h(?:ours?)?\\s*(\\d+)\\s*m(?:in(?:utes?)?)?\\s*(\\d+)\\s*s(?:ec(?:onds?)?)?", Pattern.CASE_INSENSITIVE)
            val hmsMatcher = hmsPattern.matcher(errorBody)
            if (hmsMatcher.find()) {
                val h = hmsMatcher.group(1)?.toLongOrNull() ?: 0L
                val m = hmsMatcher.group(2)?.toLongOrNull() ?: 0L
                val s = hmsMatcher.group(3)?.toLongOrNull() ?: 0L
                return h * 3600L + m * 60L + s
            }

            val msPattern = Pattern.compile("(\\d+)\\s*m(?:in(?:utes?)?)?\\s*(\\d+)\\s*s(?:ec(?:onds?)?)?", Pattern.CASE_INSENSITIVE)
            val msMatcher = msPattern.matcher(errorBody)
            if (msMatcher.find()) {
                val m = msMatcher.group(1)?.toLongOrNull() ?: 0L
                val s = msMatcher.group(2)?.toLongOrNull() ?: 0L
                return m * 60L + s
            }

            val sPattern = Pattern.compile("retry\\s+(?:in|after)\\s+(\\d+)\\s*s(?:ec(?:onds?)?)?", Pattern.CASE_INSENSITIVE)
            val sMatcher = sPattern.matcher(errorBody)
            if (sMatcher.find()) {
                val s = sMatcher.group(1)?.toLongOrNull()
                if (s != null && s > 0) return s
            }

            return null
        }
    }

    private val storageFile: File = File(storageDir, DEFAULT_FILENAME)
    private val lock = Any()
    private var data: JSONObject = JSONObject().apply {
        put("version", 1)
        put("last_updated", System.currentTimeMillis() / 1000)
        put("keys", JSONObject())
    }

    init {
        load()
    }

    private fun safeLogI(tag: String, msg: String) {
        try {
            Log.i(tag, msg)
        } catch (_: Throwable) {
        }
    }

    private fun safeLogW(tag: String, msg: String) {
        try {
            Log.w(tag, msg)
        } catch (_: Throwable) {
        }
    }

    private fun safeLogE(tag: String, msg: String) {
        try {
            Log.e(tag, msg)
        } catch (_: Throwable) {
        }
    }

    fun load() {
        synchronized(lock) {
            if (!storageFile.exists() || storageFile.length() == 0L) {
                return
            }
            try {
                val content = storageFile.readText(StandardCharsets.UTF_8)
                data = JSONObject(content)
            } catch (e: Exception) {
                safeLogW(TAG, "Failed to load key_quotas.json: ${e.message}. Starting fresh.")
                data = JSONObject().apply {
                    put("version", 1)
                    put("last_updated", System.currentTimeMillis() / 1000)
                    put("keys", JSONObject())
                }
            }
        }
    }

    fun save() {
        synchronized(lock) {
            var tempFile: File? = null
            try {
                data.put("last_updated", System.currentTimeMillis() / 1000)
                storageDir.mkdirs()
                tempFile = File.createTempFile("key_quotas_", ".tmp", storageDir)
                FileOutputStream(tempFile).use { fos ->
                    fos.write(data.toString(2).toByteArray(StandardCharsets.UTF_8))
                    fos.flush()
                    try {
                        fos.fd.sync()
                    } catch (_: Exception) {}
                }

                try {
                    Files.move(
                        tempFile.toPath(),
                        storageFile.toPath(),
                        StandardCopyOption.ATOMIC_MOVE,
                        StandardCopyOption.REPLACE_EXISTING
                    )
                } catch (e: Exception) {
                    // Fallback on filesystems that do not support ATOMIC_MOVE
                    if (storageFile.exists()) {
                        storageFile.delete()
                    }
                    if (!tempFile.renameTo(storageFile)) {
                        tempFile.copyTo(storageFile, overwrite = true)
                        tempFile.delete()
                    }
                }
            } catch (e: Exception) {
                safeLogE(TAG, "Failed to atomic-save key_quotas.json: ${e.message}")
            } finally {
                tempFile?.let {
                    if (it.exists()) {
                        it.delete()
                    }
                }
            }
        }
    }

    private fun getModelRecord(apiKey: String, modelId: String, create: Boolean = true): JSONObject? {
        val cleanKey = apiKey.trim()
        if (cleanKey.isEmpty()) return null

        val keyId = computeKeyId(cleanKey)
        val keysObj = data.optJSONObject("keys") ?: JSONObject().also { data.put("keys", it) }

        var keyRecord = keysObj.optJSONObject(keyId)
        if (keyRecord == null) {
            if (!create) return null
            keyRecord = JSONObject().apply {
                put("key_preview", maskKey(cleanKey))
                put("created_at", System.currentTimeMillis() / 1000)
                put("models", JSONObject())
            }
            keysObj.put(keyId, keyRecord)
        }

        val modelsObj = keyRecord.optJSONObject("models") ?: JSONObject().also { keyRecord.put("models", it) }
        var modelRecord = modelsObj.optJSONObject(modelId)
        val todayPacific = getPacificDateString()

        if (modelRecord == null) {
            if (!create) return null
            modelRecord = JSONObject().apply {
                put("status", "AVAILABLE")
                put("requests_today", 0)
                put("last_request_date", todayPacific)
                put("resets_at", 0L)
                put("last_success_at", 0L)
                put("last_429_at", 0L)
                put("last_error", "")
            }
            modelsObj.put(modelId, modelRecord)
        } else {
            // Check if day changed in Pacific time
            val lastDate = modelRecord.optString("last_request_date", "")
            if (lastDate.isNotEmpty() && lastDate != todayPacific) {
                modelRecord.put("requests_today", 0)
                modelRecord.put("last_request_date", todayPacific)
            } else if (lastDate.isEmpty()) {
                modelRecord.put("last_request_date", todayPacific)
            }
        }

        return modelRecord
    }

    fun isKeyAvailable(apiKey: String, modelId: String): Boolean {
        val cleanKey = apiKey.trim()
        if (cleanKey.isEmpty()) return false

        synchronized(lock) {
            val rec = getModelRecord(cleanKey, modelId, create = false) ?: return true // New key is available

            val now = System.currentTimeMillis() / 1000
            val resetsAt = rec.optLong("resets_at", 0L)
            val status = rec.optString("status", "AVAILABLE")

            val todayPacific = getPacificDateString()
            val lastDate = rec.optString("last_request_date", "")
            var changed = false
            if (lastDate.isNotEmpty() && lastDate != todayPacific) {
                rec.put("requests_today", 0)
                rec.put("last_request_date", todayPacific)
                changed = true
            }

            if (status == "EXHAUSTED") {
                if (resetsAt > 0 && now >= resetsAt) {
                    safeLogI(TAG, "Quota renewed for key ${maskKey(cleanKey)} on $modelId (resets_at passed).")
                    rec.put("status", "AVAILABLE")
                    rec.put("requests_today", 0)
                    rec.put("resets_at", 0L)
                    save()
                    return true
                }
                if (changed) {
                    save()
                }
                return false
            }

            if (changed) {
                save()
            }

            // No artificial client-side cap blocking; paid accounts can use higher quotas.
            return true
        }
    }

    fun recordSuccess(apiKey: String, modelId: String) {
        val cleanKey = apiKey.trim()
        if (cleanKey.isEmpty()) return

        synchronized(lock) {
            val rec = getModelRecord(cleanKey, modelId, create = true) ?: return

            val todayPacific = getPacificDateString()
            val lastDate = rec.optString("last_request_date", "")
            if (lastDate.isNotEmpty() && lastDate != todayPacific) {
                rec.put("requests_today", 0)
            }
            rec.put("last_request_date", todayPacific)

            val reqToday = rec.optInt("requests_today", 0) + 1
            rec.put("requests_today", reqToday)
            rec.put("last_success_at", System.currentTimeMillis() / 1000)
            rec.put("status", "AVAILABLE")
            // No client-side artificial exhaustion cap. Server 429 governs quota.
            save()
        }
    }

    fun record429Exhaustion(
        apiKey: String,
        modelId: String,
        retryDelaySeconds: Long? = null,
        errorMessage: String = ""
    ): Long {
        val cleanKey = apiKey.trim()
        if (cleanKey.isEmpty()) return 0L

        synchronized(lock) {
            val rec = getModelRecord(cleanKey, modelId, create = true) ?: return 0L
            val now = System.currentTimeMillis() / 1000

            val isQuotaExhausted = errorMessage.contains("quota", ignoreCase = true) ||
                errorMessage.contains("RESOURCE_EXHAUSTED", ignoreCase = true) ||
                errorMessage.contains("limit", ignoreCase = true)

            val delay = when {
                retryDelaySeconds != null -> retryDelaySeconds
                isQuotaExhausted -> getSecondsUntilPacificMidnight()
                else -> DEFAULT_TRANSIENT_RETRY_DELAY
            }
            val resetsAt = now + delay

            rec.put("status", "EXHAUSTED")
            rec.put("resets_at", resetsAt)
            rec.put("last_429_at", now)
            rec.put("last_error", errorMessage.take(300))
            save()

            safeLogI(TAG, "Recorded 429 exhaustion for ${maskKey(cleanKey)} on $modelId. Resets in ${delay}s.")
            return resetsAt
        }
    }

    fun findFirstAvailableKeyIndex(apiKeys: List<String>, modelId: String, preferredIndex: Int = 0): Int {
        if (apiKeys.isEmpty()) return 0

        // 1. تحقق من المفتاح المفضل أولاً
        if (preferredIndex in apiKeys.indices) {
            if (isKeyAvailable(apiKeys[preferredIndex], modelId)) {
                return preferredIndex
            }
        }

        // 2. ابحث عن أول مفتاح متاح
        for (i in apiKeys.indices) {
            if (isKeyAvailable(apiKeys[i], modelId)) {
                return i
            }
        }

        // 3. إذا كانت كل المفاتيح مستنفدة، اختر المفتاح الذي سيتجدد في أقرب وقت
        var bestIdx = 0
        var earliestReset = Long.MAX_VALUE
        synchronized(lock) {
            for (i in apiKeys.indices) {
                val rec = getModelRecord(apiKeys[i], modelId, create = false)
                val resetsAt = rec?.optLong("resets_at", 0L) ?: 0L
                if (resetsAt in 1 until earliestReset) {
                    earliestReset = resetsAt
                    bestIdx = i
                }
            }
        }
        return bestIdx
    }

    fun getNextAvailableKey(apiKeys: List<String>, currentIndex: Int, modelId: String): Pair<Int, String?> {
        if (apiKeys.isEmpty()) return Pair(-1, null)
        if (currentIndex !in apiKeys.indices) {
            for (idx in apiKeys.indices) {
                if (isKeyAvailable(apiKeys[idx], modelId)) {
                    return Pair(idx, apiKeys[idx])
                }
            }
            return Pair(-1, null)
        }
        for (i in 1 until apiKeys.size) {
            val idx = (currentIndex + i) % apiKeys.size
            if (isKeyAvailable(apiKeys[idx], modelId)) {
                return Pair(idx, apiKeys[idx])
            }
        }
        return Pair(-1, null)
    }

    fun getRequestsToday(apiKey: String, modelId: String): Int {
        val cleanKey = apiKey.trim()
        if (cleanKey.isEmpty()) return 0
        synchronized(lock) {
            val rec = getModelRecord(cleanKey, modelId, create = false) ?: return 0
            val todayPacific = getPacificDateString()
            val lastDate = rec.optString("last_request_date", "")
            if (lastDate.isNotEmpty() && lastDate != todayPacific) {
                return 0
            }
            return rec.optInt("requests_today", 0)
        }
    }

    fun getLastRequestDate(apiKey: String, modelId: String): String {
        val cleanKey = apiKey.trim()
        if (cleanKey.isEmpty()) return ""
        synchronized(lock) {
            val rec = getModelRecord(cleanKey, modelId, create = false) ?: return ""
            return rec.optString("last_request_date", "")
        }
    }

    fun getEarliestRenewalTime(apiKeys: List<String>, modelId: String): Pair<Long, String> {
        val now = System.currentTimeMillis() / 1000
        var minRemaining = Long.MAX_VALUE

        synchronized(lock) {
            for (k in apiKeys) {
                val rec = getModelRecord(k, modelId, create = false)
                val resetsAt = rec?.optLong("resets_at", 0L) ?: 0L
                if (resetsAt > now) {
                    val rem = resetsAt - now
                    if (rem < minRemaining) {
                        minRemaining = rem
                    }
                }
            }
        }

        if (minRemaining == Long.MAX_VALUE) {
            return Pair(0L, "جاهز الآن")
        }

        val hours = minRemaining / 3600
        val mins = (minRemaining % 3600) / 60
        val secs = minRemaining % 60

        val formatted = when {
            hours > 0 -> String.format(Locale.US, "%d ساعة و %d دقيقة", hours, mins)
            mins > 0 -> String.format(Locale.US, "%d دقيقة و %d ثانية", mins, secs)
            else -> String.format(Locale.US, "%d ثانية", secs)
        }

        return Pair(minRemaining, formatted)
    }
}
