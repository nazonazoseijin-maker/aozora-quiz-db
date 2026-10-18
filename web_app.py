#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
青空国語 - 問題生成・index構築・GitHub送信＆問題閲覧 WEB GUI アプリ
"""

import os
import sys
import json
import time
import subprocess
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# 単体校正用のモジュールインポート
try:
    from refine_quizzes import refine_quiz_item
    from build_index import pack_quizzes
except ImportError:
    refine_quiz_item = None
    pack_quizzes = None

PORT = 8080
LOG_MESSAGES = []
IS_RUNNING = False

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(TOOLS_DIR, "config.json")

DEFAULT_CONFIG = {
    "apiKey": "",
    "refineApiKey": "",
    "category": "",
    "quizType": "choice",
    "count": "50",
    "localTextDir": r"C:\Users\mamox\Desktop\aozorabunko_text-master",
    "passageLength": "1000",
    "passageLengthHighschool": "800",
    "passageLengthCommonTest": "1200",
    "passageLengthDifficultUniv": "1500",
    "charsPerQuiz": "5000",
    "optionCount": "6",
    "interval": "10"
}

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    cfg = DEFAULT_CONFIG.copy()
                    cfg.update(data)
                    return cfg
        except Exception as e:
            print("Config load error:", e)
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    try:
        current = load_config()
        current.update(cfg)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Config save error:", e)

# HTMLテンプレート
HTML_PAGE = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>青空国語 - データ作成＆問題閲覧ダッシュボード</title>
    <style>
        :root {
            --primary: #2196F3;
            --primary-dark: #1976D2;
            --success: #4CAF50;
            --warning: #FF9800;
            --bg: #F5F7FA;
            --card-bg: #FFFFFF;
            --text: #333333;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 20px;
        }
        .container {
            max-width: 960px;
            margin: 0 auto;
        }
        .header {
            background: linear-gradient(135deg, #1E88E5, #1565C0);
            color: white;
            padding: 20px 24px;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        .header h1 { margin: 0 0 8px 0; font-size: 22px; }
        .header p { margin: 0; opacity: 0.9; font-size: 13px; }

        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        .tab-btn {
            padding: 12px 24px;
            background: #E0E0E0;
            color: #555;
            border-radius: 8px;
            font-weight: bold;
            cursor: pointer;
            border: none;
            font-size: 14px;
        }
        .tab-btn.active {
            background: var(--primary);
            color: white;
        }

        .tab-content { display: none; }
        .tab-content.active { display: block; }

        .card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 20px 24px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            margin-bottom: 20px;
        }
        .card h2 {
            margin-top: 0; font-size: 16px; border-bottom: 2px solid #E3F2FD; padding-bottom: 8px; color: #1565C0;
            display: flex; justify-content: space-between; align-items: center;
        }
        .form-grid {
            display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px;
        }
        .form-group { display: flex; flex-direction: column; }
        .form-group.full-width { grid-column: span 2; }
        label { font-size: 13px; font-weight: bold; margin-bottom: 6px; color: #555; }
        input, select {
            padding: 10px 12px; border: 1px solid #CCCCCC; border-radius: 6px; font-size: 14px;
        }

        .btn-group { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 10px; }
        button {
            padding: 12px 20px; border: none; border-radius: 8px; font-size: 14px; font-weight: bold; cursor: pointer; transition: background-color 0.2s, transform 0.1s;
        }
        button:active { transform: scale(0.98); }
        .btn-primary { background-color: var(--primary); color: white; }
        .btn-success { background-color: var(--success); color: white; }
        .btn-warning { background-color: var(--warning); color: white; }
        .btn-secondary { background-color: #607D8B; color: white; font-size: 12px; padding: 6px 12px; }
        .btn-all { background: linear-gradient(135deg, #FF9800, #E65100); color: white; font-size: 15px; padding: 14px 28px; }
        .btn-refine-single {
            background: linear-gradient(135deg, #8E24AA, #5E35B1); color: white;
            font-size: 12px; padding: 6px 12px; border-radius: 6px; border: none; cursor: pointer; font-weight: bold;
        }
        .btn-refine-single:hover { background: #512DA8; }

        button:disabled { background-color: #CCCCCC !important; cursor: not-allowed; transform: none; }

        .console-card {
            background: #1E1E1E; color: #D4D4D4; font-family: "Consolas", "Courier New", monospace;
            padding: 16px; border-radius: 12px; height: 280px; overflow-y: auto; font-size: 13px; line-height: 1.5;
        }
        .log-line { margin: 0; white-space: pre-wrap; word-break: break-all; }
        .log-line.success { color: #81C784; }
        .log-line.error { color: #E57373; }
        .log-line.info { color: #64B5F6; }

        .status-badge { display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; margin-left: 10px; }
        .status-idle { background-color: #E0E0E0; color: #616161; }
        .status-running { background-color: #FFF9C4; color: #F57F17; animation: blink 1.5s infinite; }

        @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }

        /* 問題閲覧UIスタイル */
        .quiz-card {
            border: 1px solid #E0E0E0; border-radius: 10px; padding: 16px 20px; margin-bottom: 20px; background: #FAF9F6; position: relative;
        }
        .quiz-title { font-size: 17px; font-weight: bold; color: #1565C0; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
        .quiz-header-actions { display: flex; gap: 8px; align-items: center; }
        .quiz-theme { display: inline-block; background: #E3F2FD; color: #0D47A1; font-size: 12px; font-weight: bold; padding: 3px 8px; border-radius: 4px; margin-bottom: 8px; }
        .quiz-text-box {
            background: #FFFFFF; border: 1px solid #E0E0E0; padding: 14px; border-radius: 8px; max-height: 200px; overflow-y: auto; font-size: 14px; line-height: 1.6; margin-bottom: 12px;
        }
        .quiz-question { font-size: 15px; font-weight: bold; color: #222; margin-bottom: 10px; background: #FFF3E0; padding: 10px; border-radius: 6px; }
        .option-list { list-style: none; padding: 0; margin: 0 0 12px 0; }
        .option-item {
            padding: 8px 12px; border: 1px solid #DDD; border-radius: 6px; margin-bottom: 6px; font-size: 14px; background: #FFF;
        }
        .option-item.correct { background-color: #E8F5E9; border-color: #A5D6A7; font-weight: bold; color: #2E7D32; }
        .essay-box { background: #E1F5FE; padding: 10px; border-radius: 6px; margin-bottom: 8px; font-size: 13px; }
        .quiz-exp { font-size: 13px; color: #555; background: #F5F5F5; padding: 10px; border-radius: 6px; }
        .card-link { font-size: 12px; color: #1976D2; text-decoration: underline; }

        .toast {
            position: fixed; bottom: 20px; right: 20px; background: #323232; color: white;
            padding: 12px 24px; border-radius: 8px; font-size: 14px; font-weight: bold;
            display: none; box-shadow: 0 4px 12px rgba(0,0,0,0.2); z-index: 1000;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📘 青空国語 GUIダッシュボード</h1>
            <p>問題作成・インデックス構築・GitHub同期 ＆ 作成済み問題の閲覧・個別校正ツール</p>
        </div>

        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('tab-generate')">⚙️ 作成＆GitHub送信</button>
            <button class="tab-btn" onclick="switchTab('tab-viewer'); loadQuizzes();">📖 作成済み問題の閲覧・個別校正</button>
        </div>

        <!-- タブ1: 生成＆同期 -->
        <div id="tab-generate" class="tab-content active">
            <div class="card">
                <h2>
                    <span>⚙️ 作成設定</span>
                    <button type="button" class="btn-secondary" onclick="saveConfigToServer(true)">💾 設定を保存</button>
                </h2>
                <form id="configForm">
                    <div class="form-grid">
                        <div class="form-group">
                            <label for="apiKey">① 問題生成用 Gemini API キー</label>
                            <input type="password" id="apiKey" name="apiKey" placeholder="AQ.Ab8RN..." value="">
                        </div>

                        <div class="form-group">
                            <label for="refineApiKey">② 現代語訳校正用 Gemini API キー（※未入力時は①を使用）</label>
                            <input type="password" id="refineApiKey" name="refineApiKey" placeholder="未入力の場合は①と同じキーを使用" value="">
                        </div>

                        <div class="form-group">
                            <label for="category">カテゴリ（難易度 / ジャンル）</label>
                            <select id="category" name="category">
                                <option value="">すべて（全6パターン順次生成）</option>
                                <option value="highschool_novel">高校入試レベル ✕ 小説 (highschool_novel)</option>
                                <option value="highschool_essay">高校入試レベル ✕ 評論 (highschool_essay)</option>
                                <option value="common_test_novel">共通テストレベル ✕ 小説 (common_test_novel)</option>
                                <option value="common_test_essay">共通テストレベル ✕ 評論 (common_test_essay)</option>
                                <option value="difficult_univ_novel">難関大学レベル ✕ 小説 (difficult_univ_novel)</option>
                                <option value="difficult_univ_essay">難関大学レベル ✕ 評論 (difficult_univ_essay)</option>
                            </select>
                        </div>

                        <div class="form-group">
                            <label for="quizType">問題形式</label>
                            <select id="quizType" name="quizType">
                                <option value="choice">四択問題 (choice)</option>
                                <option value="essay">記述問題 / AI添削 (essay)</option>
                            </select>
                        </div>

                        <div class="form-group">
                            <label for="count">カテゴリごとの目標問題数</label>
                            <input type="number" id="count" name="count" value="50" min="1" max="1000">
                        </div>

                        <div class="form-group">
                            <label for="passageLengthHighschool">高校入試本文文字数 (目標/±20%)</label>
                            <input type="number" id="passageLengthHighschool" name="passageLengthHighschool" value="800" min="200" max="3000">
                        </div>

                        <div class="form-group">
                            <label for="passageLengthCommonTest">共通テスト本文文字数 (目標/±20%)</label>
                            <input type="number" id="passageLengthCommonTest" name="passageLengthCommonTest" value="1200" min="200" max="3000">
                        </div>

                        <div class="form-group">
                            <label for="passageLengthDifficultUniv">難関大学本文文字数 (目標/±20%)</label>
                            <input type="number" id="passageLengthDifficultUniv" name="passageLengthDifficultUniv" value="1500" min="200" max="3000">
                        </div>

                        <div class="form-group">
                            <label for="charsPerQuiz">何文字につき1問作成するか（文字）</label>
                            <input type="number" id="charsPerQuiz" name="charsPerQuiz" value="5000" min="1000" max="20000">
                        </div>

                        <div class="form-group">
                            <label for="optionCount">生成時の選択肢プール数（アプリ出題時は動的4択化）</label>
                            <select id="optionCount" name="optionCount">
                                <option value="4">4 択プール (正解1 + 誤答3)</option>
                                <option value="5">5 択プール (正解1 + 誤答4)</option>
                                <option value="6" selected>6 択プール (正解1 + 誤答5) ★おすすめ</option>
                            </select>
                        </div>

                        <div class="form-group">
                            <label for="interval">生成間隔ウェイト（秒）</label>
                            <input type="number" id="interval" name="interval" value="10" min="1" max="60">
                        </div>
                    </div>
                </form>
            </div>

            <div class="card">
                <h2>📊 作成済み問題数の内訳 (全 <span id="totalAllBadge" style="color: #1565C0;">0</span> 問)</h2>
                <div style="overflow-x: auto;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: center;">
                        <thead>
                            <tr style="background: #E3F2FD; color: #0D47A1; font-weight: bold;">
                                <th style="padding: 10px; border: 1px solid #BBDEFB;">難易度</th>
                                <th style="padding: 10px; border: 1px solid #BBDEFB;">ジャンル</th>
                                <th style="padding: 10px; border: 1px solid #BBDEFB;">四択問題 (選択式)</th>
                                <th style="padding: 10px; border: 1px solid #BBDEFB;">記述問題 (AI添削)</th>
                                <th style="padding: 10px; border: 1px solid #BBDEFB;">小計</th>
                            </tr>
                        </thead>
                        <tbody id="statsTableBody">
                            <tr><td colspan="5" style="padding: 12px; color: #888;">集計データを読み込み中...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <div class="card">
                <h2>🚀 ワンクリック操作</h2>
                <div class="btn-group">
                    <button type="button" class="btn-primary" onclick="runAction('generate')">⚡ ① 問題生成を実行</button>
                    <button type="button" class="btn-success" onclick="runAction('build_index')">📦 ② index.json を構築</button>
                    <button type="button" class="btn-warning" onclick="runAction('push')">☁️ ③ GitHub へ送信 (Push)</button>
                    <button type="button" style="background: linear-gradient(135deg, #9C27B0, #673AB7); color: white;" onclick="runAction('refine')">✨ [一括] 全問題の現代語訳＆校正</button>
                    <button type="button" class="btn-all" onclick="runAction('run_all')">✨ 【全自動】 ①➔②➔③ を一元実行</button>
                </div>
            </div>

            <div class="card">
                <h2>💻 リアルタイム実行ログ <span id="statusBadge" class="status-badge status-idle">待機中</span></h2>
                <div class="console-card" id="console">
                    <p class="log-line info">ダッシュボードが起動しました。操作ボタンを押してください。</p>
                </div>
            </div>
        </div>

        <!-- タブ2: 閲覧・個別校正 -->
        <div id="tab-viewer" class="tab-content">
            <div class="card">
                <h2>🔍 絞り込みフィルター</h2>
                <div class="form-grid">
                    <div class="form-group">
                        <label for="filterLevel">難易度</label>
                        <select id="filterLevel" onchange="loadQuizzes()">
                            <option value="highschool">高校入試レベル</option>
                            <option value="common_test">共通テストレベル</option>
                            <option value="difficult_univ">難関大学レベル</option>
                        </select>
                    </div>

                    <div class="form-group">
                        <label for="filterGenre">ジャンル</label>
                        <select id="filterGenre" onchange="loadQuizzes()">
                            <option value="novel">小説</option>
                            <option value="essay">評論</option>
                        </select>
                    </div>

                    <div class="form-group">
                        <label for="filterType">問題形式</label>
                        <select id="filterType" onchange="loadQuizzes()">
                            <option value="all">すべて</option>
                            <option value="MULTIPLE_CHOICE">四択問題</option>
                            <option value="ESSAY">記述問題</option>
                        </select>
                    </div>

                    <div class="form-group">
                        <label>&nbsp;</label>
                        <button type="button" class="btn-primary" onclick="loadQuizzes()">🔄 更新 / 読み込み</button>
                    </div>
                </div>
            </div>

            <div id="quizListContainer">
                <p style="text-align: center; color: #888;">問題データをロード中...</p>
            </div>
        </div>
    </div>

    <div id="toast" class="toast">処理が完了しました！</div>

    <script>
        let isRunning = false;

        window.onload = function() {
            loadConfigFromServer();
            loadStatsFromServer();
        };

        function loadStatsFromServer() {
            fetch('/api/stats')
                .then(res => res.json())
                .then(data => {
                    document.getElementById('totalAllBadge').innerText = data.totalAll;
                    const tbody = document.getElementById('statsTableBody');
                    if (!data.stats || data.stats.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="5" style="padding:12px; color:#888;">データがありません。</td></tr>';
                        return;
                    }
                    tbody.innerHTML = data.stats.map(s => `
                        <tr style="border-bottom: 1px solid #E0E0E0;">
                            <td style="padding: 8px; font-weight: bold; color: #333;">${s.levelName}</td>
                            <td style="padding: 8px; color: #555;">${s.genreName}</td>
                            <td style="padding: 8px; font-weight: bold; color: #1E88E5;">${s.choiceCount} 問</td>
                            <td style="padding: 8px; font-weight: bold; color: #8E24AA;">${s.essayCount} 問</td>
                            <td style="padding: 8px; font-weight: bold; color: #2E7D32;">${s.total} 問</td>
                        </tr>
                    `).join('');
                }).catch(e => console.error("Stats load failed:", e));
        }

        function switchTab(tabId) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(ct => ct.classList.remove('active'));

            if (tabId === 'tab-generate') {
                document.querySelectorAll('.tab-btn')[0].classList.add('active');
            } else {
                document.querySelectorAll('.tab-btn')[1].classList.add('active');
            }
            document.getElementById(tabId).classList.add('active');
        }

        function getFormData() {
            return {
                apiKey: document.getElementById('apiKey').value.trim(),
                refineApiKey: document.getElementById('refineApiKey').value.trim(),
                category: document.getElementById('category').value,
                quizType: document.getElementById('quizType').value,
                count: document.getElementById('count').value,
                passageLengthHighschool: document.getElementById('passageLengthHighschool').value,
                passageLengthCommonTest: document.getElementById('passageLengthCommonTest').value,
                passageLengthDifficultUniv: document.getElementById('passageLengthDifficultUniv').value,
                charsPerQuiz: document.getElementById('charsPerQuiz').value,
                optionCount: document.getElementById('optionCount').value,
                interval: document.getElementById('interval').value
            };
        }

        function loadConfigFromServer() {
            fetch('/api/config')
                .then(res => res.json())
                .then(cfg => {
                    if (cfg.apiKey) document.getElementById('apiKey').value = cfg.apiKey;
                    if (cfg.refineApiKey !== undefined) document.getElementById('refineApiKey').value = cfg.refineApiKey;
                    if (cfg.category !== undefined) document.getElementById('category').value = cfg.category;
                    if (cfg.quizType) document.getElementById('quizType').value = cfg.quizType;
                    if (cfg.count) document.getElementById('count').value = cfg.count;
                    if (cfg.passageLengthHighschool) document.getElementById('passageLengthHighschool').value = cfg.passageLengthHighschool;
                    if (cfg.passageLengthCommonTest) document.getElementById('passageLengthCommonTest').value = cfg.passageLengthCommonTest;
                    if (cfg.passageLengthDifficultUniv) document.getElementById('passageLengthDifficultUniv').value = cfg.passageLengthDifficultUniv;
                    if (cfg.charsPerQuiz) document.getElementById('charsPerQuiz').value = cfg.charsPerQuiz;
                    if (cfg.optionCount) document.getElementById('optionCount').value = cfg.optionCount;
                    if (cfg.interval) document.getElementById('interval').value = cfg.interval;
                }).catch(e => console.error("Config load failed:", e));
        }

        function saveConfigToServer(showToast) {
            const data = getFormData();
            fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            }).then(() => {
                if (showToast) displayToast("設定をローカルに保存しました！");
            }).catch(e => console.error("Config save failed:", e));
        }

        function displayToast(msg) {
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.style.display = 'block';
            setTimeout(() => { t.style.display = 'none'; }, 2500);
        }

        function runAction(actionType) {
            if (isRunning) {
                alert("現在処理が実行中です。完了までお待ちください。");
                return;
            }

            const data = getFormData();
            if ((actionType === 'generate' || actionType === 'run_all' || actionType === 'refine') && !data.apiKey) {
                alert("Gemini APIキーを入力してください。");
                return;
            }

            saveConfigToServer(false);

            isRunning = true;
            updateStatusUI(true, "処理実行中...");

            fetch('/api/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: actionType, config: data })
            }).then(res => res.json())
              .then(res => console.log("Started:", res))
              .catch(err => {
                  alert("エラーが発生しました: " + err);
                  isRunning = false;
                  updateStatusUI(false, "エラー");
              });
        }

        function updateStatusUI(running, text) {
            const badge = document.getElementById('statusBadge');
            const btns = document.querySelectorAll('button');
            if (running) {
                badge.className = "status-badge status-running";
                badge.innerText = text;
                btns.forEach(b => b.disabled = true);
            } else {
                badge.className = "status-badge status-idle";
                badge.innerText = "待機中";
                btns.forEach(b => b.disabled = false);
            }
        }

        function pollLogs() {
            fetch('/api/logs')
                .then(res => res.json())
                .then(data => {
                    const consoleEl = document.getElementById('console');
                    if (data.logs && data.logs.length > 0) {
                        // スクロール位置が最下部付近(30px以内)にあるか判定
                        const isAtBottom = (consoleEl.scrollHeight - consoleEl.clientHeight - consoleEl.scrollTop) <= 30;

                        consoleEl.innerHTML = data.logs.map(line => {
                            let cls = "log-line";
                            if (line.includes("[成功]") || line.includes("【成功】") || line.includes("OK")) cls += " success";
                            else if (line.includes("[Error]") || line.includes("エラー") || line.includes("fatal")) cls += " error";
                            else if (line.includes("処理") || line.includes("実行中")) cls += " info";
                            return `<p class="${cls}">${escapeHtml(line)}</p>`;
                        }).join('');

                        // ユーザーが最下部にいる時のみ自動スクロール（過去ログスクロールの妨げ防止）
                        if (isAtBottom) {
                            consoleEl.scrollTop = consoleEl.scrollHeight;
                        }
                    }
                    if (isRunning !== data.isRunning) {
                        isRunning = data.isRunning;
                        updateStatusUI(isRunning, isRunning ? "処理実行中..." : "待機中");
                    }
                }).catch(e => console.error(e));
        }

        function loadQuizzes() {
            const level = document.getElementById('filterLevel').value;
            const genre = document.getElementById('filterGenre').value;
            const type = document.getElementById('filterType').value;
            const container = document.getElementById('quizListContainer');

            container.innerHTML = '<p style="text-align: center; color: #888;">読み込み中...</p>';

            fetch(`/api/quizzes?level=${level}&genre=${genre}&type=${type}`)
                .then(res => res.json())
                .then(data => {
                    if (!data.quizzes || data.quizzes.length === 0) {
                        container.innerHTML = '<div class="card"><p style="text-align:center; color:#888;">該当する問題データがありません。</p></div>';
                        return;
                    }

                    container.innerHTML = data.quizzes.map((q, idx) => {
                        const isEssay = q.quizType === 'ESSAY';
                        const themeTag = q.themeTitle ? `<span class="quiz-theme">🎯 テーマ: ${escapeHtml(q.themeTitle)}</span>` : '';
                        const linkBtn = q.cardUrl ? `<a href="${q.cardUrl}" target="_blank" class="card-link">📖 青空文庫で開く</a>` : '';

                        let bodyHtml = '';
                        if (isEssay) {
                            bodyHtml = `
                                <div class="essay-box">
                                    <strong>【模範解答】</strong><br>${escapeHtml(q.modelAnswer || 'なし')}
                                    ${q.gradingCriteria ? `<br><br><strong>【採点基準】</strong><br>${escapeHtml(q.gradingCriteria)}` : ''}
                                </div>
                            `;
                        } else {
                            bodyHtml = `
                                <ul class="option-list">
                                    ${(q.options || []).map((opt, oIdx) => `
                                        <li class="option-item ${oIdx === q.correctAnswerIndex ? 'correct' : ''}">
                                            (${oIdx + 1}) ${escapeHtml(opt)} ${oIdx === q.correctAnswerIndex ? ' ✓ 正解' : ''}
                                        </li>
                                    `).join('')}
                                </ul>
                            `;
                        }

                        return `
                            <div class="quiz-card" id="quiz-card-${q.id}">
                                <div class="quiz-title">
                                    <span>#${idx + 1}. ${escapeHtml(q.title)} [${isEssay ? '記述' : '4択'}]</span>
                                    <div class="quiz-header-actions">
                                        <button class="btn-refine-single" id="btn-refine-${q.id}" onclick="refineSingleQuiz('${q.id}', '${level}', '${genre}')">
                                            ✨ この問題を現代語訳＆校正
                                        </button>
                                        ${linkBtn}
                                    </div>
                                </div>
                                ${themeTag}
                                <div class="quiz-text-box">${escapeHtml(q.text || '')}</div>
                                <div class="quiz-question">問. ${escapeHtml(q.question || '')}</div>
                                ${bodyHtml}
                                <div class="quiz-exp"><strong>【解説】</strong><br>${escapeHtml(q.explanation || '')}</div>
                            </div>
                        `;
                    }).join('');
                }).catch(err => {
                    container.innerHTML = `<div class="card"><p style="color:red;">データの読み込み失敗: ${err}</p></div>`;
                });
        }

        function refineSingleQuiz(quizId, level, genre) {
            const btn = document.getElementById(`btn-refine-${quizId}`);
            const apiKey = document.getElementById('refineApiKey').value.trim() || document.getElementById('apiKey').value.trim();

            if (btn) {
                btn.disabled = true;
                btn.innerText = "⏳ 現代語訳・校正中...";
            }

            fetch('/api/refine_single', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ quizId, level, genre, apiKey })
            }).then(res => res.json())
              .then(res => {
                  if (res.status === 'ok') {
                      displayToast("✨ この問題の現代語訳＆校正が完了しました！");
                      loadQuizzes();
                  } else {
                      alert("校正エラー: " + (res.error || "不明なエラー"));
                      if (btn) {
                          btn.disabled = false;
                          btn.innerText = "✨ この問題を現代語訳＆校正";
                      }
                  }
              }).catch(err => {
                  alert("エラーが発生しました: " + err);
                  if (btn) {
                      btn.disabled = false;
                      btn.innerText = "✨ この問題を現代語訳＆校正";
                  }
              });
        }

        function escapeHtml(text) {
            return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        }

        setInterval(pollLogs, 1000);
    </script>
</body>
</html>
"""

def append_log(msg: str):
    global LOG_MESSAGES
    LOG_MESSAGES.append(msg)
    if len(LOG_MESSAGES) > 500:
        LOG_MESSAGES = LOG_MESSAGES[-500:]

def run_command_stream(cmd_list: list, cwd: str):
    """コマンドを実行して出力をリアルタイムにログ追加"""
    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen(
            cmd_list,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env
        )
        for line in iter(process.stdout.readline, ''):
            if line:
                append_log(line.rstrip())
        process.stdout.close()
        process.wait()
        return process.returncode
    except Exception as e:
        append_log(f"[Error] コマンド実行失敗: {e}")
        return -1

def worker_thread(action: str, config: dict):
    global IS_RUNNING
    IS_RUNNING = True
    save_config(config)

    api_key = config.get("apiKey", "")
    refine_api_key = config.get("refineApiKey", "").strip() or api_key
    local_text_dir = config.get("localTextDir", r"C:\Users\mamox\Desktop\aozorabunko_text-master")
    category = config.get("category", "")
    quiz_type = config.get("quizType", "choice")
    count = config.get("count", "50")
    passage_length_hs = config.get("passageLengthHighschool", "800")
    passage_length_ct = config.get("passageLengthCommonTest", "1200")
    passage_length_du = config.get("passageLengthDifficultUniv", "1500")
    chars_per_quiz = config.get("charsPerQuiz", "5000")
    option_count = config.get("optionCount", "4")
    interval = config.get("interval", "10")

    try:
        if action in ["generate", "run_all"]:
            append_log(f"\n==========================================")
            append_log(f" 🚀 ① 問題生成スクリプトを開始します")
            append_log(f"==========================================")
            cmd = [
                sys.executable, "-u", "generate_quizzes.py",
                f"--api_key={api_key}",
                f"--refine_api_key={refine_api_key}",
                f"--local_text_dir={local_text_dir}",
                f"--count_per_category={count}",
                f"--interval={interval}",
                f"--quiz_type={quiz_type}",
                f"--passage_length_highschool={passage_length_hs}",
                f"--passage_length_common_test={passage_length_ct}",
                f"--passage_length_difficult_univ={passage_length_du}",
                f"--chars_per_quiz={chars_per_quiz}",
                f"--option_count={option_count}"
            ]
            if category:
                cmd.append(f"--category={category}")

            code = run_command_stream(cmd, cwd=TOOLS_DIR)
            if code != 0:
                append_log(f"[Warn] 問題生成がコード {code} で終了しました。")

        if action == "refine":
            refine_api_key = config.get("refineApiKey", "").strip() or api_key
            append_log(f"\n==========================================")
            append_log(f" ✨ 全問題の現代語訳ブラッシュアップ＆誤り訂正を開始します")
            append_log(f"==========================================")
            cmd = [
                sys.executable, "-u", "refine_quizzes.py",
                f"--api_key={refine_api_key}",
                f"--interval={interval}"
            ]
            run_command_stream(cmd, cwd=TOOLS_DIR)

        if action in ["build_index", "run_all"]:
            append_log(f"\n==========================================")
            append_log(f" 📦 ② index.json およびパケット構築を開始します")
            append_log(f"==========================================")
            cmd = [sys.executable, "-u", "build_index.py"]
            run_command_stream(cmd, cwd=TOOLS_DIR)

        if action in ["push", "run_all"]:
            append_log(f"\n==========================================")
            append_log(f" ☁️ ③ GitHub への同期 (Push) を開始します")
            append_log(f"==========================================")

            run_command_stream(["git", "add", "-A"], cwd=TOOLS_DIR)
            run_command_stream(["git", "commit", "-m", "WebGUIからの自動データ更新"], cwd=TOOLS_DIR)
            code = run_command_stream(["git", "push", "-u", "origin", "main"], cwd=TOOLS_DIR)

            if code != 0:
                append_log("   -> 通常Push失敗のため、強制Push (--force) を試みます...")
                run_command_stream(["git", "push", "-u", "origin", "main", "--force"], cwd=TOOLS_DIR)

            append_log(f"\n✨ 【成功】すべての作業が正常に完了いたしました！")

    except Exception as e:
        append_log(f"[Error] 作業スレッド例外: {e}")
    finally:
        IS_RUNNING = False


def get_quiz_stats() -> dict:
    """全12パターン（3レベル × 2ジャンル × 2形式）の作成済み件数を集計"""
    levels = [("highschool", "高校入試レベル"), ("common_test", "共通テストレベル"), ("difficult_univ", "難関大学レベル")]
    genres = [("novel", "小説"), ("essay", "評論")]

    stats = []
    total_choice_all = 0
    total_essay_all = 0

    for level_key, level_name in levels:
        for genre_key, genre_name in genres:
            target_raw = os.path.join(TOOLS_DIR, "quiz_output", level_key, genre_key, "raw_quizzes.json")
            choice_cnt = 0
            essay_cnt = 0
            if os.path.exists(target_raw):
                try:
                    with open(target_raw, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            for q in data:
                                if isinstance(q, dict):
                                    if q.get("quizType") == "ESSAY":
                                        essay_cnt += 1
                                    else:
                                        choice_cnt += 1
                except Exception:
                    pass

            stats.append({
                "levelKey": level_key,
                "levelName": level_name,
                "genreKey": genre_key,
                "genreName": genre_name,
                "choiceCount": choice_cnt,
                "essayCount": essay_cnt,
                "total": choice_cnt + essay_cnt
            })
            total_choice_all += choice_cnt
            total_essay_all += essay_cnt

    return {
        "stats": stats,
        "totalChoiceAll": total_choice_all,
        "totalEssayAll": total_essay_all,
        "totalAll": total_choice_all + total_essay_all
    }

class AppRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        url_obj = urlparse(self.path)
        url_path = url_obj.path
        query_params = parse_qs(url_obj.query)

        if url_path == "/" or url_path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))

        elif url_path == "/api/stats":
            stats_data = get_quiz_stats()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(stats_data, ensure_ascii=False).encode("utf-8"))

        elif url_path == "/api/config":
            cfg = load_config()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(cfg, ensure_ascii=False).encode("utf-8"))

        elif url_path == "/api/logs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            res = json.dumps({"logs": LOG_MESSAGES, "isRunning": IS_RUNNING})
            self.wfile.write(res.encode("utf-8"))

        elif url_path == "/api/quizzes":
            level = query_params.get("level", ["highschool"])[0]
            genre = query_params.get("genre", ["novel"])[0]
            quiz_type_filter = query_params.get("type", ["all"])[0]

            target_raw_file = os.path.join(TOOLS_DIR, "quiz_output", level, genre, "raw_quizzes.json")

            quizzes = []
            if os.path.exists(target_raw_file):
                try:
                    with open(target_raw_file, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                        if isinstance(raw_data, list):
                            quizzes = raw_data
                except Exception as e:
                    print("Error reading raw_quizzes:", e)

            if quiz_type_filter != "all":
                quizzes = [q for q in quizzes if q.get("quizType") == quiz_type_filter]

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"quizzes": quizzes}, ensure_ascii=False).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        url_path = urlparse(self.path).path
        if url_path == "/api/run":
            content_len = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_len)
            data = json.loads(body_bytes.decode("utf-8"))

            action = data.get("action", "")
            config = data.get("config", {})

            if not IS_RUNNING:
                t = threading.Thread(target=worker_thread, args=(action, config), daemon=True)
                t.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started"}).encode("utf-8"))

        elif url_path == "/api/config":
            content_len = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_len)
            cfg = json.loads(body_bytes.decode("utf-8"))

            save_config(cfg)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "saved"}).encode("utf-8"))

        elif url_path == "/api/refine_single":
            content_len = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_len)
            data = json.loads(body_bytes.decode("utf-8"))

            quiz_id = data.get("quizId")
            level = data.get("level", "highschool")
            genre = data.get("genre", "novel")
            api_key = data.get("apiKey") or load_config().get("apiKey", "")

            if not api_key:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Gemini APIキーが設定されていません。設定画面で入力してください。"}).encode("utf-8"))
                return

            if not refine_quiz_item:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "校正モジュールがロードできませんでした。"}).encode("utf-8"))
                return

            target_raw_file = os.path.join(TOOLS_DIR, "quiz_output", level, genre, "raw_quizzes.json")
            if not os.path.exists(target_raw_file):
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "対象の raw_quizzes.json が見つかりません。"}).encode("utf-8"))
                return

            try:
                with open(target_raw_file, "r", encoding="utf-8") as f:
                    quizzes = json.load(f)

                target_idx = -1
                for i, q in enumerate(quizzes):
                    if q.get("id") == quiz_id:
                        target_idx = i
                        break

                if target_idx == -1:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "対象の問題IDが見つかりませんでした。"}).encode("utf-8"))
                    return

                append_log(f" -> 個別現代語訳・校正開始: #{target_idx + 1} ({quizzes[target_idx].get('title')})")
                refined_q = refine_quiz_item(api_key, quizzes[target_idx])
                quizzes[target_idx] = refined_q

                with open(target_raw_file, "w", encoding="utf-8") as f:
                    json.dump(quizzes, f, ensure_ascii=False, indent=2)

                # パケット再構築
                if pack_quizzes:
                    output_dir = os.path.join(TOOLS_DIR, "quiz_output")
                    pack_quizzes(output_dir)

                append_log(f"   ✅ 個別現代語訳・校正完了: #{target_idx + 1}")

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "quiz": refined_q}).encode("utf-8"))

            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))


def main():
    print("==========================================")
    print("  青空国語 Web GUI アプリサーバー起動中")
    print("==========================================")
    print(f"・アクセスURL: http://localhost:{PORT}")
    print("・自動でブラウザが開きます...\n")

    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{PORT}")

    threading.Thread(target=open_browser, daemon=True).start()

    server = HTTPServer(("localhost", PORT), AppRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb アプリを終了しました。")

if __name__ == "__main__":
    main()
