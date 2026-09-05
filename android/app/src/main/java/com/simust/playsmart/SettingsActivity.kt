package com.simust.playsmart

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.RadioGroup
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
        val publicHost = findViewById<EditText>(R.id.publicHost)
        val labHost = findViewById<EditText>(R.id.labHost)
        publicHost.setText(Prefs.getPublicHost(this))
        labHost.setText(Prefs.getLabHost(this))
        modes.check(
            when (Prefs.getMode(this)) {
                Prefs.MODE_PLAYER -> R.id.modePlayer
                Prefs.MODE_LAB -> R.id.modeLab
                else -> R.id.modeOperator
            },
        )

        findViewById<Button>(R.id.saveButton).setOnClickListener {
            Prefs.setPublicHost(this, publicHost.text.toString())
            Prefs.setLabHost(this, labHost.text.toString())
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
