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
from typing import List, Dict, Any, Optional
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
        "小説": """
- 文章選択: 具体的で分かりやすい場面を1000文字抽出。
- 設問: 叙述や描写などに即して、語句や文の意味、登場人物の様子、心情などを正しく理解していれば解ける問い。
- 選択肢: 明らかに誤りと分かる選択肢を1つ含め、正解を導きやすくする。
""",
        "評論": """
- 文章選択: 具体的で分かりやすい場面を1000文字抽出。
- 設問: 叙述や描写などに即して、語句や文の意味、文章の構成及び要旨などを正しく理解していれば解ける問い。
- 選択肢: 明らかに誤りと分かる選択肢を1つ含め、正解を導きやすくする。
"""
    },
    "共通テストレベル": {
        "小説": """
- 文章選択: 心情の屈折や情景描写の工夫が見られる一節を1000文字程度抽出。
- 設問: 登場人物の心情の推移やその背景、比喩や視点といった表現の特色が読者に与える効果、および本文の構造を多角的に分析する問い。
- 選択肢: 本文の言い換えが巧妙で、文脈上の細かな根拠を正確に照合させる、標準的かつ思考力を要する構成。
""",
        "評論": """
- 文章選択: 論理の展開が明確で、筆者の独自の主張や概念が提示されている箇所を1000文字程度抽出。
- 設問: 文章全体の構成や展開、筆者の主張の根拠、および語句の文脈的意味を的確に把握し、多角的な視点から考察させる問い。
- 選択肢: 部分的な一致に惑わされず、文章全体の要旨と照らし合わせて論理的な消去法を要求する、標準的かつ精緻な構成。
"""
    },
    "難関大学レベル": {
        "小説": """
- 文章選択: 文体や心理描写が重層的で、人間の内面の葛藤や実存的なテーマを扱う高度な一節を1000文字程度厳選。
- 設問: 叙述の微細なニュアンスから読み取れる心理の深層、言葉に込められた象徴的意味、あるいは作品の時代背景に踏み込んだ、極めて深い洞察を要する問い。
- 選択肢: 4択すべてが正解に見えるほど抽象度が高く、本文の表現とのわずかな「ずれ」を見抜かなければ解けない、高度に罠が仕掛けられた構成。
""",
        "評論": """
- 文章選択: 哲学、思想、芸術、社会批評など、高度な抽象概念や二項対立、反語的なレトリックを駆使した難解な文章を1000文字程度厳選。
- 設問: 筆者の思索のプロセスを追体験し、提示された概念の特異性や、一見矛盾する議論の帰結を読み解く、高度な論理的思考力と深い教養を試す問い。
- 選択肢: 本文の言葉を単に拾うのではなく、その本質を捉え直した高度な抽象化がなされており、微細な論理の綻びを聞き分ける必要がある構成。
"""
    }
}

# 設問テーマ（設問タイプ）の定義
THEMES_MULTIPLE_CHOICE = {
    "REASON_CHOICE": {
        "title": "傍線部の理由説明",
        "target": "なぜその状況・発言に至ったのかの論理的因果関係を問う",
        "rule": "傍線部の「なぜか」「その根拠」を問う4択問題を作成せよ。・正解：本文の根拠に基づいた因果関係・誤答：因果の逆転、根拠の欠落、本文と無関係な理由"
    },
    "PARAPHRASE_CHOICE": {
        "title": "傍線部の言い換え・内容説明",
        "target": "「どういうことか」という換言・具体化能力を問う",
        "rule": "傍線部（比喩・抽象表現・指示語など）を分かりやすく説明した4択問題を作成せよ。・正解：本文文脈に合致する抽象↔具体の換言・誤答：一部のみ正しい（不十分）、誇張（言い過ぎ）、ニュアンスのズレ"
    },
    "EMOTION_CHOICE": {
        "title": "登場人物の心情・心理変化",
        "target": "場面の情景や言動から心理変化を客観的に読み取る力を問う",
        "rule": "場面（情景・言動・対話）における登場人物の心情やその変化を問う4択問題を作成せよ。・正解：文脈・描写から客観的に導ける感情・誤答：現代的な先入観による解釈、本文描写と反する感情"
    },
    "SUMMARY_CHOICE": {
        "title": "段落・全体の要旨把握",
        "target": "文章全体の構造とメインテーマを把握する全体俯瞰力を問う",
        "rule": "文章全体の主張や特定段落のまとめとして最も適切なものを選ぶ4択問題を作成せよ。・正解：筆者の主張・メインテーマの要約・誤答：細部の話（部分的正解）、本文の主張と対立する内容"
    },
    "TRICKY_CHOICE": {
        "title": "高難易度（ひっかけ・消去法訓練）",
        "target": "言い過ぎ・すり替えなどの誤答を見抜く精緻な消去法能力を問う",
        "rule": "誤答選択肢の誤り（「言い過ぎ」「すり替え」「本文に記述なし」など）が見抜きにくい高難易度4択問題を作成せよ。"
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
    def __init__(self, book_id: str, title: str, author: str, zip_url: str, card_url: str, ndc: str):
        self.book_id = book_id
        self.title = title
        self.author = author
        self.zip_url = zip_url
        self.card_url = card_url
        self.ndc = ndc


def load_books_from_csv(csv_path: str) -> Dict[str, List[BookInfo]]:
    """CSVからNDC分類（913:小説, 914:評論）に応じた作品リストを取得"""
    books = {"小説": [], "評論": []}
    if not os.path.exists(csv_path):
        print(f"エラー: CSVファイルが見つかりません: {csv_path}")
        return books

    with open(csv_path, mode="r", encoding="shift_jis", errors="ignore") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if len(row) > 45:
                ndc = row[8].strip()
                zip_url = row[45].strip()
                title = row[1].strip()
                author = f"{row[15].strip()}{row[16].strip()}"
                book_id = row[0].strip()
                card_url = row[13].strip() if len(row) > 13 else ""

                if zip_url.startswith("http"):
                    book = BookInfo(book_id, title, author, zip_url, card_url, ndc)
                    if "913" in ndc:
                        books["小説"].append(book)
                    elif "914" in ndc:
                        books["評論"].append(book)

    # 作品ID（book_id）の若い順（昇順）にソート
    def parse_book_id(b: BookInfo) -> int:
        try:
            return int(b.book_id)
        except ValueError:
            return 999999

    books["小説"].sort(key=parse_book_id)
    books["評論"].sort(key=parse_book_id)
    return books


def clean_aozora_text(text: str) -> str:
    """青空文庫のルビ・注釈を除去"""
    text = re.sub(r"《[^》]+》", "", text)
    text = re.sub(r"［[^］]+］", "", text)
    text = re.sub(r"｜", "", text)
    return text.strip()


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


def generate_quiz_with_gemini(
    api_key: str,
    book: BookInfo,
    clean_text: str,
    level: str,
    genre: str,
    quiz_type: str = "choice",
    model_name: str = "gemini-3.5-flash-lite"
) -> Optional[Dict[str, Any]]:
    """Gemini API を使って問題を1件生成（選択問題または記述問題）"""

    # 本文から8000文字程度抽出
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
あなたは超一流の国語教師です。以下の実在する青空文庫作品の「抜粋テキスト」から、指定難易度（{level}）および【設問テーマ】に相応しい最高品質の国語【記述問題】を作成してください。

【出典情報】
作品名：{book.title}
著者：{book.author}
指定ジャンル：{genre}
指定難易度：{level}

【設問テーマ（最重要指示）】
テーマ名: {theme_info['title']}
設問の狙い: {theme_info['target']}
作問ルール: {theme_info['rule']}

【レベル別・作問ガイドライン】
{guideline}

【作成ルール】
1. ガイドラインに従い、抜粋テキストから最適な一節を「1000文字程度」抽出してください。
2. 【最重要：本文の完全現代語訳】抽出した本文（text）について、古い言葉遣い、難解な表現、旧字体、旧仮名遣いは、現代の中高生がそのままスムーズに理解できるわかりやすい現代語（新字体・現代仮名遣い）に完全に書き換えて出力してください。
3. 【重要：あらすじの作成】抽出した場面に至るまでの作品の背景やストーリー展開を50文字程度で作成し、文末は必ず「〜〜場面である。」の形式で締めくくってください（例: 「メロスが王の悪行を知り、暴君退治を決意して城へ向かう場面である。」）。
4. 本文内の核心箇所を一箇所だけ【傍線: 〇〇〇】で囲んでください。
5. 【設問テーマに沿った記述問題の作成】本文の【傍線: 〇〇〇】に関して、上記設問テーマの指示ルールに厳格に従った記述問題（question）を作成してください。
6. 【模範解答と採点基準の作成】指定文字数内に収まる最高品質の「模範解答（modelAnswer）」と、AIが採点する際の明確な「採点基準（gradingCriteria）」を箇条書きで作成してください。
7. 【重要：問題の重複回避】同じような問題文や問題内容を完全に回避し、ユニークで独自の問題を作成してください。

【出力フォーマット】
必ず以下のJSONオブジェクト形式のみを返却してください。
{{
  "title": "{book.title}（{book.author}）",
  "synopsis": "抽出場面に至るまでの背景やあらすじ（50文字程度。必ず『〜〜場面である。』で終わること）",
  "text": "1000文字程度の【現代語訳された本文】。必ず【傍線: 〇〇〇】を含めること。",
  "question": "テーマに沿った記述問題文。",
  "modelAnswer": "（模範解答）",
  "gradingCriteria": "1. 〇〇に言及していること (+50点)\n2. 〇〇を説明していること (+50点)",
  "explanation": "（解法のポイントと着眼点）"
}}

【対象テキスト（抜粋）】
{snippet}
"""
    else:
        theme_id, theme_info = random.choice(list(THEMES_MULTIPLE_CHOICE.items()))
        prompt = f"""
あなたは超一流の国語教師です。以下の実在する青空文庫作品の「抜粋テキスト」から、指定難易度（{level}）および【設問テーマ】に相応しい最高品質の国語問題（4択）を作成してください。

【出典情報】
作品名：{book.title}
著者：{book.author}
指定ジャンル：{genre}
指定難易度：{level}

【設問テーマ（最重要指示）】
テーマ名: {theme_info['title']}
設問の狙い: {theme_info['target']}
作問ルール: {theme_info['rule']}

【レベル別・作問ガイドライン】
{guideline}

【作成ルール】
1. ガイドラインに従い、抜粋テキストから最適な一節を「1000文字程度」抽出してください。
2. 【最重要：本文の完全現代語訳】抽出した本文（text）について、古い言葉遣い、難解な表現、旧字体、旧仮名遣いは、現代の中高生がそのままスムーズに理解できるわかりやすい現代語（新字体・現代仮名遣い）に完全に書き換えて出力してください。
3. 【重要：あらすじの作成】抽出した場面に至るまでの作品の背景やストーリー展開を50文字程度で作成し、文末は必ず「〜〜場面である。」の形式で締めくくってください（例: 「メロスが王の悪行を知り、暴君退治を決意して城へ向かう場面である。」）。
4. 本文内の核心箇所を一箇所だけ【傍線: 〇〇〇】で囲んでください。
5. 【設問テーマに沿った4択問題の作成】上記設問テーマのルールに厳格に従って4択問題（questionおよびoptions）を作成してください。
6. 解説では番号を使わず、選択肢の内容に基づいて {level} に相応しい着眼点で詳しく説明してください。
7. 【重要：問題の重複回避】同じような問題文や同じような問題内容、選択肢の使い回しを完全に回避し、ユニークで独自の問題を作成してください。

【出力フォーマット】
必ず以下のJSONオブジェクト形式のみを返却してください。
{{
  "title": "{book.title}（{book.author}）",
  "synopsis": "抽出場面に至るまでの背景やあらすじ（50文字程度。必ず『〜〜場面である。』で終わること）",
  "text": "1000文字程度の【現代語訳された本文】。必ず【傍線: 〇〇〇】を含めること。",
  "question": "テーマに沿った4択問題文。",
  "options": ["選択肢1", "選択肢2", "選択肢3", "選択肢4"],
  "correctAnswerIndex": 0〜3（正解位置は0〜3の数値）,
  "explanation": "詳細な解説（番号言及禁止）"
}}

【対象テキスト（抜粋）】
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
            raw_text = raw_response_text.strip()
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(json)?", "", raw_text).strip()
                raw_text = re.sub(r"```$", "", raw_text).strip()

            data = json.loads(raw_text)

            synopsis = str(data.get("synopsis", "")).strip()
            body_text = str(data.get("text", "")).strip()
            formatted_text = f"【あらすじ】\n{synopsis}\n\n【本文】\n{body_text}" if synopsis else body_text

            raw_title = str(data.get("title", f"{book.title}（{book.author}）")).strip()
            cleaned_title = re.sub(r"（現代.*）", "", raw_title).strip()
            cleaned_title = re.sub(r"\(現代.*\)", "", cleaned_title).strip()

            if quiz_type == "essay":
                quiz_item = {
                    "id": str(uuid.uuid4()),
                    "title": cleaned_title,
                    "text": formatted_text,
                    "question": data.get("question", ""),
                    "options": [],
                    "correctAnswerIndex": 0,
                    "explanation": data.get("explanation", ""),
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
                quiz_item = {
                    "id": str(uuid.uuid4()),
                    "title": cleaned_title,
                    "text": formatted_text,
                    "question": data.get("question", ""),
                    "options": data.get("options", []),
                    "correctAnswerIndex": int(data.get("correctAnswerIndex", 0)),
                    "explanation": data.get("explanation", ""),
                    "level": level,
                    "genre": genre,
                    "quizType": "MULTIPLE_CHOICE",
                    "modelAnswer": None,
                    "gradingCriteria": None,
                    "themeTypeId": theme_id,
                    "themeTitle": theme_info["title"],
                    "themeTarget": theme_info["target"],
                    "bookId": book.book_id,
                    "cardUrl": book.card_url
                }

                # 選択肢のシャッフル（正解インデックスの自動調整）
                options_with_correct = [(opt, i == quiz_item["correctAnswerIndex"]) for i, opt in enumerate(quiz_item["options"])]
                random.shuffle(options_with_correct)
                quiz_item["options"] = [item[0] for item in options_with_correct]
                quiz_item["correctAnswerIndex"] = next(i for i, item in enumerate(options_with_correct) if item[1])

            return quiz_item

        except Exception as e:
            print(f"  [Warn] Gemini生成エラー(試行 {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                wait_sec = 15 * attempt
                print(f"   -> サーバーの過負荷/一時的エラーのため {wait_sec}秒間 待機して自動再試行します...")
                time.sleep(wait_sec)
            else:
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
    parser.add_argument("--api_key", type=str, default=os.getenv("GEMINI_API_KEY", ""), help="Gemini API Key")
    parser.add_argument("--csv", type=str, default="../app/src/main/assets/aozora_works.csv", help="aozora_works.csv のパス")
    parser.add_argument("--count_per_category", type=int, default=10, help="1つの(難易度×ジャンル)あたりの目標生成数")
    parser.add_argument("--output_dir", type=str, default="./quiz_output", help="出力先ディレクトリ")
    parser.add_argument("--model", type=str, default="gemini-3.5-flash-lite", help="Geminiモデル名")
    parser.add_argument("--interval", type=int, default=10, help="生成間隔（秒）。RPM制限回避用（デフォルト: 10秒）")
    parser.add_argument("--quiz_type", type=str, choices=["choice", "essay"], default="choice", help="問題形式: choice (選択問題) または essay (記述問題)")
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
    print(f"作品ロード完了: 小説 {len(books_by_genre['小説'])}件, 評論 {len(books_by_genre['評論'])}件")

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

            needed = args.count_per_category - len(existing_quizzes)
            print(f"\n--- 処理中: [{level}] ✕ [{genre}] (既存: {len(existing_quizzes)}問 / 目標: {args.count_per_category}問) ---")

            if needed <= 0:
                print("  目標数を達成しているためスキップします。")
                continue

            candidate_books = books_by_genre.get(genre, [])
            if not candidate_books:
                print("  該当ジャンルの作品がCSV内にありません。")
                continue

            existing_questions = {q.get("question", "") for q in existing_quizzes if isinstance(q, dict)}
            processed_book_ids = {
                str(q.get("bookId")) for q in existing_quizzes
                if isinstance(q, dict) and q.get("bookId")
            }
            generated_count = 0

            # 作品IDの若い順（昇順）に未作成の作品から順次選定
            for book in candidate_books:
                if len(existing_quizzes) >= args.count_per_category:
                    break

                # 既に過去に問題作成済みの作品はスキップ（未作成の中で一番IDが若い作品へ進む）
                if str(book.book_id) in processed_book_ids:
                    continue

                clean_text = download_and_extract_text(book.zip_url)
                if not clean_text or len(clean_text) < 1000:
                    continue

                text_length = len(clean_text)
                # 5,000文字あたり1問（5,000文字未満は1問）
                num_questions = max(1, math.ceil(text_length / 5000))
                print(f" -> 新規作品選択(ID: {book.book_id}): 『{book.title}』（{book.author}） - {text_length}字 -> 最大{num_questions}問作成")

                for q_idx in range(num_questions):
                    if len(existing_quizzes) >= args.count_per_category:
                        break

                    quiz = generate_quiz_with_gemini(
                        api_key=args.api_key,
                        book=book,
                        clean_text=clean_text,
                        level=level,
                        genre=genre,
                        quiz_type=args.quiz_type,
                        model_name=args.model
                    )

                    if quiz and quiz.get("question") not in existing_questions:
                        existing_quizzes.append(quiz)
                        existing_questions.add(quiz.get("question", ""))
                        processed_book_ids.add(str(book.book_id))
                        generated_count += 1
                        print(f"   [成功] 生成完了 ({len(existing_quizzes)}/{args.count_per_category}) [{q_idx + 1}/{num_questions}問目]")

                        # こまめにファイル保存
                        with open(raw_file, "w", encoding="utf-8") as f:
                            json.dump(existing_quizzes, f, ensure_ascii=False, indent=2)

                    # レート制限（RPM）回避のため指定秒数ウェイト（デフォルト10秒）
                    print(f"   [待機] レート制限回避のため {args.interval} 秒間待機します...")
                    time.sleep(args.interval)

    # 最後にパケット化処理
    pack_quizzes(args.output_dir)


if __name__ == "__main__":
    main()
