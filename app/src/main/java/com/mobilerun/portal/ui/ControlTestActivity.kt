package com.mobilerun.portal.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Bundle
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity

/** Safe local fixtures: actions never send messages, spend money, or access accounts. */
class ControlTestActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(36, 36, 36, 48)
            setBackgroundColor(Color.WHITE)
        }
        val scroll = ScrollView(this).apply { addView(root) }
        setContentView(scroll)
        root.addView(TextView(this).apply { text = "手机助手 · 安全测试页"; textSize = 24f; setTextColor(Color.BLACK) })
        root.addView(TextView(this).apply { text = "这里的操作只改变本页面，不发送任何内容。"; textSize = 15f })
        val count = TextView(this).apply { text = "点击次数：0"; textSize = 20f }
        root.addView(count)
        var clicks = 0
        root.addView(Button(this).apply {
            text = "测试点击"; setOnClickListener { clicks++; count.text = "点击次数：$clicks" }
        })
        val input = EditText(this).apply { hint = "在这里测试中文输入"; contentDescription = "中文测试输入框"; textSize = 18f }
        root.addView(input)
        val result = TextView(this).apply { text = "尚未校验文字"; textSize = 18f }
        root.addView(Button(this).apply { text = "校验输入"; setOnClickListener { result.text = "已输入：${input.text}" } })
        root.addView(result)
        root.addView(TextView(this).apply { text = "下面是纯画布图片，文字不进入控件树："; textSize = 14f })
        root.addView(ImageFixture(this), LinearLayout.LayoutParams(-1, 290))
        for (i in 1..8) root.addView(TextView(this).apply {
            text = "滚动测试 · 第 $i 行"; textSize = 18f; setPadding(8, 24, 8, 24)
        })
        root.addView(Button(this).apply { text = "返回连接页"; setOnClickListener { finish() } })
    }

    private class ImageFixture(context: Context) : View(context) {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        init { importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO }
        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            canvas.drawColor(Color.rgb(225, 241, 235))
            paint.color = Color.rgb(23, 78, 64); paint.textSize = 38f
            canvas.drawText("图片测试  海盐饼干", 28f, 66f, paint)
            paint.textSize = 31f
            canvas.drawText("规格：120 克   价格：¥18.80", 28f, 122f, paint)
            canvas.drawText("批次：A-2026-1016", 28f, 171f, paint)
            paint.color = Color.rgb(205, 67, 57)
            canvas.drawCircle(65f, 233f, 22f, paint)
            paint.color = Color.rgb(31, 91, 166)
            canvas.drawRect(126f, 210f, 172f, 256f, paint)
        }
    }
}
