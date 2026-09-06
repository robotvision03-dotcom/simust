package com.simust.playsmart

import android.content.Context
import android.content.SharedPreferences
object Prefs {
    private const val FILE = "simust"
    const val KEY_MODE = "app_mode"
    const val KEY_PUBLIC_HOST = "public_host"
    const val KEY_LAB_HOST = "lab_host"
    const val KEY_SERVER_URL = "server_url"
    const val KEY_TEXT_ZOOM = "text_zoom"
    const val KEY_KEEP_SCREEN = "keep_screen_on"
    const val KEY_ORIENTATION = "orientation"

    const val MODE_OPERATOR = "operator"
    const val MODE_PLAYER = "player"
    const val MODE_LAB = "lab"

    const val ORIENTATION_AUTO = "auto"
    const val ORIENTATION_LANDSCAPE = "landscape"
    const val ORIENTATION_PORTRAIT = "portrait"

    const val DEFAULT_PUBLIC_HOST = "http://157.180.47.98"
    const val DEFAULT_LAB_HOST = "http://10.0.2.2:8000"
    const val DEFAULT_TEXT_ZOOM = 110
    const val MIN_TEXT_ZOOM = 80
    const val MAX_TEXT_ZOOM = 180

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

    fun getTextZoom(context: Context): Int {
        val stored = prefs(context).getInt(KEY_TEXT_ZOOM, 0)
        if (stored in MIN_TEXT_ZOOM..MAX_TEXT_ZOOM) return stored
        return defaultTextZoom(context)
    }

    fun setTextZoom(context: Context, zoom: Int) {
        val clamped = zoom.coerceIn(MIN_TEXT_ZOOM, MAX_TEXT_ZOOM)
        prefs(context).edit().putInt(KEY_TEXT_ZOOM, clamped).apply()
    }

    fun getKeepScreenOn(context: Context): Boolean {
        return prefs(context).getBoolean(KEY_KEEP_SCREEN, true)
    }

    fun setKeepScreenOn(context: Context, on: Boolean) {
        prefs(context).edit().putBoolean(KEY_KEEP_SCREEN, on).apply()
    }

    fun getOrientation(context: Context): String {
        return prefs(context).getString(KEY_ORIENTATION, ORIENTATION_AUTO) ?: ORIENTATION_AUTO
    }

    fun setOrientation(context: Context, value: String) {
        prefs(context).edit().putString(KEY_ORIENTATION, value).apply()
    }

    fun resetDisplayDefaults(context: Context) {
        prefs(context).edit()
            .putInt(KEY_TEXT_ZOOM, defaultTextZoom(context))
            .putBoolean(KEY_KEEP_SCREEN, true)
            .putString(KEY_ORIENTATION, ORIENTATION_AUTO)
            .apply()
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

    private fun defaultTextZoom(context: Context): Int {
        val sw = context.resources.configuration.smallestScreenWidthDp
        return when {
            sw >= 800 -> 115
            sw >= 600 -> 110
            sw >= 360 -> 105
            else -> 100
        }
    }

    private fun withAppFlag(url: String): String {
        return if (url.contains("app=android")) url else {
            url + if (url.contains("?")) "&app=android" else "?app=android"
        }
    }
}
