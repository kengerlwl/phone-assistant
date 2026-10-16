package com.mobilerun.portal.ui

import android.Manifest
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.View
import android.view.WindowManager
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.mobilerun.portal.BuildConfig
import com.mobilerun.portal.config.ConfigManager
import com.mobilerun.portal.service.MobilerunAccessibilityService
import com.mobilerun.portal.service.ReverseConnectionService
import com.mobilerun.portal.state.ConnectionState
import com.mobilerun.portal.state.ConnectionStateManager
import org.json.JSONObject
import java.net.URI
import javax.net.ssl.HttpsURLConnection

/** Personal, attended connection UI. No cloud login, billing, or silent permissions. */
class MainActivity : AppCompatActivity() {
    companion object {
        @Volatile var privateScreenVisible = false
            private set
    }
    private lateinit var config: ConfigManager
    private lateinit var status: TextView
    private lateinit var permissionStatus: TextView
    private lateinit var server: EditText
    private lateinit var code: EditText
    private lateinit var connect: Button
    private lateinit var stop: Button
    private var pairing = false
    private val ink = Color.rgb(28, 39, 52)
    private val accent = Color.rgb(27, 105, 89)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        config = ConfigManager.getInstance(this)
        config.screenShareAutoAcceptEnabled = false
        config.installAutoAcceptEnabled = false
        config.setSocketServerEnabledWithNotification(false)
        config.setWebSocketEnabledWithNotification(false)
        config.setOverlayVisibleWithNotification(false)
        val scroll = ScrollView(this).apply { setBackgroundColor(Color.rgb(245, 247, 249)) }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(30), dp(24), dp(32))
        }
        scroll.addView(root)
        setContentView(scroll)
        root.addView(label("Phone Assistant", 28, true))
        root.addView(label("手机助手 · 由你开启，由你随时停止", 16))
        status = label("未连接", 22, true)
        root.addView(status, spaced())
        root.addView(label("通过移动数据或 Wi-Fi 连接你的服务器。\n无需 Root、USB 调试或电脑激活。", 15))
        permissionStatus = label("检查无障碍权限…", 15)
        root.addView(permissionStatus, spaced())
        root.addView(button("开启 / 检查无障碍权限") {
            val intent = Intent("android.settings.ACCESSIBILITY_DETAILS_SETTINGS").apply {
                putExtra(Intent.EXTRA_COMPONENT_NAME, ComponentName(this@MainActivity, MobilerunAccessibilityService::class.java))
            }
            try { startActivity(intent) } catch (_: Exception) { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        })
        root.addView(button("允许连接状态通知") {
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 20)
            } else {
                startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
            }
        })
        root.addView(label("服务器", 14, true), spaced())
        server = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine(true)
            setText(config.reverseConnectionUrlOrDefault)
            hint = "wss://your-server.example:8443/device"
            textSize = 14f
            contentDescription = "服务器地址"
        }
        root.addView(server)
        root.addView(label("首次配对码（有效期内使用一次）", 14, true), spaced())
        code = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
            setSingleLine(true)
            hint = if (config.reverseConnectionToken.isBlank()) "输入 8 位配对码" else "已保存凭据，重启后直接连接"
            contentDescription = "配对码"
        }
        root.addView(code)
        root.addView(button("粘贴配对链接") {
            val clipboard = getSystemService(android.content.ClipboardManager::class.java)
            val value = clipboard.primaryClip?.getItemAt(0)?.coerceToText(this)?.toString().orEmpty()
            importPairingLink(value)
        })
        connect = button("连接我的助手", primary = true) { connectRequested() }
        root.addView(connect, spaced())
        stop = button("立即断开", primary = false) {
            config.reverseConnectionEnabled = false
            ReverseConnectionService.getInstance()?.stopByUser()
            stopService(Intent(this, ReverseConnectionService::class.java))
            ConnectionStateManager.setState(ConnectionState.DISCONNECTED)
            updateState(ConnectionState.DISCONNECTED)
        }
        root.addView(stop)
        root.addView(button("打开操作测试页") { startActivity(Intent(this, ControlTestActivity::class.java)) }, spaced())
        root.addView(button("后台运行设置（按需）") {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        })
        root.addView(label("重启后：解锁 → 打开本 App → 点连接。\n若系统关闭了无障碍权限，按上方按钮重新开启。\n不自动解锁，不自动同意系统授权，不读取短信或通知。", 14), spaced())
        root.addView(label("Phone Assistant ${BuildConfig.VERSION_NAME}\n基于 Mobilerun Portal v0.7.25 · AGPL-3.0-or-later\nCopyright (C) 2025 Niels Schmidt\n本衍生版不提供担保，可按许可证修改及分发。\n源码与许可：github.com/kengerlwl/phone-assistant", 12), spaced())
        ConnectionStateManager.connectionState.observe(this) { updateState(it) }
        intent.dataString?.let(::importPairingLink)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent.dataString?.let(::importPairingLink)
    }

    private fun importPairingLink(value: String) {
        if (pairing || config.reverseConnectionEnabled) {
            toast("请先断开当前连接再导入")
            return
        }
        try {
            val details = PairingLink.parse(value)
            server.setText(details.server)
            code.setText(details.code)
            toast("地址和配对码已填入，请核对服务器后主动点连接")
        } catch (_: Exception) {
            toast("配对链接无效，请使用服务器生成的链接")
        }
    }

    override fun onResume() {
        super.onResume()
        privateScreenVisible = true
        if (::permissionStatus.isInitialized) refreshPermission()
    }

    override fun onPause() {
        privateScreenVisible = false
        super.onPause()
    }

    private fun refreshPermission() {
        val ready = MobilerunAccessibilityService.getInstance() != null
        permissionStatus.text = if (ready) "无障碍服务：已就绪" else "无障碍服务：未就绪，请在系统设置中开启「Phone Assistant」"
        permissionStatus.setTextColor(if (ready) accent else Color.rgb(156, 76, 22))
    }

    private fun connectRequested() {
        if (pairing) return
        if (MobilerunAccessibilityService.getInstance() == null) {
            toast("请先手动开启无障碍权限")
            return
        }
        val url = server.text.toString().trim()
        val uri = try { URI(url) } catch (_: Exception) { null }
        if (uri == null || uri.scheme != "wss" || uri.host.isNullOrBlank() || uri.userInfo != null || uri.query != null || uri.fragment != null || uri.path != "/device" || (uri.port != -1 && uri.port !in 1..65535)) {
            toast("请输入有效的 wss:// 加密服务器地址")
            return
        }
        val pin = code.text.toString().trim()
        if (pin.isBlank()) {
            if (config.reverseConnectionToken.isBlank() || url != config.reverseConnectionUrlOrDefault) {
                toast("首次连接或更换服务器，需要新的配对码")
                return
            }
            startConnection()
            return
        }
        if (!pin.matches(Regex("[0-9]{8}"))) { toast("配对码为 8 位数字"); return }
        pairing = true
        connect.isEnabled = false
        server.isEnabled = false
        code.isEnabled = false
        status.text = "正在安全配对…"
        Thread {
            var connection: HttpsURLConnection? = null
            try {
                val endpoint = URI("https", null, uri.host, uri.port, "/pair", null, null).toURL()
                connection = endpoint.openConnection() as HttpsURLConnection
                connection.connectTimeout = 12000
                connection.readTimeout = 12000
                connection.requestMethod = "POST"
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                val request = JSONObject().put("code", pin).put("deviceId", config.deviceID).toString()
                connection.outputStream.use { it.write(request.toByteArray(Charsets.UTF_8)) }
                check(connection.responseCode == 200) { "配对失败：请检查配对码或重新生成" }
                val response = connection.inputStream.bufferedReader().use { it.readText() }
                val token = JSONObject(response).getString("token")
                check(token.length >= 32) { "服务器返回的凭据无效" }
                runOnUiThread {
                    if (isDestroyed) return@runOnUiThread
                    config.reverseConnectionUrl = url
                    config.reverseConnectionToken = token
                    config.reverseConnectionServiceKey = ""
                    code.text.clear()
                    code.hint = "凭据已保存，重启后直接连接"
                    pairing = false
                    startConnection()
                }
            } catch (e: Exception) {
                runOnUiThread {
                    if (isDestroyed) return@runOnUiThread
                    pairing = false
                    updateState(ConnectionState.ERROR)
                    toast(e.message ?: "连接失败，请检查网络")
                }
            } finally { connection?.disconnect() }
        }.start()
    }

    private fun startConnection() {
        config.reverseConnectionEnabled = true
        config.forceLoginOnNextConnect = false
        try {
            startForegroundService(Intent(this, ReverseConnectionService::class.java).setAction(ReverseConnectionService.ACTION_RECONNECT))
            updateState(ConnectionState.CONNECTING)
        } catch (_: Exception) {
            config.reverseConnectionEnabled = false
            updateState(ConnectionState.ERROR)
            toast("系统暂不允许启动，请保持 App 在前台后重试")
        }
    }

    private fun updateState(state: ConnectionState) {
        if (!::status.isInitialized) return
        status.text = when (state) {
            ConnectionState.CONNECTED -> "已连接 · 助手可以操作"
            ConnectionState.CONNECTING -> "正在连接…"
            ConnectionState.RECONNECTING -> "网络中断 · 正在重连…"
            ConnectionState.UNAUTHORIZED -> "凭据失效，请重新配对"
            ConnectionState.DISCONNECTED -> "已断开 · 不能远程操作"
            else -> "未连接，请检查网络或重新配对"
        }
        val active = state in setOf(ConnectionState.CONNECTED, ConnectionState.CONNECTING, ConnectionState.RECONNECTING)
        connect.isEnabled = !active && !pairing
        stop.isEnabled = active
        server.isEnabled = !active && !pairing
        code.isEnabled = !active && !pairing
        refreshPermission()
    }

    private fun label(value: String, size: Int, bold: Boolean = false) = TextView(this).apply {
        text = value; textSize = size.toFloat(); setTextColor(ink)
        setPadding(0, dp(5), 0, dp(5))
        if (bold) setTypeface(typeface, Typeface.BOLD)
    }
    private fun button(value: String, primary: Boolean = false, action: () -> Unit) = Button(this).apply {
        text = value; isAllCaps = false; textSize = 16f; minHeight = dp(52)
        setTextColor(if (primary) Color.WHITE else accent)
        background = GradientDrawable().apply {
            cornerRadius = dp(12).toFloat()
            setColor(if (primary) accent else Color.rgb(231, 240, 237))
        }
        setOnClickListener { action() }
        layoutParams = LinearLayout.LayoutParams(-1, dp(54)).apply { topMargin = dp(10) }
    }
    private fun spaced() = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(16); bottomMargin = dp(6) }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun toast(value: String) = Toast.makeText(this, value, Toast.LENGTH_LONG).show()
}
