package com.simust.mysimust

import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.res.Configuration
import android.graphics.Bitmap
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.JsPromptResult
import android.webkit.JsResult
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView
    private lateinit var errorPanel: LinearLayout
    private lateinit var progressBar: ProgressBar
    private var lastUrl: String = ""
    private val statusHandler = Handler(Looper.getMainLooper())
    private val statusTick = object : Runnable {
        override fun run() {
            refreshSubtitle()
            statusHandler.postDelayed(this, 5000)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        applyDisplayPrefs()

        val toolbar = findViewById<Toolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayShowTitleEnabled(true)

        webView = findViewById(R.id.webView)
        errorPanel = findViewById(R.id.errorPanel)
        progressBar = findViewById(R.id.progressBar)
        findViewById<Button>(R.id.retryButton).setOnClickListener { loadGui() }
        findViewById<Button>(R.id.openSettingsButton).setOnClickListener { openSettings() }

        val cookies = CookieManager.getInstance()
        cookies.setAcceptCookie(true)
        cookies.setAcceptThirdPartyCookies(webView, true)

        val settings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.databaseEnabled = true
        settings.loadWithOverviewMode = true
        settings.useWideViewPort = true
        settings.setSupportZoom(true)
        settings.builtInZoomControls = true
        settings.displayZoomControls = false
        settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
        settings.cacheMode = WebSettings.LOAD_NO_CACHE
        settings.mediaPlaybackRequiresUserGesture = false
        settings.allowContentAccess = true
        settings.allowFileAccess = false
        settings.layoutAlgorithm = WebSettings.LayoutAlgorithm.TEXT_AUTOSIZING
        settings.userAgentString = settings.userAgentString + " MySIMUSTAndroid/" + Prefs.APP_VERSION
        applyTextZoom()

        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                progressBar.visibility = View.VISIBLE
                errorPanel.visibility = View.GONE
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                progressBar.visibility = View.GONE
                CookieManager.getInstance().flush()
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?,
            ) {
                if (request?.isForMainFrame == true) {
                    progressBar.visibility = View.GONE
                    errorPanel.visibility = View.VISIBLE
                    val extra = if (NetworkStatus.isOnline(this@MainActivity)) {
                        Prefs.getLaunchUrl(this@MainActivity)
                    } else {
                        getString(R.string.load_error_offline)
                    }
                    findViewById<TextView>(R.id.errorText).text =
                        getString(R.string.load_error) + "\n" + extra
                }
            }

            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                return false
            }
        }
        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                progressBar.visibility = if (newProgress in 1..99) View.VISIBLE else View.GONE
            }

            override fun onJsAlert(
                view: WebView?,
                url: String?,
                message: String?,
                result: JsResult?,
            ): Boolean {
                AlertDialog.Builder(this@MainActivity)
                    .setMessage(message ?: "")
                    .setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm() }
                    .setOnCancelListener { result?.cancel() }
                    .show()
                return true
            }

            override fun onJsConfirm(
                view: WebView?,
                url: String?,
                message: String?,
                result: JsResult?,
            ): Boolean {
                AlertDialog.Builder(this@MainActivity)
                    .setMessage(message ?: "")
                    .setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm() }
                    .setNegativeButton(android.R.string.cancel) { _, _ -> result?.cancel() }
                    .setOnCancelListener { result?.cancel() }
                    .show()
                return true
            }

            override fun onJsPrompt(
                view: WebView?,
                url: String?,
                message: String?,
                defaultValue: String?,
                result: JsPromptResult?,
            ): Boolean {
                val input = EditText(this@MainActivity).apply {
                    setText(defaultValue ?: "")
                    setSelection(text.length)
                    inputType = android.text.InputType.TYPE_CLASS_TEXT or
                        android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD
                }
                AlertDialog.Builder(this@MainActivity)
                    .setMessage(message ?: "")
                    .setView(input)
                    .setPositiveButton(android.R.string.ok) { _, _ ->
                        result?.confirm(input.text?.toString() ?: "")
                    }
                    .setNegativeButton(android.R.string.cancel) { _, _ -> result?.cancel() }
                    .setOnCancelListener { result?.cancel() }
                    .show()
                return true
            }
        }

        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    if (webView.canGoBack()) {
                        webView.goBack()
                    } else {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                    }
                }
            },
        )

        loadGui()
        statusHandler.post(statusTick)
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        applyDisplayPrefs()
        applyTextZoom()
    }

    override fun onResume() {
        super.onResume()
        webView.onResume()
        applyDisplayPrefs()
        applyTextZoom()
        val url = Prefs.getLaunchUrl(this)
        if (url != lastUrl) {
            loadGui()
        }
        supportActionBar?.title = getString(R.string.title_main)
        statusHandler.removeCallbacks(statusTick)
        statusHandler.post(statusTick)
    }

    override fun onPause() {
        statusHandler.removeCallbacks(statusTick)
        webView.onPause()
        super.onPause()
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.main_menu, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_reload -> {
                loadGui()
                true
            }
            R.id.action_login -> {
                Prefs.setStartPath(this, Prefs.PATH_LOGIN)
                loadGui(Prefs.urlForPath(this, Prefs.PATH_LOGIN))
                true
            }
            R.id.action_dashboard -> {
                Prefs.setStartPath(this, Prefs.PATH_DASHBOARD)
                loadGui(Prefs.urlForPath(this, Prefs.PATH_DASHBOARD))
                true
            }
            R.id.action_register -> {
                Prefs.setStartPath(this, Prefs.PATH_REGISTER)
                loadGui(Prefs.urlForPath(this, Prefs.PATH_REGISTER))
                true
            }
            R.id.action_settings -> {
                openSettings()
                true
            }
            else -> super.onOptionsItemSelected(item)
        }
    }

    private fun openSettings() {
        startActivity(Intent(this, SettingsActivity::class.java))
    }

    private fun applyDisplayPrefs() {
        if (Prefs.getKeepScreenOn(this)) {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        } else {
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
        requestedOrientation = when (Prefs.getOrientation(this)) {
            Prefs.ORIENTATION_LANDSCAPE -> ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
            Prefs.ORIENTATION_PORTRAIT -> ActivityInfo.SCREEN_ORIENTATION_SENSOR_PORTRAIT
            else -> ActivityInfo.SCREEN_ORIENTATION_FULL_USER
        }
    }

    private fun applyTextZoom() {
        if (!::webView.isInitialized) return
        webView.settings.textZoom = Prefs.getTextZoom(this)
    }

    private fun refreshSubtitle() {
        if (!NetworkStatus.isOnline(this)) {
            runOnUiThread { supportActionBar?.subtitle = getString(R.string.subtitle_no_network) }
            return
        }
        val transport = NetworkStatus.transportLabel(this)
        Thread {
            try {
                val host = Prefs.getPublicHost(this)
                val ok = pingHost(host + "/login") || pingHost(host + "/")
                runOnUiThread {
                    supportActionBar?.subtitle = if (ok) {
                        getString(R.string.subtitle_online, transport)
                    } else {
                        getString(R.string.subtitle_host_unreachable, transport)
                    }
                }
            } catch (_: Exception) {
                runOnUiThread {
                    supportActionBar?.subtitle =
                        getString(R.string.subtitle_host_unreachable, transport)
                }
            }
        }.start()
    }

    private fun pingHost(url: String): Boolean {
        return try {
            val conn = java.net.URL(url).openConnection() as java.net.HttpURLConnection
            conn.connectTimeout = 4000
            conn.readTimeout = 4000
            conn.requestMethod = "GET"
            conn.setRequestProperty("Cache-Control", "no-cache")
            val code = conn.responseCode
            conn.disconnect()
            code in 200..399
        } catch (_: Exception) {
            false
        }
    }

    private fun loadGui(forcedUrl: String? = null) {
        errorPanel.visibility = View.GONE
        val url = forcedUrl ?: Prefs.getLaunchUrl(this)
        lastUrl = url
        supportActionBar?.title = getString(R.string.title_main)
        applyTextZoom()
        webView.clearCache(false)
        webView.loadUrl(url)
    }
}
