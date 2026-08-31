package com.simust.playsmart

import android.content.Context
import android.content.SharedPreferences

object Prefs {
    private const val FILE = "simust"
    const val KEY_SERVER_URL = "server_url"
    const val DEFAULT_URL = "http://10.0.2.2:8000"

    private fun prefs(context: Context): SharedPreferences {
        return context.getSharedPreferences(FILE, Context.MODE_PRIVATE)
    }

    fun getServerUrl(context: Context): String {
        val raw = prefs(context).getString(KEY_SERVER_URL, DEFAULT_URL) ?: DEFAULT_URL
        return normalize(raw)
    }

    fun setServerUrl(context: Context, url: String) {
        prefs(context).edit().putString(KEY_SERVER_URL, normalize(url)).apply()
    }

    fun normalize(url: String): String {
        var value = url.trim()
        if (value.isEmpty()) return DEFAULT_URL
        if (!value.startsWith("http://") && !value.startsWith("https://")) {
            value = "http://$value"
        }
        return value.trimEnd('/')
    }
}
