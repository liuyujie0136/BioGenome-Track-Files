#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jiangnan Gacha Simulator - Add new characters

使用方法:
  python3 add_characters.py <新角色数据文件.txt> <index.html路径>

数据文件格式 (制表符或空格分隔):
  编号  稀有度  角色名  建造  农牧  制作  理财  探险

示例:
  240  天  新角色A  600  400  780  300  500
  241  侯  新角色B  300  500  200  600  400

注意:
  - 头像文件需手动放入 images/ 目录，命名为 "编号_角色名.png"
  - 立绘文件需手动放入 art/ 目录，命名为 "编号_角色名.png"
  - 脚本会自动备份原 index.html 为 index.html.bak
"""

import sys
import os
import json
import re
import shutil


def parse_input_file(filepath):
    """解析输入文件，返回新角色列表"""
    characters = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 7:
                print(f"  警告: 第{line_num}行数据不足，跳过: {line}")
                continue
            try:
                char_id = parts[0]
                rarity = parts[1]
                name = parts[2]
                stats = [int(v) for v in parts[3:8]]
                if rarity not in ("天", "侯", "卿"):
                    print(
                        f"  警告: 第{line_num}行稀有度'{rarity}'无效，应为天/侯/卿，跳过"
                    )
                    continue
                characters.append(
                    {"id": char_id, "rarity": rarity, "name": name, "stats": stats}
                )
            except (ValueError, IndexError) as e:
                print(f"  警告: 第{line_num}行解析失败: {e}")
                continue
    return characters


def compute_specialty(stats):
    """根据五围数据计算擅长"""
    labels = ["建造", "农牧", "制作", "理财", "探险"]
    max_v = max(stats)
    best = [labels[i] for i, v in enumerate(stats) if v == max_v]
    return best


def get_rank_class(value):
    """根据数值返回评级CSS类名"""
    if value > 650:
        return "rank-s"
    elif value >= 500:
        return "rank-a"
    elif value >= 300:
        return "rank-b"
    elif value >= 100:
        return "rank-c"
    else:
        return "rank-d"


def update_html(html_path, new_chars):
    """更新HTML文件，添加新角色数据"""
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. 更新 ALL_CHARS 数组
    all_chars_match = re.search(r"const ALL_CHARS\s*=\s*(\[.*?\]);", html, re.DOTALL)
    if not all_chars_match:
        print("错误: 无法找到 ALL_CHARS 定义")
        return False

    try:
        all_chars = json.loads(all_chars_match.group(1))
    except json.JSONDecodeError:
        print("错误: ALL_CHARS JSON 解析失败")
        return False

    # 找到当前最大编号
    max_idx = -1
    for c in all_chars:
        # 从 art 路径提取编号: art/XXX_名.png
        m = re.match(r"art/(\d+)_", c.get("art", ""))
        if m:
            max_idx = max(max_idx, int(m.group(1)))

    # 添加新角色
    added = 0
    for char in new_chars:
        # 检查是否已存在
        existing = [c for c in all_chars if c["name"] == char["name"]]
        if existing:
            print(f"  跳过已存在的角色: {char['name']}")
            continue

        idx = max_idx + 1
        max_idx = idx

        new_entry = {
            "name": char["name"],
            "rarity": char["rarity"],
            "art": f"art/{idx:03d}_{char['name']}.png",
            "avatar": f"images/{idx:03d}_{char['name']}.png",
        }
        all_chars.append(new_entry)
        added += 1
        print(f"  添加: {char['name']} ({char['rarity']}级, 编号{idx:03d})")

    if added == 0:
        print("没有新角色需要添加")
        return False

    # 替换 ALL_CHARS
    new_json = json.dumps(all_chars, ensure_ascii=False)
    html = (
        html[: all_chars_match.start()]
        + f"const ALL_CHARS = {new_json};"
        + html[all_chars_match.end():]
    )

    # 2. 更新 STATS_MAP
    stats_map_match = re.search(
        r"const STATS_MAP\s*=\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\};", html, re.DOTALL
    )
    if not stats_map_match:
        print("错误: 无法找到 STATS_MAP 定义")
        return False

    # 解析现有 STATS_MAP
    stats_content = stats_map_match.group(1)
    # 使用 eval-safe 方式解析
    stats_map_str = "{" + stats_content + "}"
    try:
        # 替换简写为标准JSON
        stats_map_str_fixed = stats_map_str.replace("'", '"')
        stats_map = json.loads(stats_map_str_fixed)
    except json.JSONDecodeError:
        # 尝试从HTML重新构建
        stats_map = {}

    # 添加新角色五围数据
    for char in new_chars:
        if char["name"] in stats_map:
            print(f"  跳过已存在的五围数据: {char['name']}")
            continue
        best = compute_specialty(char["stats"])
        stats_map[char["name"]] = {"v": char["stats"], "best": best}

    # 重建 STATS_MAP 字符串
    entries = []
    for name, data in stats_map.items():
        v_str = ",".join(str(x) for x in data["v"])
        best_str = '","'.join(data["best"])
        entries.append(f'"{name}":{{"v":[{v_str}],"best":["{best_str}"]}}')

    new_stats_map = "const STATS_MAP = {" + ",".join(entries) + "};"
    html = (
        html[: stats_map_match.start()] + new_stats_map + html[stats_map_match.end():]
    )

    # 写入文件
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n成功添加 {added} 个新角色!")
    print("请确保以下文件已放入对应目录:")
    for char in new_chars:
        idx_str = f"{max_idx:03d}"
        print(f"  images/{idx_str}_{char['name']}.png (头像)")
        print(f"  art/{idx_str}_{char['name']}.png (立绘)")

    return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    input_file = sys.argv[1]
    html_file = sys.argv[2]

    # 检查文件
    if not os.path.exists(input_file):
        print(f"错误: 输入文件不存在: {input_file}")
        sys.exit(1)
    if not os.path.exists(html_file):
        print(f"错误: HTML文件不存在: {html_file}")
        sys.exit(1)

    # 备份
    backup_path = html_file + ".bak"
    if not os.path.exists(backup_path):
        shutil.copy2(html_file, backup_path)
        print(f"已备份: {backup_path}")
    else:
        print(f"备份已存在: {backup_path}")

    # 解析输入
    print(f"\n解析输入文件: {input_file}")
    new_chars = parse_input_file(input_file)
    if not new_chars:
        print("没有找到有效的新角色数据")
        sys.exit(1)
    print(f"找到 {len(new_chars)} 个新角色")

    # 更新HTML
    print(f"\n更新HTML: {html_file}")
    success = update_html(html_file, new_chars)
    if success:
        print("\n完成! 请检查以下事项:")
        print("  1. 确认头像和立绘文件已放入 images/ 和 art/ 目录")
        print("  2. 在浏览器中刷新页面验证新角色显示正常")
    else:
        print("\n未做修改")
