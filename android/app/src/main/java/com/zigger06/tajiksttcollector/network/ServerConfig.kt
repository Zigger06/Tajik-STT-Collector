package com.zigger06.tajiksttcollector.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

object ServerConfig {
    private const val CONFIG_URL =
        "https://zigger06.github.io/Tajik-STT-Collector/app-config.json"

    // Keep a last-known-good Funnel address inside the APK. The tiny GitHub Pages
    // config can still replace it when it answers quickly, but first setup must not
    // sit for 8-12 seconds just because GitHub Pages/DNS is slow or temporarily down.
    private const val BUILT_IN_SERVER_URL =
        "https://mlscientist06.tailbc3525.ts.net"

    private val client = OkHttpClient.Builder()
        .connectTimeout(500, TimeUnit.MILLISECONDS)
        .readTimeout(700, TimeUnit.MILLISECONDS)
        .callTimeout(900, TimeUnit.MILLISECONDS)
        .build()

    suspend fun resolve(cachedUrl: String): String = withContext(Dispatchers.IO) {
        val cached = cachedUrl.trim().trimEnd('/')
        if (isValid(cached)) return@withContext cached

        // Fresh installs try the remotely updateable URL, but only as a sub-second
        // best-effort lookup. If it is unavailable, use the embedded Funnel address
        // immediately instead of treating config-host failure as server failure.
        val remoteUrl = runCatching {
            val request = Request.Builder()
                .url("$CONFIG_URL?time=${System.currentTimeMillis()}")
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@use ""
                JSONObject(response.body?.string().orEmpty())
                    .optString("server_url")
                    .trim()
                    .trimEnd('/')
            }
        }.getOrNull().orEmpty()

        if (isValid(remoteUrl)) remoteUrl else BUILT_IN_SERVER_URL
    }

    private fun isValid(url: String): Boolean = url.startsWith("https://")
}
