package com.example.citruscollect.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.example.citruscollect.ui.LocalAppContainer
import com.example.citruscollect.ui.theme.CitrusColors

@Composable
fun DualHomeScreen(onIdentify: () -> Unit, onCollection: () -> Unit, onHistory: () -> Unit) {
    val container = LocalAppContainer.current
    val pending by container.repository.observePendingCount().collectAsState(initial = 0)
    val diagnoses by container.diagnosisRepository.observeAll().collectAsState(initial = emptyList())
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        Text("柚见 · 田间助手", color = CitrusColors.Green, style = MaterialTheme.typography.labelLarge)
        ScreenTitle("今天，想做什么？", "识别病虫害，或记录田间观察。")
        Surface(color = CitrusColors.Green, contentColor = CitrusColors.White, shape = RoundedCornerShape(22.dp)) {
            Column(Modifier.fillMaxWidth().padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text("给种植者的识别助手", style = MaterialTheme.typography.labelMedium)
                Text("拍照识别\n知道怎么处理", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                Text("拍清叶片或果实，了解可能的问题和处理方法。", style = MaterialTheme.typography.bodyMedium)
                Button(onClick = onIdentify, colors = ButtonDefaults.buttonColors(containerColor = CitrusColors.GreenSoft, contentColor = CitrusColors.Green), modifier = Modifier.fillMaxWidth()) { Text("拍照 / 选图识别 →") }
            }
        }
        AppSection {
            Text("采集人员工作区", color = CitrusColors.Muted, style = MaterialTheme.typography.labelMedium)
            Text("数据采集", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text("拍照、标注、离线保存，按批次上传。", color = CitrusColors.Muted)
            Text("$pending 条待上传", color = CitrusColors.Green)
            OutlinedButton(onClick = onCollection, modifier = Modifier.fillMaxWidth()) { Text("进入数据采集 →") }
        }
        AppSection {
            Text("每次判断，都能回头看", style = MaterialTheme.typography.titleMedium)
            Text("${diagnoses.size} 条识别记录 · ${diagnoses.count { it.followUpDate != null && it.observation.isBlank() }} 条待观察", color = CitrusColors.Muted)
            TextButton(onClick = onHistory) { Text("查看我的记录 →") }
        }
    }
}

@Composable
fun CollectionWorkspaceScreen(onCapture: () -> Unit, onRecords: () -> Unit, onBatches: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        ScreenTitle("数据采集", "按批次组织照片，每张图独立填写与上传。")
        AppSection {
            Text("开始田间采集", style = MaterialTheme.typography.titleLarge)
            Text("先选择地点与批次，再连续拍摄。离线时也能保留照片。", color = CitrusColors.Muted)
            Button(onClick = onCapture, modifier = Modifier.fillMaxWidth()) { Text("开始采集") }
            OutlinedButton(onClick = onBatches, modifier = Modifier.fillMaxWidth()) { Text("采集批次") }
            OutlinedButton(onClick = onRecords, modifier = Modifier.fillMaxWidth()) { Text("图片记录与上传") }
        }
        Text("拍照识别与采集独立使用。识别照片只有经你同意后，才会转入采集。", style = MaterialTheme.typography.bodySmall, color = CitrusColors.Muted)
    }
}
