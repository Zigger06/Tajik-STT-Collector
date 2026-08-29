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

        // Deployment configuration must win over an old value kept in
        // SharedPreferences. Earlier builds returned any syntactically valid cached
        // https:// URL immediately, so a phone that had once used an older Funnel
        // address never even attempted the current server and misleadingly showed
        // "Сервер Дастнорас аст" while Chrome could reach the live Funnel normally.
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

        when {
            isValid(remoteUrl) -> remoteUrl
            isValid(BUILT_IN_SERVER_URL) -> BUILT_IN_SERVER_URL
            isValid(cached) -> cached
            else -> BUILT_IN_SERVER_URL
        }
    }

    private fun isValid(url: String): Boolean = url.startsWith("https://")
}
