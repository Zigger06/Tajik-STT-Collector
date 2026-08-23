package com.zigger06.tajiksttcollector.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

object ServerConfig {
    private const val CONFIG_URL =
        "https://zigger06.github.io/Tajik-STT-Collector/app-config.json"

    private val client = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(12, TimeUnit.SECONDS)
        .build()

    suspend fun resolve(cachedUrl: String): String = withContext(Dispatchers.IO) {
        val remoteUrl = runCatching {
            val request = Request.Builder()
                .url("$CONFIG_URL?time=${System.currentTimeMillis()}")
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) throw IOException("Server config HTTP ${response.code}")
                JSONObject(response.body?.string().orEmpty())
                    .optString("server_url")
                    .trim()
                    .trimEnd('/')
            }
        }.getOrNull()

        when {
            isValid(remoteUrl.orEmpty()) -> remoteUrl.orEmpty()
            isValid(cachedUrl) -> cachedUrl.trim().trimEnd('/')
            else -> throw IOException("Танзими сервер ҳоло дастрас нест. Баъдтар такрор кунед.")
        }
    }

    private fun isValid(url: String): Boolean = url.startsWith("https://")
}
