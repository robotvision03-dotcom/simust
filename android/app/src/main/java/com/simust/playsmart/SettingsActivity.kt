package com.simust.playsmart

import android.os.Bundle
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.RadioGroup
import android.widget.SeekBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar

class SettingsActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        val toolbar = findViewById<Toolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        toolbar.setNavigationOnClickListener { finish() }

        val modes = findViewById<RadioGroup>(R.id.modeGroup)
        val orientations = findViewById<RadioGroup>(R.id.orientationGroup)
        val publicHost = findViewById<EditText>(R.id.publicHost)
        val labHost = findViewById<EditText>(R.id.labHost)
        val zoomBar = findViewById<SeekBar>(R.id.textZoom)
        val zoomLabel = findViewById<TextView>(R.id.textZoomValue)
        val keepScreen = findViewById<CheckBox>(R.id.keepScreenOn)

        publicHost.setText(Prefs.getPublicHost(this))
        labHost.setText(Prefs.getLabHost(this))
        keepScreen.isChecked = Prefs.getKeepScreenOn(this)
        modes.check(
            when (Prefs.getMode(this)) {
                Prefs.MODE_PLAYER -> R.id.modePlayer
                Prefs.MODE_LAB -> R.id.modeLab
                else -> R.id.modeOperator
            },
        )
        orientations.check(
            when (Prefs.getOrientation(this)) {
                Prefs.ORIENTATION_LANDSCAPE -> R.id.orientationLandscape
                Prefs.ORIENTATION_PORTRAIT -> R.id.orientationPortrait
                else -> R.id.orientationAuto
            },
        )

        zoomBar.max = (Prefs.MAX_TEXT_ZOOM - Prefs.MIN_TEXT_ZOOM) / 5
        fun showZoom(zoom: Int) {
            zoomBar.progress = (zoom - Prefs.MIN_TEXT_ZOOM) / 5
            zoomLabel.text = getString(R.string.text_zoom_value, zoom)
        }
        showZoom(Prefs.getTextZoom(this))
        zoomBar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: SeekBar?, progress: Int, fromUser: Boolean) {
                val zoom = Prefs.MIN_TEXT_ZOOM + progress * 5
                zoomLabel.text = getString(R.string.text_zoom_value, zoom)
            }
            override fun onStartTrackingTouch(seekBar: SeekBar?) {}
            override fun onStopTrackingTouch(seekBar: SeekBar?) {}
        })

        findViewById<Button>(R.id.zoomCompact).setOnClickListener { showZoom(90) }
        findViewById<Button>(R.id.zoomStandard).setOnClickListener { showZoom(110) }
        findViewById<Button>(R.id.zoomLarge).setOnClickListener { showZoom(140) }

        findViewById<Button>(R.id.resetDisplayButton).setOnClickListener {
            Prefs.resetDisplayDefaults(this)
            keepScreen.isChecked = true
            orientations.check(R.id.orientationAuto)
            showZoom(Prefs.getTextZoom(this))
        }

        findViewById<Button>(R.id.saveButton).setOnClickListener {
            Prefs.setPublicHost(this, publicHost.text.toString())
            Prefs.setLabHost(this, labHost.text.toString())
            Prefs.setTextZoom(this, Prefs.MIN_TEXT_ZOOM + zoomBar.progress * 5)
            Prefs.setKeepScreenOn(this, keepScreen.isChecked)
            Prefs.setOrientation(
                this,
                when (orientations.checkedRadioButtonId) {
                    R.id.orientationLandscape -> Prefs.ORIENTATION_LANDSCAPE
                    R.id.orientationPortrait -> Prefs.ORIENTATION_PORTRAIT
                    else -> Prefs.ORIENTATION_AUTO
                },
            )
            Prefs.setMode(
                this,
                when (modes.checkedRadioButtonId) {
                    R.id.modePlayer -> Prefs.MODE_PLAYER
                    R.id.modeLab -> Prefs.MODE_LAB
                    else -> Prefs.MODE_OPERATOR
                },
            )
            finish()
        }
    }
}
