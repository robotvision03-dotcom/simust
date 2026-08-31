package com.simust.playsmart

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
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

        val input = findViewById<EditText>(R.id.serverUrl)
        input.setText(Prefs.getServerUrl(this))

        findViewById<Button>(R.id.saveButton).setOnClickListener {
            Prefs.setServerUrl(this, input.text.toString())
            finish()
        }
    }
}
