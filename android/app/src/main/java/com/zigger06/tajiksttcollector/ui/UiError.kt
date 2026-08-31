package com.zigger06.tajiksttcollector.ui

import android.util.Log
import com.zigger06.tajiksttcollector.BuildConfig
import com.zigger06.tajiksttcollector.network.ApiException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

/**
 * Keep transport details, hostnames and raw backend messages out of the volunteer UI.
 * Debug builds log the real exception so device-specific transport failures can be
 * diagnosed through adb without exposing technical details in the production UI.
 */
fun userFacingError(error: Throwable, fallback: String): String {
    if (BuildConfig.DEBUG) {
        Log.e(
            "TajikSTT-Net",
            "${error.javaClass.simpleName}: ${error.message.orEmpty()}",
            error,
        )
    }

    return when {
        error is ApiException && error.statusCode == 429 ->
            "Дархостҳо муваққатан маҳдуд шуданд. Каме интизор шавед ва дубора кӯшиш кунед."
        error is UnknownHostException || error is ConnectException || error is SocketTimeoutException ->
            "Сервер Дастнорас аст"
        error is IllegalStateException && fallback.startsWith("Пайвастшав") ->
            "Сервер Дастнорас аст"
        else -> fallback
    }
}
