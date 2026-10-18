#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
青空文庫の作品から Gemini API を使用して国語読解問題を一括生成するスクリプト

【準備】
1. Python 3.8 以上が必要です。
2. 依存ライブラリのインストール:
   pip install google-genai requests

【使用方法】
python generate_quizzes.py --api_key YOUR_GEMINI_API_KEY --count_per_category 50

※ `--count_per_category` で難易度×ジャンルあたりの生成目標数を設定できます。
※ 生成されたデータは `quiz_output/` フォルダ下に構造化されて保存されます。
"""

import os
import sys
import re
import csv
import json
import time
import uuid
import random
import io
import zipfile
import argparse
import math
import glob
import functools
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

def get_seconds_until_1715_jst() -> float:
    """現在時刻(JST = UTC+9)から次の 17:15 (JST) までの待機秒数を計算"""
    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst)
    target_jst = now_jst.replace(hour=17, minute=15, second=0, microsecond=0)
    if now_jst >= target_jst:
        target_jst += timedelta(days=1)
    return (target_jst - now_jst).total_seconds()

try:
    from refine_quizzes import refine_quiz_item
except ImportError:
    refine_quiz_item = None

# ログ出力を即時反映（アンバッファ）させる設定
print = functools.partial(print, flush=True)

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
import urllib.request

try:
    from google import genai
    from google.genai import types
    HAS_GENAI_LIB = True
except ImportError:
    HAS_GENAI_LIB = False

# 定数定義
LEVELS = ["高校入試レベル", "共通テストレベル", "難関大学レベル"]
GENRES = ["小説", "評論"]

def make_progress_bar(current: int, total: int, length: int = 15) -> str:
    if total <= 0:
        return ""
    percent = min(100.0, (current / total) * 100.0)
    filled_len = int(length * current // total) if total > 0 else 0
    bar = "█" * filled_len + "░" * (length - filled_len)
    return f"[{bar}] {current}/{total}問 ({percent:.1f}%)"

LEVEL_DIR_MAP = {
    "高校入試レベル": "highschool",
    "共通テストレベル": "common_test",
    "難関大学レベル": "difficult_univ"
}

GENRE_DIR_MAP = {
    "小説": "novel",
    "評論": "essay"
}

LEVEL_GUIDELINES = {
    "高校入試レベル": {
        "小説": "【場面】具体的で分かりやすい場面。【設問】登場人物の心情・言動・語句の意味を問う。【選択肢】明確な誤りを含め解きやすくする。",
        "評論": "【文章】論理の展開が分かりやすい箇所。【設問】文章の構成・要旨・語句の意味を問う。【選択肢】標準的な構成。"
    },
    "共通テストレベル": {
        "小説": "【場面】心情の屈折や情景描写の工夫が見られる一節。【設問】心情推移、表現の効果、本文構造の多角分析。【選択肢】巧妙な言い換えを含み文脈照合を要求する。",
        "評論": "【文章】筆者の独自の主張や概念が提示された箇所。【設問】文章の構成、主張の根拠、語句の文脈的意味。【選択肢】消去法を要する精緻な構成。"
    },
    "難関大学レベル": {
        "小説": "【場面】葛藤や実存的テーマを扱う高度な一節。【設問】心理の深層、象徴的意味、微細なニュアンスの解釈。【選択肢】抽象度が高くわずかなズレを見抜かせる構成。",
        "評論": "【文章】高度な抽象概念や二項対立を駆使した難解な文章。【設問】思索のプロセス追体験、概念の特異性の解釈。【選択肢】高度な抽象化がなされた精緻な構成。"
    }
}

# 設問テーマ（設問タイプ）の定義
THEMES_MULTIPLE_CHOICE = {
    "REASON_CHOICE": {
        "title": "傍線部の理由説明",
        "target": "なぜその状況・発言に至ったのかの論理的因果関係を問う",
        "rule": "傍線部の「なぜか」「その根拠」を問う問題を作成せよ。・正解：本文の根拠に基づいた因果関係・誤答：因果の逆転、根拠の欠落、無関係な理由"
    },
    "PARAPHRASE_CHOICE": {
        "title": "傍線部の言い換え・内容説明",
        "target": "「どういうことか」という換言・具体化能力を問う",
        "rule": "傍線部（比喩・抽象表現・指示語など）を分かりやすく説明した問題を作成せよ。・正解：本文文脈に合致する換言・誤答：不十分な正解、誇張、ニュアンスのズレ"
    },
    "EMOTION_CHOICE": {
        "title": "登場人物の心情・心理変化",
        "target": "場面の情景や言動から心理変化を客観的に読み取る力を問う",
        "rule": "場面における登場人物の心情やその変化を問う問題を作成せよ。・正解：文脈から導ける感情・誤答：先入観による解釈、本文と反する感情"
    },
    "SUMMARY_CHOICE": {
        "title": "段落・全体の要旨把握",
        "target": "文章全体の構造とメインテーマを把握する全体俯瞰力を問う",
        "rule": "文章全体の主張や特定段落のまとめを選択する問題を作成せよ。・正解：筆者の主張・要約・誤答：細部の話（部分的正解）、主張と対立する内容"
    },
    "TRICKY_CHOICE": {
        "title": "高難易度（ひっかけ・消去法訓練）",
        "target": "言い過ぎ・すり替えなどの誤答を見抜く精緻な消去法能力を問う",
        "rule": "誤答選択肢の誤り（「言い過ぎ」「すり替え」「本文に記述なし」など）が見抜きにくい高難易度問題を作成せよ。"
    }
}


THEMES_ESSAY = {
    "SHORT_EXPLANATION": {
        "title": "要素まとめ（短文記述）",
        "target": "本文から必要な要素を集約・整理してまとめる力を問う",
        "rule": "傍線部の意味や理由を「〜から」「〜こと」などの形で短文（30〜50字程度）で説明させる問題を作成せよ。・模範解答および必須の採点要素（キーワード1〜2つ）を明記すること。"
    },
    "SUMMARY_WRITING": {
        "title": "要約・全体説明（長文記述）",
        "target": "論理構造を整理して論理的に構成する総合的な要約力を問う",
        "rule": "指定の段落または全体の要旨・筆者の主張を長文（80〜120字程度）でまとめさせる問題を作成せよ。・論理構造（「AであるためBとなり、結論としてCである」）を含めた採点基準を提示すること。"
    },
    "EMOTION_WRITING": {
        "title": "心情変化・背景説明",
        "target": "描写を根拠に登場人物の心理や経緯を自分の言葉で説明する力を問う",
        "rule": "登場人物の行動の裏にある心理や、その心情に至った経緯を説明させる問題（40〜80字程度）を作成せよ。・「[きっかけ/状況]によって[感情]になった」の構造を網羅する模範解答を作ること。"
    },
    "CRITICAL_THINKING": {
        "title": "思考力・考察記述",
        "target": "本文の理解を踏まえて自分の言葉で考察・意見を述べる応用力を問う",
        "rule": "本文の内容を踏まえた上で、読者（生徒）自身の考えや理由を述べる問題（80〜100字程度）を作成せよ。・「本文の理解＋自身の意見＋その理由」で評価するルーブリックを作成すること。"
    }
}

# 難易度とジャンルの別名マッピング（コマンドライン指定用）
LEVEL_ALIAS_MAP = {
    "highschool": "高校入試レベル",
    "normal": "高校入試レベル",
    "高校": "高校入試レベル",
    "高校入試": "高校入試レベル",
    "高校入試レベル": "高校入試レベル",
    "common_test": "共通テストレベル",
    "common": "共通テストレベル",
    "共通": "共通テストレベル",
    "共通テスト": "共通テストレベル",
    "共通テストレベル": "共通テストレベル",
    "difficult_univ": "難関大学レベル",
    "difficult": "難関大学レベル",
    "難関": "難関大学レベル",
    "難関大学": "難関大学レベル",
    "難関大学レベル": "難関大学レベル"
}

GENRE_ALIAS_MAP = {
    "novel": "小説",
    "小説": "小説",
    "essay": "評論",
    "評論": "評論"
}


class BookInfo:
    def __init__(self, book_id: str, title: str, author: str, zip_url: str, card_url: str, category: str):
        self.book_id = book_id
        self.title = title
        self.author = author
        self.zip_url = zip_url
        self.card_url = card_url
        self.category = category  # novel, novel-easy, essay, essay-easy


def load_books_from_csv(csv_path: str) -> Dict[str, List[BookInfo]]:
    """新しいCSVから問題分類（novel, novel-easy, essay, essay-easy）に応じた作品リストを取得"""
    books = {"novel": [], "novel-easy": [], "essay": [], "essay-easy": []}
    if not os.path.exists(csv_path):
        print(f"エラー: CSVファイルが見つかりません: {csv_path}")
        return books

    with open(csv_path, mode="r", encoding="shift_jis", errors="ignore") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if len(row) >= 8:
                book_id = row[0].strip()
                title = row[1].strip()
                category = row[2].strip().lower()  # novel, novel-easy, essay, essay-easy
                card_url = row[4].strip()
                author = row[6].strip()
                zip_url = row[7].strip()

                if zip_url.startswith("http") and category in books:
                    book = BookInfo(book_id, title, author, zip_url, card_url, category)
                    books[category].append(book)

    # 作品ID（book_id）の若い順（昇順）にソート
    def parse_book_id(b: BookInfo) -> int:
        try:
            return int(b.book_id)
        except ValueError:
            return 999999

    for cat in books:
        books[cat].sort(key=parse_book_id)

    return books


def get_candidate_books(books_by_cat: Dict[str, List[BookInfo]], level: str, genre: str) -> List[BookInfo]:
    """レベルとジャンル（小説/評論）に応じた対象作品リストを取得"""
    if genre == "小説":
        if level == "高校入試レベル":
            # 高校入試レベルの小説: novel + novel-easy
            raw_candidates = books_by_cat.get("novel", []) + books_by_cat.get("novel-easy", [])
        else:
            # 共通テスト / 難関大学レベルの小説: novel のみ
            raw_candidates = books_by_cat.get("novel", [])
    else:  # 評論
        if level == "高校入試レベル":
            # 高校入試レベルの評論: essay + essay-easy
            raw_candidates = books_by_cat.get("essay", []) + books_by_cat.get("essay-easy", [])
        else:
            # 共通テスト / 難関大学レベルの評論: essay のみ
            raw_candidates = books_by_cat.get("essay", [])

    # 作品ID（book_id）の昇順に並び替え
    def parse_book_id(b: BookInfo) -> int:
        try:
            return int(b.book_id)
        except ValueError:
            return 999999

    return sorted(raw_candidates, key=parse_book_id)


def clean_aozora_text(text: str) -> str:
    """青空文庫のルビ・注釈を除去"""
    text = re.sub(r"《[^》]+》", "", text)
    text = re.sub(r"［[^］]+］", "", text)
    text = re.sub(r"｜", "", text)
    return normalize_modern_japanese(text.strip())


def normalize_modern_japanese(text: str) -> str:
    """旧仮名遣いや不自然な大文字の「つ」、問題文の「六つから」等を現代日本語表記に後補正"""
    replacements = [
        ("ゐ", "い"), ("ヰ", "イ"),
        ("ゑ", "え"), ("ヱ", "エ"),
        ("くゎ", "か"), ("ぐゎ", "が"),
        ("つて", "って"), ("つた", "った"), ("つと", "っと"),
        ("つき", "っき"), ("つく", "っく"), ("つけ", "っけ"), ("つこ", "っこ"),
        ("つさ", "っさ"), ("つし", "っし"), ("つす", "っす"), ("つせ", "っせ"), ("つそ", "っそ"),
        ("つぱ", "っぱ"), ("つぴ", "っぴ"), ("つぷ", "っぷ"), ("つぺ", "っぺ"), ("つぽ", "っぽ"),
        ("つち", "っち"), ("つちゃ", "っちゃ"), ("つちゅ", "っちゅ"), ("つちょ", "っちょ"),
        ("座つ", "座っ"), ("立つ", "立っ"), ("買つ", "買っ"), ("言ふ", "いう"), ("思ふ", "おもう"),
        ("次の六つから", "次のうちから"),
        ("次の6つから", "次のうちから"),
        ("次の五つから", "次のうちから"),
        ("次の5つから", "次のうちから"),
        ("六つの選択肢", "選択肢"),
        ("6つの選択肢", "選択肢"),
        ("五つの選択肢", "選択肢"),
        ("5つの選択肢", "選択肢"),
        ("次の六つ", "次の選択肢"),
        ("次の6つ", "次の選択肢"),
        ("次の五つ", "次の選択肢"),
        ("次の5つ", "次の選択肢")
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def find_local_text_file(local_dir: str, book_id: str) -> Optional[str]:
    """ローカルの aozorabunko_text-master ディレクトリから作品IDに合致するtxtファイルを高速検索"""
    if not local_dir or not os.path.exists(local_dir):
        return None

    clean_id = str(book_id).lstrip("0")
    pattern = os.path.join(local_dir, "cards", "**", f"{clean_id}_*.txt")
    matches = glob.glob(pattern, recursive=True)
    if matches:
        return matches[0]

    pattern_zero = os.path.join(local_dir, "cards", "**", f"{book_id}_*.txt")
    matches_zero = glob.glob(pattern_zero, recursive=True)
    if matches_zero:
        return matches_zero[0]

    return None

def load_text_from_file_or_download(local_dir: str, book: BookInfo) -> Optional[str]:
    """ローカルのtxtファイルから優先読み込みし、無ければネットダウンロードを行わず即座にNoneを返して次の作品へスキップ"""
    local_txt_path = find_local_text_file(local_dir, book.book_id)
    if local_txt_path and os.path.exists(local_txt_path):
        try:
            with open(local_txt_path, "r", encoding="shift_jis", errors="ignore") as f:
                content = f.read()
                if content and len(content) > 100:
                    print(f"   ⚡ [ローカル高速ロード] {os.path.basename(local_txt_path)}")
                    return clean_aozora_text(content)
        except Exception:
            pass

    # ローカルに見つからなかった場合は即座に次の作品へ進むため None を返す
    return None

def download_and_extract_text(zip_url: str) -> Optional[str]:
    """ZIPをダウンロードして中のテキストを取得"""
    try:
        req = urllib.request.Request(zip_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            zip_bytes = response.read()

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            for filename in z.namelist():
                if filename.endswith(".txt"):
                    with z.open(filename) as f:
                        raw_bytes = f.read()
                        try:
                            return raw_bytes.decode("shift_jis")
                        except UnicodeDecodeError:
                            return raw_bytes.decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  [Warn] ダウンロード/解凍失敗 ({zip_url}): {e}")
        return None


def extract_continuous_passage(clean_text: str, target_length: int) -> str:
    """
    Python側で、原文から指定文字数（target_length: ±10%以内）に収まる
    完全に連続した「ツギハギ無しのひと繋がりの場面」を句切れ（。）単位で物理的に切り出す
    """
    text_length = len(clean_text)
    if text_length <= target_length:
        return clean_text

    max_start = max(0, text_length - target_length - 200)
    start_pos = random.randint(0, max_start)
    if start_pos > 0:
        idx = clean_text.find("。", start_pos)
        start_pos = idx + 1 if (idx != -1 and idx < start_pos + 300) else start_pos

    end_pos = start_pos + target_length
    if end_pos >= text_length:
        return clean_text[start_pos:]

    stop_idx = clean_text.find("。", end_pos - 100)
    if stop_idx != -1 and stop_idx < start_pos + target_length + 200:
        end_pos = stop_idx + 1
    else:
        stop_idx2 = clean_text.find("。", start_pos + target_length // 2)
        if stop_idx2 != -1:
            end_pos = stop_idx2 + 1

    passage = clean_text[start_pos:end_pos].strip()
    return passage


def generate_quiz_with_gemini(
    api_key: str,
    book: BookInfo,
    clean_text: str,
    level: str,
    genre: str,
    quiz_type: str = "choice",
    passage_length: int = 1000,
    option_count: int = 4,
    model_name: str = "gemini-3.5-flash-lite"
) -> Optional[Dict[str, Any]]:
    """Gemini API を使って問題を1件生成（選択問題または記述問題）"""

    # 本文から豊かな文脈（8000文字程度）をスニペットとして抽出
    extract_size = 8000
    text_length = len(clean_text)
    if text_length > extract_size:
        max_start = text_length - extract_size
        start = random.randint(0, max_start)
        idx = clean_text.find("。", start)
        adjusted_start = idx + 1 if (idx != -1 and idx < start + 500) else start
        snippet = clean_text[adjusted_start: adjusted_start + extract_size]
    else:
        snippet = clean_text

    guideline = LEVEL_GUIDELINES.get(level, {}).get(genre, "")

    if quiz_type == "essay":
        theme_id, theme_info = random.choice(list(THEMES_ESSAY.items()))
        prompt = f"""
あなたはプロの国語教師です。以下の抜粋テキストから、指定難易度（{level}）の国語【記述問題】を作成してください。

【基本情報】
・作品名: {book.title}（{book.author}）
・ジャンル: {genre} / 難易度: {level}
・作問指針: {guideline}
・設問テーマ: {theme_info['title']}（{theme_info['target']}）

【作成ルール】
1. 本文（text）: 抜粋テキストから主要な場面を「{passage_length}文字程度」抽出・現代語訳してください。旧仮名遣いや古風な表記は完全排除し、現代人がスムーズに読める現代日本語（新字体・現代仮名遣い）に書き換えてください。核心箇所1箇所を【傍線: 〇〇〇】で囲んでください。
2. あらすじ（synopsis）: 本文に至る背景を50文字程度で作成し、文末は「〜〜場面である。」で終えてください。
3. 設問・解答: 本文のみに基づいて解ける記述問題文（question）、模範解答（modelAnswer）、採点基準（gradingCriteria）を作成してください。（※指示代名詞がある場合は具体的人名を補足すること）
4. 解説（explanation）: 着眼点と解法のポイントを詳しく説明してください。

【出力フォーマット (JSONのみ)】
{{
  "title": "{book.title}（{book.author}）",
  "synopsis": "50文字程度のあらすじ（〜〜場面である。）",
  "text": "{passage_length}文字程度の現代語訳された本文【傍線: 〇〇〇】",
  "question": "記述問題文",
  "modelAnswer": "模範解答",
  "gradingCriteria": "1. 〇〇に言及 (+50点)\n2. 〇〇を説明 (+50点)",
  "explanation": "詳細な解説"
}}

【対象テキスト】
{snippet}
"""
    else:
        theme_id, theme_info = random.choice(list(THEMES_MULTIPLE_CHOICE.items()))
        prompt = f"""
あなたはプロの国語教師です。以下の抜粋テキストから、指定難易度（{level}）の国語問題を作成してください。

【基本情報】
・作品名: {book.title}（{book.author}）
・ジャンル: {genre} / 難易度: {level}
・レベル別指針: {guideline}
・設問テーマ: {theme_info['title']}（{theme_info['target']}）

【作成ルール】
1. 本文（text）: 抜粋テキストから主要な場面を「{passage_length}文字程度」抽出・現代語訳してください。旧仮名遣いや古風な表記は完全排除し、スムーズに読める現代日本語（新字体・現代仮名遣い）に書き換えてください。文章内の核心箇所1箇所を【傍線: 〇〇〇】で囲んでください。
2. あらすじ（synopsis）: 本文に至る背景を50文字程度で作成し、文末は「〜〜場面である。」で終えてください。
3. 問題文（question）: 傍線部や場面全体に関する、指定難易度（{level}）に応じた適切な問を作成してください。（※具体的な選択肢数は書かないこと。代名詞がある場合は具体的人名を補足すること）
4. 【最重要：選択肢および理由の作成】
   ・正解の選択肢1個を「correctOption」として作成し、なぜ正解なのか（本文の注目箇所と理由）を reason に記載してください。
   ・間違いの選択肢{option_count - 1}個を「wrongOptions」配列として作成し、それぞれなぜ不正解なのか（本文のどの記述と矛盾するか等の着眼点）を reason に記載してください。
5. 解説（explanation）: 本文の着眼点と解法のポイントを詳しく説明してください。

【出力フォーマット (JSONのみ)】
{{
  "title": "{book.title}（{book.author}）",
  "synopsis": "50文字程度のあらすじ（〜〜場面である。）",
  "text": "{passage_length}文字程度の現代語訳された本文【傍線: 〇〇〇】",
  "question": "テーマに沿った問題文（※選択肢数は書かない）",
  "correctOption": {{
    "text": "正解の選択肢文章",
    "reason": "本文の【〇〇】に着目すると〇〇となるため正解。"
  }},
  "wrongOptions": [
    {{
      "text": "間違いの選択肢1",
      "reason": "本文の【〇〇】という記述と矛盾するため不適。"
    }},
    {{
      "text": "間違いの選択肢2",
      "reason": "本文に記載のない解釈が含まれるため不適。"
    }}
    ...計{option_count - 1}個の誤答
  ],
  "explanation": "全体的な解法の着眼点と要点のまとめ解説"
}}

【対象テキスト】
{snippet}
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
                # SDKがない場合はDirect REST Call
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

            # クリーニング
            if not raw_response_text:
                raise ValueError("Gemini APIからの応答テキストが空(None)です（セーフティフィルター等によるブロックの可能性があります）")

            raw_text = raw_response_text.strip()
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(json)?", "", raw_text).strip()
                raw_text = re.sub(r"```$", "", raw_text).strip()

            data = json.loads(raw_text)

            synopsis = str(data.get("synopsis", "")).strip()
            body_text = str(data.get("text", "")).strip()
            formatted_text = f"【あらすじ】\n{synopsis}\n\n【本文】\n{body_text}" if synopsis else body_text
            formatted_text = normalize_modern_japanese(formatted_text)

            raw_title = str(data.get("title", f"{book.title}（{book.author}）")).strip()
            cleaned_title = re.sub(r"（現代.*）", "", raw_title).strip()
            cleaned_title = re.sub(r"\(現代.*\)", "", cleaned_title).strip()

            raw_question = normalize_modern_japanese(str(data.get("question", "")).strip())

            if quiz_type == "essay":
                quiz_item = {
                    "id": str(uuid.uuid4()),
                    "title": cleaned_title,
                    "text": formatted_text,
                    "question": raw_question,
                    "options": [],
                    "correctAnswerIndex": 0,
                    "explanation": normalize_modern_japanese(str(data.get("explanation", "")).strip()),
                    "level": level,
                    "genre": genre,
                    "quizType": "ESSAY",
                    "modelAnswer": data.get("modelAnswer", ""),
                    "gradingCriteria": data.get("gradingCriteria", ""),
                    "themeTypeId": theme_id,
                    "themeTitle": theme_info["title"],
                    "themeTarget": theme_info["target"],
                    "bookId": book.book_id,
                    "cardUrl": book.card_url
                }
            else:
                correct_opt = data.get("correctOption", {})
                wrong_opts = data.get("wrongOptions", [])

                if isinstance(correct_opt, dict) and "text" in correct_opt:
                    correct_opt["text"] = normalize_modern_japanese(str(correct_opt["text"]))
                    correct_opt["reason"] = normalize_modern_japanese(str(correct_opt.get("reason", "")))

                if isinstance(wrong_opts, list):
                    for wo in wrong_opts:
                        if isinstance(wo, dict):
                            wo["text"] = normalize_modern_japanese(str(wo.get("text", "")))
                            wo["reason"] = normalize_modern_japanese(str(wo.get("reason", "")))

                # テキスト一覧の構築
                all_opt_texts = []
                if isinstance(correct_opt, dict) and "text" in correct_opt:
                    all_opt_texts.append(correct_opt["text"])
                elif "options" in data and isinstance(data["options"], list):
                    all_opt_texts.extend([normalize_modern_japanese(str(o)) for o in data["options"]])

                if isinstance(wrong_opts, list):
                    for wo in wrong_opts:
                        if isinstance(wo, dict) and "text" in wo:
                            all_opt_texts.append(wo["text"])

                quiz_item = {
                    "id": str(uuid.uuid4()),
                    "title": cleaned_title,
                    "text": formatted_text,
                    "question": raw_question,
                    "options": all_opt_texts,
                    "correctAnswerIndex": 0,
                    "explanation": normalize_modern_japanese(str(data.get("explanation", "")).strip()),
                    "level": level,
                    "genre": genre,
                    "quizType": "MULTIPLE_CHOICE",
                    "modelAnswer": None,
                    "gradingCriteria": None,
                    "themeTypeId": theme_id,
                    "themeTitle": theme_info["title"],
                    "themeTarget": theme_info["target"],
                    "bookId": book.book_id,
                    "cardUrl": book.card_url,
                    "rawOptions": all_opt_texts,
                    "correctOption": correct_opt if isinstance(correct_opt, dict) else None,
                    "wrongOptions": wrong_opts if isinstance(wrong_opts, list) else []
                }

            return quiz_item

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota" in err_str or "too many requests" in err_str.lower():
                wait_sec = get_seconds_until_1715_jst()
                hours = int(wait_sec // 3600)
                minutes = int((wait_sec % 3600) // 60)
                seconds = int(wait_sec % 60)
                print(f"\n  [⚠️ 429 Rate Limit Detected] Gemini APIのクォータ制限(429)を検出しました。")
                print(f"  -> 次回の日本時間 17:15 (残り {hours}時間 {minutes}分 {seconds}秒) まで一時停止します...")
                time.sleep(wait_sec)
                print(f"  -> 17:15 になりました。自動再開します...\n")
                continue
            else:
                print(f"  [Warn] Gemini生成エラー(試行 {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    wait_sec = 15 * attempt
                    print(f"   -> サーバーの過負荷/一時的エラーのため {wait_sec}秒間 待機して自動再試行します...")
                    time.sleep(wait_sec)
                else:
                    return None

    return None


def pack_quizzes(output_dir: str, pack_size: int = 100):

    """ディレクトリ内のデータを100問ずつの pack_XXX.json にパケット化し、index.json を作成"""
    index_manifest = {"categories": {}}

    for level in LEVELS:
        level_dir_name = LEVEL_DIR_MAP[level]
        for genre in GENRES:
            genre_dir_name = GENRE_DIR_MAP[genre]

            target_dir = os.path.join(output_dir, level_dir_name, genre_dir_name)
            raw_file = os.path.join(target_dir, "raw_quizzes.json")

            if not os.path.exists(raw_file):
                continue

            with open(raw_file, "r", encoding="utf-8") as f:
                all_quizzes = json.load(f)

            # パケット出力
            packs_info = []
            total_count = len(all_quizzes)
            for i in range(0, total_count, pack_size):
                pack_num = (i // pack_size) + 1
                pack_filename = f"pack_{pack_num:03d}.json"
                pack_quizzes_chunk = all_quizzes[i: i + pack_size]

                pack_path = os.path.join(target_dir, pack_filename)
                with open(pack_path, "w", encoding="utf-8") as pf:
                    json.dump(pack_quizzes_chunk, pf, ensure_ascii=False, indent=2)

                packs_info.append({
                    "pack_name": pack_filename,
                    "count": len(pack_quizzes_chunk)
                })

            cat_key = f"{level_dir_name}/{genre_dir_name}"
            index_manifest["categories"][cat_key] = {
                "level": level,
                "genre": genre,
                "total_count": total_count,
                "packs": packs_info
            }

    index_path = os.path.join(output_dir, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_manifest, f, ensure_ascii=False, indent=2)
    print(f"\n[完了] パケット化および index.json の作成が完了しました: {index_path}")


def main():
    parser = argparse.ArgumentParser(description="青空文庫から問題データ一括生成ツール")
    parser.add_argument("--api_key", type=str, default=os.getenv("GEMINI_API_KEY", ""), help="Gemini API Key (生成用)")
    parser.add_argument("--refine_api_key", type=str, default="", help="Gemini API Key (現代語訳校正用。空なら--api_keyを使用)")
    parser.add_argument("--csv", type=str, default="../app/src/main/assets/aozora_works.csv", help="aozora_works.csv のパス")
    parser.add_argument("--local_text_dir", type=str, default=r"C:\Users\mamox\Desktop\aozorabunko_text-master", help="ローカルの青空文庫テキストフォルダーパス")
    parser.add_argument("--count_per_category", type=int, default=10, help="1つの(難易度×ジャンル)あたりの目標生成数")
    parser.add_argument("--output_dir", type=str, default="./quiz_output", help="出力先ディレクトリ")
    parser.add_argument("--model", type=str, default="gemini-3.5-flash-lite", help="Geminiモデル名")
    parser.add_argument("--interval", type=int, default=10, help="生成間隔（秒）。RPM制限回避用（デフォルト: 10秒）")
    parser.add_argument("--quiz_type", type=str, choices=["choice", "essay", "auto"], default="choice", help="問題形式: choice (選択問題), essay (記述問題), auto (指定比率で自動決定)")
    parser.add_argument("--choice_ratio", type=int, default=70, help="quiz_type=autoの場合の選択問題比率 (0-100)。残りが記述問題")
    parser.add_argument("--passage_length", type=int, default=1000, help="本文抽出の目標文字数（デフォルト: 1000文字）")
    parser.add_argument("--passage_length_highschool", type=int, default=800, help="高校入試レベル本文文字数（デフォルト: 800文字）")
    parser.add_argument("--passage_length_common_test", type=int, default=1200, help="共通テストレベル本文文字数（デフォルト: 1200文字）")
    parser.add_argument("--passage_length_difficult_univ", type=int, default=1500, help="難関大学レベル本文文字数（デフォルト: 1500文字）")
    parser.add_argument("--chars_per_quiz", type=int, default=5000, help="何文字につき1問作成するか（デフォルト: 5000文字）")
    parser.add_argument("--option_count", type=int, default=6, help="生成時の選択肢プール数（デフォルト: 6択[正解1+誤答5]）")
    parser.add_argument("--category", type=str, default="", help="カテゴリ指定 (例: difficult_novel, highschool_essay など)")
    parser.add_argument("--level", type=str, default="", help="難易度指定 (例: normal, common_test, difficult_univ など)")
    parser.add_argument("--genre", type=str, default="", help="ジャンル指定 (例: novel, essay など)")

    args = parser.parse_args()

    if not args.api_key:
        print("エラー: APIキーが指定されていません。--api_key か環境変数 GEMINI_API_KEY を設定してください。")
        return

    # 難易度とジャンルの絞り込み判定
    target_levels = LEVELS
    target_genres = GENRES

    req_level = args.level
    req_genre = args.genre

    if args.category:
        parts = args.category.replace("/", "_").split("_")
        if len(parts) >= 1 and parts[0]:
            req_level = parts[0]
        if len(parts) >= 2 and parts[1]:
            req_genre = parts[1]

    if req_level:
        norm_level = LEVEL_ALIAS_MAP.get(req_level.lower()) or LEVEL_ALIAS_MAP.get(req_level)
        if norm_level:
            target_levels = [norm_level]

    if req_genre:
        norm_genre = GENRE_ALIAS_MAP.get(req_genre.lower()) or GENRE_ALIAS_MAP.get(req_genre)
        if norm_genre:
            target_genres = [norm_genre]

    print("==========================================")
    print("  青空国語 問題データ自動生成ツール")
    print("==========================================")
    print(f"・対象レベル: {', '.join(target_levels)}")
    print(f"・対象ジャンル: {', '.join(target_genres)}")
    print(f"・目標生成数: 各カテゴリ {args.count_per_category} 個")
    print(f"・使用モデル: {args.model}")
    print(f"・出力先: {args.output_dir}\n")

    books_by_genre = load_books_from_csv(args.csv)
    print(f"作品ロード完了: 小説 {len(books_by_genre['novel'])}件 (easy: {len(books_by_genre['novel-easy'])}件), 評論 {len(books_by_genre['essay'])}件 (easy: {len(books_by_genre['essay-easy'])}件)")

    # 実行セッション全体でスキップ済み（ローカル未検出/短文）の作品IDを記憶するセット
    globally_skipped_book_ids = set()

    for level in target_levels:
        level_dir_name = LEVEL_DIR_MAP[level]
        for genre in target_genres:
            genre_dir_name = GENRE_DIR_MAP[genre]

            target_dir = os.path.join(args.output_dir, level_dir_name, genre_dir_name)
            os.makedirs(target_dir, exist_ok=True)
            raw_file = os.path.join(target_dir, "raw_quizzes.json")

            existing_quizzes = []
            if os.path.exists(raw_file):
                try:
                    with open(raw_file, "r", encoding="utf-8") as f:
                        existing_quizzes = json.load(f)
                except Exception:
                    existing_quizzes = []

            target_new_total = args.count_per_category
            if args.quiz_type == "choice":
                target_choice_count = target_new_total
                target_essay_count = 0
            elif args.quiz_type == "essay":
                target_choice_count = 0
                target_essay_count = target_new_total
            else:
                target_choice_count = int(round(target_new_total * (args.choice_ratio / 100.0)))
                target_essay_count = target_new_total - target_choice_count

            session_new_count = 0
            session_choice_count = 0
            session_essay_count = 0

            p_bar_init = make_progress_bar(0, target_new_total)
            print(f"\n==================================================")
            print(f" 📂 カテゴリ: [{level}] x [{genre}]")
            print(f" 📊 既存蓄積数: {len(existing_quizzes)}問 ➔ 今回新規作成目標: {target_new_total}問 (選択{target_choice_count}問 / 記述{target_essay_count}問)")
            print(f" 📊 進捗: {p_bar_init}")
            print(f"==================================================")

            candidate_books = get_candidate_books(books_by_genre, level, genre)
            if not candidate_books:
                print("  該当レベル・ジャンルの作品がCSV内にありません。")
                continue

            existing_questions = {q.get("question", "") for q in existing_quizzes if isinstance(q, dict)}
            processed_book_ids = {
                str(q.get("bookId")) for q in existing_quizzes
                if isinstance(q, dict) and q.get("bookId")
            }

            # レベルごとの本文目標文字数を決定
            if level == "高校入試レベル":
                effective_passage_length = args.passage_length_highschool
            elif level == "共通テストレベル":
                effective_passage_length = args.passage_length_common_test
            elif level == "難関大学レベル":
                effective_passage_length = args.passage_length_difficult_univ
            else:
                effective_passage_length = args.passage_length

            # 作品IDの若い順（昇順）に未作成の作品から順次選定
            for book in candidate_books:
                if session_new_count >= target_new_total:
                    break

                book_id_str = str(book.book_id)

                # 既に過去に問題作成済み、または一度でもスキップされた作品は二度と読み込まない
                if book_id_str in processed_book_ids or book_id_str in globally_skipped_book_ids:
                    continue

                clean_text = load_text_from_file_or_download(args.local_text_dir, book)
                if not clean_text or len(clean_text) < 1000:
                    globally_skipped_book_ids.add(book_id_str) # 二度と試さないよう記憶
                    print(f"   ⏩ [ローカル未検出/短文のためスキップ] ID: {book.book_id} 『{book.title}』 ➔ 次の作品を自動検索します")
                    continue

                text_length = len(clean_text)
                num_questions = max(1, math.ceil(text_length / args.chars_per_quiz))
                print(f" 📖 作品選択(ID: {book.book_id}): 『{book.title}』（{book.author}） - {text_length}字 ➔ 最大{num_questions}問作成 (目標文字数: {effective_passage_length}字)")

                for q_idx in range(num_questions):
                    if session_new_count >= target_new_total:
                        break

                    current_quiz_type = args.quiz_type
                    if current_quiz_type == "auto":
                        if session_choice_count < target_choice_count and session_essay_count < target_essay_count:
                            current_quiz_type = "choice" if random.randint(0, 99) < args.choice_ratio else "essay"
                        elif session_choice_count < target_choice_count:
                            current_quiz_type = "choice"
                        elif session_essay_count < target_essay_count:
                            current_quiz_type = "essay"
                        else:
                            current_quiz_type = "choice"

                    quiz = generate_quiz_with_gemini(
                        api_key=args.api_key,
                        book=book,
                        clean_text=clean_text,
                        level=level,
                        genre=genre,
                        quiz_type=current_quiz_type,
                        passage_length=effective_passage_length,
                        option_count=args.option_count,
                        model_name=args.model
                    )

                    if quiz and quiz.get("question") not in existing_questions:
                        refine_key = args.refine_api_key.strip() if hasattr(args, 'refine_api_key') and args.refine_api_key and args.refine_api_key.strip() else args.api_key
                        if refine_quiz_item and refine_key:
                            print(f"   ✨ [現代語訳自動校正] 現代語訳・難易度最適化を実行中...")
                            quiz = refine_quiz_item(api_key=refine_key, quiz=quiz, model_name=args.model)

                        existing_quizzes.append(quiz)
                        existing_questions.add(quiz.get("question", ""))
                        processed_book_ids.add(str(book.book_id))
                        session_new_count += 1
                        if quiz.get("quizType") == "ESSAY":
                            session_essay_count += 1
                        else:
                            session_choice_count += 1

                        p_bar = make_progress_bar(session_new_count, target_new_total)
                        print(f"   ✅ [成功・自動校正済] {p_bar} (選択{session_choice_count}/{target_choice_count}, 記述{session_essay_count}/{target_essay_count}) 『{book.title}』({q_idx + 1}/{num_questions}問目)")

                        # こまめにファイル保存
                        with open(raw_file, "w", encoding="utf-8") as f:
                            json.dump(existing_quizzes, f, ensure_ascii=False, indent=2)

                    # レート制限（RPM）回避のため指定秒数ウェイト
                    print(f"   ⏳ [待機] レート制限回避のため {args.interval} 秒間待機中...")
                    time.sleep(args.interval)

            p_bar_final = make_progress_bar(session_new_count, target_new_total)
            print(f"   🎉 [完了] [{level}] x [{genre}] 新規追加完了: {p_bar_final} (選択{session_choice_count}問 / 記述{session_essay_count}問)")


    # 最後にパケット化処理
    pack_quizzes(args.output_dir)


if __name__ == "__main__":
    main()
