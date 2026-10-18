#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
既存の保存済みクイズデータ（raw_quizzes.json）に含まれる
「次の六つから」「次の6つから」などの不要な選択肢数表現を一括修正・クリーンアップするツール
"""

import os
import json
import subprocess
import sys

def clean_question_text(text: str) -> str:
    replacements = [
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
        ("次の5つ", "次の選択肢"),
        ("六つ", "四つ"),
        ("6つ", "4つ")
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text

def clean_all_quizzes(output_dir: str = "./quiz_output"):
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    target_output_dir = os.path.join(tools_dir, "quiz_output")

    cleaned_count = 0
    total_files = 0

    for root, dirs, files in os.walk(target_output_dir):
        for file in files:
            if file == "raw_quizzes.json":
                total_files += 1
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        quizzes = json.load(f)

                    if isinstance(quizzes, list):
                        updated = False
                        for q in quizzes:
                            if isinstance(q, dict) and "question" in q:
                                old_q = q["question"]
                                new_q = clean_question_text(old_q)
                                if old_q != new_q:
                                    q["question"] = new_q
                                    updated = True
                                    cleaned_count += 1

                        if updated:
                            with open(file_path, "w", encoding="utf-8") as f:
                                json.dump(quizzes, f, ensure_ascii=False, indent=2)
                            print(f" [修正完了] {file_path}")
                except Exception as e:
                    print(f" [エラー] {file_path}: {e}")

    print("==========================================")
    print(f"【クリーンアップ完了】計 {cleaned_count} 件の問題文を「次のうちから」へ修正しました！")
    print("==========================================")

    # indexおよびパケットの更新
    build_index_script = os.path.join(tools_dir, "build_index.py")
    if os.path.exists(build_index_script):
        print("\n-> index.json とパケットファイルを自動再構築中...")
        subprocess.run([sys.executable, build_index_script], cwd=tools_dir)

if __name__ == "__main__":
    clean_all_quizzes()
