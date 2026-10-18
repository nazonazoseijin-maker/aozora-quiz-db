#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
全生成済み問題を西暦2000年生まれ（現代人・Z世代）に最適化し、
自然な現代文・完璧な表現へブラッシュアップ＆誤り訂正する自動ツール
"""

import os
import sys
import re
import csv
import json
import time
import argparse
import urllib.request
import functools

# ログ出力を即時反映（アンバッファ）させる設定
print = functools.partial(print, flush=True)

try:
    from google import genai
    from google.genai import types
    HAS_GENAI_LIB = True
except ImportError:
    HAS_GENAI_LIB = False

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

LEVELS = ["高校入試レベル", "共通テストレベル", "難関大学レベル"]
GENRES = ["小説", "評論"]

LEVEL_DIR_MAP = {
    "高校入試レベル": "highschool",
    "共通テストレベル": "common_test",
    "難関大学レベル": "difficult_univ"
}

GENRE_DIR_MAP = {
    "小説": "novel",
    "評論": "essay"
}

def normalize_modern_japanese(text: str) -> str:
    """旧仮名遣いや不自然な大文字の「つ」などを現代日本語表記に後補正"""
    replacements = [
        ("ゐ", "い"), ("ヰ", "イ"),
        ("ゑ", "え"), ("ヱ", "エ"),
        ("くゎ", "か"), ("ぐゎ", "が"),
        ("つて", "って"), ("つた", "った"), ("つと", "っと"),
        ("つき", "っき"), ("つく", "っく"), ("つけ", "っけ"), ("つこ", "っこ"),
        ("つさ", "っさ"), ("つし", "っし"), ("つす", "っす"), ("つせ", "っせ"), ("つそ", "っそ"),
        ("つぱ", "っぱ"), ("つぴ", "っぴ"), ("つぷ", "っぷ"), ("つぺ", "っぺ"), ("つぽ", "っぽ"),
        ("つち", "っち"), ("つちゃ", "っちゃ"), ("つちゅ", "っちゅ"), ("つちょ", "っちょ"),
        ("座つ", "座っ"), ("立つ", "立っ"), ("買つ", "買っ"), ("言ふ", "いう"), ("思ふ", "おもう")
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text

def refine_quiz_item(api_key: str, quiz: dict, model_name: str = "gemini-3.5-flash-lite") -> dict:
    """Gemini API を使って1件の問題データを西暦2000年生まれの自然な現代文へ推敲・誤り訂正"""

    prompt = f"""
あなたは西暦2000年生まれの現代人（Z世代・現代の中高生・若者）に向けた超一流の国語編集者です。
以下の国語問題データを精査し、現代人が読んで完全に自然で、不自然な古風表記や旧仮名遣い・旧字体・文章や語句の誤りが一切ない【洗練された現代日本語表現】に校正・ブラッシュアップしてください。

【推敲・校正ルール】
1. 本文・設問・選択肢の完全現代語訳:
   「ゐた」「座つて」「いふ」「思ふ」などの旧仮名遣いや不自然な文体を排除し、スムーズに読める現代日本語に書き換えてください。
2. 誤り訂正・表現の推敲:
   文章や語句に誤りがあれば修正し、自然で論理的な文体にブラッシュアップしてください。（※指示代名詞がある場合は具体的人名を補足すること）
3. 傍線部・あらすじ形式の維持:
   本文内の【傍線: 〇〇〇】を必ず維持し、あらすじ文末は「〜〜場面である。」の形式を維持してください。

【元の問題データ】
作品タイトル: {quiz.get('title', '')}
本文:
{quiz.get('text', '')}

問題文:
{quiz.get('question', '')}

選択肢:
{json.dumps(quiz.get('options', []), ensure_ascii=False)}

解説:
{quiz.get('explanation', '')}

模範解答（記述の場合）:
{quiz.get('modelAnswer', '')}

採点基準（記述の場合）:
{quiz.get('gradingCriteria', '')}

【出力フォーマット】
必ず以下のJSONオブジェクト形式のみを返却してください。
{{
  "title": "{quiz.get('title', '')}",
  "text": "洗練・完全現代語訳された本文（必ず【傍線: 〇〇〇】を含めること）",
  "question": "自然に校正・推敲された問題文",
  "options": ["校正後の選択肢1", "選択肢2", "選択肢3", "選択肢4"],
  "explanation": "わかりやすく校正された解説",
  "modelAnswer": "（記述問題の場合は校正された模範解答、四択問題ならnull）",
  "gradingCriteria": "（記述問題の場合は校正された採点基準、四択問題ならnull）"
}}
"""

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            raw_response_text = ""
            if HAS_GENAI_LIB:
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
                raw_response_text = response.text
            else:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json"}
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    raw_response_text = res_json["candidates"][0]["content"]["parts"][0]["text"]

            raw_text = raw_response_text.strip()
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(json)?", "", raw_text).strip()
                raw_text = re.sub(r"```$", "", raw_text).strip()

            res_data = json.loads(raw_text)

            # 更新適用
            updated_quiz = quiz.copy()
            if res_data.get("text"):
                updated_quiz["text"] = normalize_modern_japanese(str(res_data["text"]).strip())
            if res_data.get("question"):
                updated_quiz["question"] = normalize_modern_japanese(str(res_data["question"]).strip())
            if res_data.get("options") and isinstance(res_data["options"], list) and len(res_data["options"]) > 0:
                updated_quiz["options"] = [normalize_modern_japanese(str(o)) for o in res_data["options"]]
            if res_data.get("explanation"):
                updated_quiz["explanation"] = normalize_modern_japanese(str(res_data["explanation"]).strip())
            if res_data.get("modelAnswer"):
                updated_quiz["modelAnswer"] = normalize_modern_japanese(str(res_data["modelAnswer"]).strip())
            if res_data.get("gradingCriteria"):
                updated_quiz["gradingCriteria"] = normalize_modern_japanese(str(res_data["gradingCriteria"]).strip())

            # タイトルのクリーニング
            raw_title = str(res_data.get("title", quiz.get("title", ""))).strip()
            cleaned_title = re.sub(r"（現代.*）", "", raw_title).strip()
            cleaned_title = re.sub(r"\(現代.*\)", "", cleaned_title).strip()
            updated_quiz["title"] = cleaned_title

            return updated_quiz

        except Exception as e:
            if attempt < max_retries:
                time.sleep(5 * attempt)
            else:
                print(f"  [Warn] 校正失敗: {e}")
                return quiz

    return quiz


def refine_all_quizzes(api_key: str, output_dir: str = "./quiz_output", interval: int = 10, model_name: str = "gemini-3.5-flash-lite"):
    print("==========================================")
    print("  ✨ 全問題の現代語訳ブラッシュアップ＆校正ツール")
    print("==========================================")
    print("・対象: 西暦2000年生まれが読んで自然な文章・設問への自動校正")
    print(f"・出力先: {output_dir}\n")

    total_refined = 0

    for level in LEVELS:
        level_dir_name = LEVEL_DIR_MAP[level]
        for genre in GENRES:
            genre_dir_name = GENRE_DIR_MAP[genre]

            target_dir = os.path.join(output_dir, level_dir_name, genre_dir_name)
            raw_file = os.path.join(target_dir, "raw_quizzes.json")

            if not os.path.exists(raw_file):
                continue

            try:
                with open(raw_file, "r", encoding="utf-8") as f:
                    quizzes = json.load(f)
            except Exception as e:
                print(f" エラー読み込み失敗 ({raw_file}): {e}")
                continue

            if not quizzes:
                continue

            print(f"\n📂 校正中: [{level}] x [{genre}] (全 {len(quizzes)} 問)")
            refined_list = []

            for idx, q in enumerate(quizzes):
                print(f" -> #{idx + 1}/{len(quizzes)} 校正中: 『{q.get('title', '')}』...")
                refined_q = refine_quiz_item(api_key, q, model_name=model_name)
                refined_list.append(refined_q)
                total_refined += 1

                # ファイルへ書き込み
                with open(raw_file, "w", encoding="utf-8") as f:
                    json.dump(refined_list, f, ensure_ascii=False, indent=2)

                print(f"   ✅ [完了] #{idx + 1} のブラッシュアップ・誤り訂正が完了しました")
                time.sleep(interval)

    print(f"\n==========================================")
    print(f"【大成功】全 {total_refined} 問の現代語訳ブラッシュアップ＆誤り訂正が完了しました！")
    print("==========================================")

    # 最後に build_index.py のパケット再構築を呼ぶ
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    build_index_script = os.path.join(tools_dir, "build_index.py")
    if os.path.exists(build_index_script):
        print("\n-> index.json とパケットファイルを自動構築中...")
        subprocess.run([sys.executable, build_index_script], cwd=tools_dir)


def main():
    parser = argparse.ArgumentParser(description="全問題の現代語訳ブラッシュアップ＆誤り訂正ツール")
    parser.add_argument("--api_key", type=str, default=os.getenv("GEMINI_API_KEY", ""), help="Gemini API Key")
    parser.add_argument("--output_dir", type=str, default="./quiz_output", help="出力先ディレクトリ")
    parser.add_argument("--interval", type=int, default=10, help="生成間隔（秒）")
    parser.add_argument("--model", type=str, default="gemini-3.5-flash-lite", help="Geminiモデル名")

    args = parser.parse_args()

    if not args.api_key:
        print("エラー: APIキーが指定されていません。--api_key を指定してください。")
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "quiz_output")

    refine_all_quizzes(
        api_key=args.api_key,
        output_dir=output_dir,
        interval=args.interval,
        model_name=args.model
    )

if __name__ == "__main__":
    main()
