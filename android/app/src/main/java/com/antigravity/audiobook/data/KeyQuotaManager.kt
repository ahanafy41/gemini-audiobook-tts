package com.antigravity.audiobook.data

import android.util.Log
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.nio.charset.StandardCharsets
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

        val MODEL_DAILY_CAPS = mapOf(
            "gemini-3.8-flash-tts" to 100,
            "gemini-3.8-flash-lite-tts" to 100,
            "gemini-3.1-flash-tts-preview" to 10,
            "gemini-2.5-flash-preview-tts" to 10,
            "gemini-2.5-pro-preview-tts" to 10
        )
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

        fun getModelDailyCap(modelId: String): Int {
            for ((knownModel, cap) in MODEL_DAILY_CAPS) {
                if (modelId.contains(knownModel)) {
                    return cap
                }
            }
            return DEFAULT_DAILY_CAP
        }

        fun getSecondsUntilPacificMidnight(): Long {
            return try {
                val pacificZone = ZoneId.of("America/Los_Angeles")
                val nowPacific = ZonedDateTime.now(pacificZone)
                val midnightPacific = nowPacific.toLocalDate().plusDays(1).atStartOfDay(pacificZone)
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

    fun load() {
        synchronized(lock) {
            if (!storageFile.exists() || storageFile.length() == 0L) {
                return
            }
            try {
                val content = storageFile.readText(StandardCharsets.UTF_8)
                data = JSONObject(content)
            } catch (e: Exception) {
                Log.w(TAG, "Failed to load key_quotas.json: ${e.message}. Starting fresh.")
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
            try {
                data.put("last_updated", System.currentTimeMillis() / 1000)
                storageDir.mkdirs()
                val tempFile = File(storageDir, "$DEFAULT_FILENAME.tmp")
                FileOutputStream(tempFile).use { fos ->
                    fos.write(data.toString(2).toByteArray(StandardCharsets.UTF_8))
                    fos.flush()
                }
                if (!tempFile.renameTo(storageFile)) {
                    // Fallback on some Android filesystems
                    storageFile.delete()
                    tempFile.renameTo(storageFile)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to atomic-save key_quotas.json: ${e.message}")
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
        if (modelRecord == null) {
            if (!create) return null
            modelRecord = JSONObject().apply {
                put("status", "AVAILABLE")
                put("requests_today", 0)
                put("daily_cap", getModelDailyCap(modelId))
                put("resets_at", 0L)
                put("last_success_at", 0L)
                put("last_429_at", 0L)
                put("last_error", "")
            }
            modelsObj.put(modelId, modelRecord)
        }

        return modelRecord
    }

    fun isKeyAvailable(apiKey: String, modelId: String): Boolean {
        val cleanKey = apiKey.trim()
        if (cleanKey.isEmpty()) return false

        synchronized(lock) {
            val rec = getModelRecord(cleanKey, modelId, create = false) ?: return true // مفتاح جديد لم يُستخدم

            val now = System.currentTimeMillis() / 1000
            val resetsAt = rec.optLong("resets_at", 0L)
            val status = rec.optString("status", "AVAILABLE")

            if (status == "EXHAUSTED") {
                if (resetsAt > 0 && now >= resetsAt) {
                    Log.i(TAG, "Quota renewed for key ${maskKey(cleanKey)} on $modelId (resets_at passed).")
                    rec.put("status", "AVAILABLE")
                    rec.put("requests_today", 0)
                    rec.put("resets_at", 0L)
                    save()
                    return true
                }
                return false
            }

            val dailyCap = rec.optInt("daily_cap", getModelDailyCap(modelId))
            val requestsToday = rec.optInt("requests_today", 0)
            if (requestsToday >= dailyCap) {
                return false
            }

            return true
        }
    }

    fun recordSuccess(apiKey: String, modelId: String) {
        val cleanKey = apiKey.trim()
        if (cleanKey.isEmpty()) return

        synchronized(lock) {
            val rec = getModelRecord(cleanKey, modelId, create = true) ?: return
            val reqToday = rec.optInt("requests_today", 0) + 1
            rec.put("requests_today", reqToday)
            rec.put("last_success_at", System.currentTimeMillis() / 1000)
            rec.put("status", "AVAILABLE")

            val dailyCap = rec.optInt("daily_cap", getModelDailyCap(modelId))
            if (reqToday >= dailyCap) {
                val delaySec = getSecondsUntilPacificMidnight()
                val resetsAt = (System.currentTimeMillis() / 1000) + delaySec
                rec.put("status", "EXHAUSTED")
                rec.put("resets_at", resetsAt)
                Log.i(TAG, "Key ${maskKey(cleanKey)} reached daily cap ($dailyCap reqs) on $modelId. Reset in ${delaySec}s.")
            }
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
            val delay = retryDelaySeconds ?: getSecondsUntilPacificMidnight()
            val resetsAt = now + delay

            rec.put("status", "EXHAUSTED")
            rec.put("resets_at", resetsAt)
            rec.put("last_429_at", now)
            rec.put("last_error", errorMessage.take(300))
            save()

            Log.i(TAG, "Recorded 429 exhaustion for ${maskKey(cleanKey)} on $modelId. Resets in ${delay}s.")
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
        for (idx in (currentIndex + 1) until apiKeys.size) {
            if (isKeyAvailable(apiKeys[idx], modelId)) {
                return Pair(idx, apiKeys[idx])
            }
        }
        return Pair(-1, null)
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
