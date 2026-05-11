#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jiangnan Gacha Simulator - Add new characters
使用方法:
  python add_characters.py <index.html路径> <新角色数据文件.txt>
数据文件格式 (制表符或空格分隔):
  编号  稀有度  角色名  建造  农牧  制作  理财  探险
示例:
  A01  天  新角色A  600  400  780  300  500
  A02  侯  新角色B  300  500  200  600  400
  B01  卿  新角色C  400  300  500  700  200
注意:
  - 编号由你手动指定（如A01、B02），脚本不做任何修改
  - 头像文件需手动放入 images/ 目录，命名为 "编号_角色名.png"
  - 立绘文件需手动放入 art/ 目录，命名为 "编号_角色名.png"
  - 脚本会自动备份原 index.html 为 index.html.bak
  - 新角色将按文件顺序插入到 ALL_CHARS、STATS_MAP 最头部
"""

import sys
import os
import json
import re
import shutil


def parse_input_file(filepath):
    """解析输入文件，直接读取你指定的完整编号"""
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


def update_html(html_path, new_chars):
    """更新HTML：新角色按顺序插入到ALL_CHARS、STATS_MAP头部"""
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. 解析 ALL_CHARS 数组
    all_chars_match = re.search(r"const ALL_CHARS\s*=\s*(\[.*?\]);", html, re.DOTALL)
    if not all_chars_match:
        print("错误: 无法找到 ALL_CHARS 定义")
        return False
    try:
        all_chars = json.loads(all_chars_match.group(1))
    except json.JSONDecodeError:
        print("错误: ALL_CHARS JSON 解析失败")
        return False

    # 2. 按你文件的顺序，插入到 ALL_CHARS 头部
    added = 0
    # 逆序遍历保证最终顺序和你文件一致
    for char in reversed(new_chars):
        # 跳过重名角色
        if any(c["name"] == char["name"] for c in all_chars):
            print(f"  跳过已存在的角色: {char['name']}")
            continue
        # 直接使用你提供的编号生成图片路径
        new_entry = {
            "name": char["name"],
            "rarity": char["rarity"],
            "art": f"art/{char['id']}_{char['name']}.png",
            "avatar": f"images/{char['id']}_{char['name']}.png",
        }
        all_chars.insert(0, new_entry)  # 插入头部
        added += 1
        print(f"  添加: {char['name']} ({char['rarity']}, 编号{char['id']})")

    if added == 0:
        print("没有新角色需要添加")
        return False

    # 回写 ALL_CHARS
    new_all_chars_json = json.dumps(all_chars, ensure_ascii=False)
    html = (
        html[: all_chars_match.start()]
        + f"const ALL_CHARS = {new_all_chars_json};"
        + html[all_chars_match.end():]
    )

    # 3. 更新 STATS_MAP：新数据放在头部
    stats_map_match = re.search(r"const STATS_MAP\s*=\s*\{.*?\};", html, re.DOTALL)
    if not stats_map_match:
        print("错误: 无法找到 STATS_MAP 定义")
        return False

    # 解析原有数据
    stats_map_str = (
        stats_map_match.group(0).replace("const STATS_MAP =", "").rstrip(";")
    )
    try:
        stats_map = json.loads(stats_map_str.replace("'", '"'))
    except json.JSONDecodeError:
        stats_map = {}

    # 新角色统计数据（放头部）
    new_stats = []
    for char in new_chars:
        if char["name"] in stats_map:
            print(f"  跳过已存在的五围数据: {char['name']}")
            continue
        v_str = ",".join(map(str, char["stats"]))
        best_str = '","'.join(compute_specialty(char["stats"]))
        new_stats.append(f'"{char["name"]}":{{"v":[{v_str}],"best":["{best_str}"]}}')

    # 原有统计数据（放尾部）
    old_stats = []
    for name, data in stats_map.items():
        v_str = ",".join(map(str, data["v"]))
        best_str = '","'.join(data["best"])
        old_stats.append(f'"{name}":{{"v":[{v_str}],"best":["{best_str}"]}}')

    # 合并：新数据在前，旧数据在后
    new_stats_map = f"const STATS_MAP = {{ {','.join(new_stats + old_stats)} }};"
    html = (
        html[: stats_map_match.start()] + new_stats_map + html[stats_map_match.end():]
    )

    # 写入文件
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 提示文件放置
    print(f"\n成功添加 {added} 个新角色！")
    print("请放入对应图片文件：")
    for char in new_chars:
        if char["name"] not in stats_map:
            print(f"  images/{char['id']}_{char['name']}.png")
            print(f"  art/{char['id']}_{char['name']}.png")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    html_file = sys.argv[1]
    input_file = sys.argv[2]

    # 校验文件
    if not os.path.exists(input_file):
        print(f"错误：输入文件不存在 {input_file}")
        sys.exit(1)
    if not os.path.exists(html_file):
        print(f"错误：HTML文件不存在 {html_file}")
        sys.exit(1)

    # 备份
    bak_path = html_file + ".bak"
    if not os.path.exists(bak_path):
        shutil.copy2(html_file, bak_path)
        print(f"已备份：{bak_path}")

    # 执行
    print(f"\n解析文件：{input_file}")
    new_chars = parse_input_file(input_file)
    if not new_chars:
        print("无有效角色数据")
        sys.exit(1)
    print(f"找到 {len(new_chars)} 个角色")

    print(f"\n更新HTML：{html_file}")
    if update_html(html_file, new_chars):
        print("\n完成！新角色已插入列表头部~")
    else:
        print("\n未修改任何内容")
