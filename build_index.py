#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
現在ある raw_quizzes.json から即座に pack_XXX.json と index.json を再構築するツール
"""

import os
import json

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

def pack_quizzes(output_dir: str = "./quiz_output", pack_size: int = 100):
    """ディレクトリ内のデータを100問ずつの pack_XXX.json にパケット化し、index.json を作成"""
    index_manifest = {"categories": {}}

    print(f"-> quiz_output フォルダ ({output_dir}) をスキャンして index.json を構築中...")

    total_all_quizzes = 0

    for level in LEVELS:
        level_dir_name = LEVEL_DIR_MAP[level]
        for genre in GENRES:
            genre_dir_name = GENRE_DIR_MAP[genre]

            target_dir = os.path.join(output_dir, level_dir_name, genre_dir_name)
            raw_file = os.path.join(target_dir, "raw_quizzes.json")

            if not os.path.exists(raw_file):
                print(f" [スキップ] 存在しません: {raw_file}")
                continue

            try:
                with open(raw_file, "r", encoding="utf-8") as f:
                    all_quizzes = json.load(f)
            except Exception as e:
                print(f" [エラー] 読み込み失敗 ({raw_file}): {e}")
                continue

            if not all_quizzes:
                print(f" [スキップ] データが空です: {raw_file}")
                continue

            choice_quizzes = [q for q in all_quizzes if isinstance(q, dict) and q.get("quizType") != "ESSAY"]
            essay_quizzes = [q for q in all_quizzes if isinstance(q, dict) and q.get("quizType") == "ESSAY"]

            choice_packs_info = []
            for i in range(0, len(choice_quizzes), pack_size):
                pack_num = (i // pack_size) + 1
                pack_filename = f"pack_{pack_num:03d}.json"
                pack_chunk = choice_quizzes[i: i + pack_size]
                pack_path = os.path.join(target_dir, pack_filename)
                with open(pack_path, "w", encoding="utf-8") as pf:
                    json.dump(pack_chunk, pf, ensure_ascii=False, indent=2)
                choice_packs_info.append({"pack_name": pack_filename, "count": len(pack_chunk)})

            essay_packs_info = []
            for i in range(0, len(essay_quizzes), pack_size):
                pack_num = (i // pack_size) + 1
                pack_filename = f"essay_pack_{pack_num:03d}.json"
                pack_chunk = essay_quizzes[i: i + pack_size]
                pack_path = os.path.join(target_dir, pack_filename)
                with open(pack_path, "w", encoding="utf-8") as pf:
                    json.dump(pack_chunk, pf, ensure_ascii=False, indent=2)
                essay_packs_info.append({"pack_name": pack_filename, "count": len(pack_chunk)})

            total_count = len(all_quizzes)
            total_all_quizzes += total_count

            cat_key = f"{level_dir_name}/{genre_dir_name}"
            index_manifest["categories"][cat_key] = {
                "level": level,
                "genre": genre,
                "total_count": total_count,
                "packs": choice_packs_info if choice_packs_info else choice_packs_info,
                "choice_packs": choice_packs_info,
                "essay_packs": essay_packs_info
            }
            print(f" [OK] {level} ✕ {genre}: 選択問 {len(choice_quizzes)}問 / 記述問 {len(essay_quizzes)}問")

    index_path = os.path.join(output_dir, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_manifest, f, ensure_ascii=False, indent=2)

    print("==========================================")
    print(f"【成功】全 {total_all_quizzes} 問のデータから index.json を構築しました！")
    print(f"保存先: {os.path.abspath(index_path)}")
    print("==========================================")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "quiz_output")
    pack_quizzes(output_dir)
