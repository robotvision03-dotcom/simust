package com.simust.mysimust

import android.content.Context
import android.content.SharedPreferences

object Prefs {
    private const val FILE = "mysimust"
    const val KEY_PUBLIC_HOST = "public_host"
    const val KEY_TEXT_ZOOM = "text_zoom"
    const val KEY_KEEP_SCREEN = "keep_screen_on"
    const val KEY_ORIENTATION = "orientation"
    const val KEY_START_PATH = "start_path"

    const val PATH_LOGIN = "login"
    const val PATH_DASHBOARD = "dashboard"
    const val PATH_REGISTER = "register"

    const val ORIENTATION_AUTO = "auto"
    const val ORIENTATION_LANDSCAPE = "landscape"
    const val ORIENTATION_PORTRAIT = "portrait"

    const val DEFAULT_PUBLIC_HOST = "http://157.180.47.98"
    const val DEFAULT_TEXT_ZOOM = 110
    const val MIN_TEXT_ZOOM = 80
    const val MAX_TEXT_ZOOM = 180
    const val APP_VERSION = "1.1"

    private fun prefs(context: Context): SharedPreferences {
        return context.getSharedPreferences(FILE, Context.MODE_PRIVATE)
    }

    fun getPublicHost(context: Context): String {
        val raw = prefs(context).getString(KEY_PUBLIC_HOST, DEFAULT_PUBLIC_HOST) ?: DEFAULT_PUBLIC_HOST
        return normalize(raw)
    }

    fun setPublicHost(context: Context, url: String) {
        prefs(context).edit().putString(KEY_PUBLIC_HOST, normalize(url)).apply()
    }

    fun getStartPath(context: Context): String {
        return prefs(context).getString(KEY_START_PATH, PATH_LOGIN) ?: PATH_LOGIN
    }

    fun setStartPath(context: Context, path: String) {
        prefs(context).edit().putString(KEY_START_PATH, path).apply()
    }

    fun getTextZoom(context: Context): Int {
        val stored = prefs(context).getInt(KEY_TEXT_ZOOM, 0)
        if (stored in MIN_TEXT_ZOOM..MAX_TEXT_ZOOM) return stored
        return defaultTextZoom(context)
    }

    fun setTextZoom(context: Context, zoom: Int) {
        prefs(context).edit().putInt(KEY_TEXT_ZOOM, zoom.coerceIn(MIN_TEXT_ZOOM, MAX_TEXT_ZOOM)).apply()
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
        val path = when (getStartPath(context)) {
            PATH_DASHBOARD -> "/dashboard"
            PATH_REGISTER -> "/register"
            else -> "/login"
        }
        return withAppFlag(getPublicHost(context) + path)
    }

    fun urlForPath(context: Context, path: String): String {
        val suffix = when (path) {
            PATH_DASHBOARD -> "/dashboard"
            PATH_REGISTER -> "/register"
            else -> "/login"
        }
        return withAppFlag(getPublicHost(context) + suffix)
    }

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
            sw >= 800 -> 120
            sw >= 600 -> 115
            sw >= 360 -> 105
            else -> 100
        }
    }

    private fun withAppFlag(url: String): String {
        var out = url
        if (!out.contains("app=android")) {
            out += if (out.contains("?")) "&app=android" else "?app=android"
        }
        out = out
            .replace(Regex("""&v=[^&]*"""), "")
            .replace(Regex("""\?v=[^&]*&"""), "?")
            .replace(Regex("""\?v=[^&]*$"""), "")
        out += if (out.contains("?")) "&v=$APP_VERSION" else "?v=$APP_VERSION"
        return out
    }
}
