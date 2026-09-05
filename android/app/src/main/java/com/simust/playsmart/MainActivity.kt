package com.simust.playsmart

import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.Bitmap
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView
    private lateinit var errorPanel: LinearLayout
    private lateinit var progressBar: ProgressBar
    private var lastUrl: String = ""

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val toolbar = findViewById<Toolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)

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
        settings.builtInZoomControls = true
        settings.displayZoomControls = false
        settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
        settings.cacheMode = WebSettings.LOAD_DEFAULT
        settings.mediaPlaybackRequiresUserGesture = false
        settings.allowContentAccess = true
        settings.allowFileAccess = false
        settings.userAgentString = settings.userAgentString + " SIMUSTAndroid/2.0"

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
                    findViewById<TextView>(R.id.errorText).text =
                        getString(R.string.load_error) + "\n" + Prefs.getLaunchUrl(this@MainActivity)
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
    }

    override fun onResume() {
        super.onResume()
        webView.onResume()
        val url = Prefs.getLaunchUrl(this)
        if (url != lastUrl) {
            loadGui()
        }
        titleForMode()
    }

    override fun onPause() {
        webView.onPause()
        super.onPause()
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.main_menu, menu)
        return true
    }

    override fun onPrepareOptionsMenu(menu: Menu): Boolean {
        val mode = Prefs.getMode(this)
        menu.findItem(R.id.action_operator)?.isChecked = mode == Prefs.MODE_OPERATOR
        menu.findItem(R.id.action_player)?.isChecked = mode == Prefs.MODE_PLAYER
        return super.onPrepareOptionsMenu(menu)
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_reload -> {
                loadGui()
                true
            }
            R.id.action_operator -> {
                Prefs.setMode(this, Prefs.MODE_OPERATOR)
                loadGui()
                true
            }
            R.id.action_player -> {
                Prefs.setMode(this, Prefs.MODE_PLAYER)
                loadGui()
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

    private fun titleForMode() {
        supportActionBar?.title = when (Prefs.getMode(this)) {
            Prefs.MODE_PLAYER -> getString(R.string.title_player)
            Prefs.MODE_LAB -> getString(R.string.title_lab)
            else -> getString(R.string.title_operator)
        }
    }

    private fun loadGui() {
        errorPanel.visibility = View.GONE
        val url = Prefs.getLaunchUrl(this)
        lastUrl = url
        titleForMode()
        invalidateOptionsMenu()
        webView.loadUrl(url)
    }
}
