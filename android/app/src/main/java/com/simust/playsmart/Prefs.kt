package com.simust.playsmart

import android.content.Context
import android.content.SharedPreferences

object Prefs {
    private const val FILE = "simust"
    const val KEY_MODE = "app_mode"
    const val KEY_PUBLIC_HOST = "public_host"
    const val KEY_LAB_HOST = "lab_host"
    const val KEY_SERVER_URL = "server_url"

    const val MODE_OPERATOR = "operator"
    const val MODE_PLAYER = "player"
    const val MODE_LAB = "lab"

    const val DEFAULT_PUBLIC_HOST = "http://157.180.47.98"
    const val DEFAULT_LAB_HOST = "http://10.0.2.2:8000"

    private fun prefs(context: Context): SharedPreferences {
        return context.getSharedPreferences(FILE, Context.MODE_PRIVATE)
    }

    fun getMode(context: Context): String {
        val stored = prefs(context).getString(KEY_MODE, "") ?: ""
        if (stored.isNotEmpty()) return stored
        val legacy = prefs(context).getString(KEY_SERVER_URL, "") ?: ""
        return if (legacy.contains("157.180.47.98") || legacy.contains("my.simust") || legacy.contains("/login")) {
            MODE_PLAYER
        } else if (legacy.isNotEmpty()) {
            MODE_LAB
        } else {
            MODE_OPERATOR
        }
    }

    fun setMode(context: Context, mode: String) {
        prefs(context).edit().putString(KEY_MODE, mode).apply()
    }

    fun getPublicHost(context: Context): String {
        val raw = prefs(context).getString(KEY_PUBLIC_HOST, DEFAULT_PUBLIC_HOST) ?: DEFAULT_PUBLIC_HOST
        return normalize(raw)
    }

    fun setPublicHost(context: Context, url: String) {
        prefs(context).edit().putString(KEY_PUBLIC_HOST, normalize(url)).apply()
    }

    fun getLabHost(context: Context): String {
        val raw = prefs(context).getString(KEY_LAB_HOST, DEFAULT_LAB_HOST) ?: DEFAULT_LAB_HOST
        return normalize(raw)
    }

    fun setLabHost(context: Context, url: String) {
        prefs(context).edit().putString(KEY_LAB_HOST, normalize(url)).apply()
    }

    fun getLaunchUrl(context: Context): String {
        return when (getMode(context)) {
            MODE_PLAYER -> withAppFlag(getPublicHost(context) + "/login")
            MODE_LAB -> withAppFlag(getLabHost(context))
            else -> withAppFlag(getPublicHost(context) + "/operator")
        }
    }

    fun getServerUrl(context: Context): String = getLaunchUrl(context)

    fun normalize(url: String): String {
        var value = url.trim()
        if (value.isEmpty()) return DEFAULT_PUBLIC_HOST
        if (!value.startsWith("http://") && !value.startsWith("https://")) {
            value = "http://$value"
        }
        return value.trimEnd('/')
    }

    private fun withAppFlag(url: String): String {
        return if (url.contains("app=android")) url else {
            url + if (url.contains("?")) "&app=android" else "?app=android"
        }
    }
}
