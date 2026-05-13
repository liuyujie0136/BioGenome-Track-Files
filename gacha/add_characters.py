#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jiangnan Gacha Simulator - Add new characters (with auto image download)
使用方法:
  python add_characters.py <index.html路径> <新角色数据文件.txt> [输出目录]
数据文件格式 (制表符或空格分隔):
  编号  稀有度  角色名  建造  农牧  制作  理财  探险
示例:
  A01  天  新角色A  600  400  780  300  500
  A02  侯  新角色B  300  500  200  600  400
  B01  卿  新角色C  400  300  500  700  200
注意:
  - 编号由你手动指定（如A01、B02），脚本不做任何修改
  - 脚本会自动从bilibili wiki抓取头像和立绘，按"编号_角色名.png"命名
  - 头像保存到 NEW/image/ 目录（90x90像素）
  - 立绘保存到 NEW/art/ 目录（宽度400像素，等比缩放）
  - 可通过第三个参数指定输出目录（默认为脚本所在目录下的 NEW/）
  - 脚本会自动备份原 index.html 为 index.html.bak
  - 新角色将按文件顺序插入到 ALL_CHARS、STATS_MAP 最头部
依赖:
  pip install requests Pillow beautifulsoup4 lxml
"""

import sys
import os
import json
import re
import shutil
import time
import urllib.parse

import requests
from PIL import Image
from io import BytesIO


# ============================================================
#  常量
# ============================================================
WIKI_API = "https://wiki.biligame.com/jiangnan/api.php"
WIKI_BASE = "https://wiki.biligame.com/jiangnan/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": WIKI_BASE,
}

# 图片目标尺寸
AVATAR_SIZE = (90, 90)  # 头像：90x90
ART_WIDTH = 400  # 立绘：宽度400，高度等比缩放

# 请求间隔（秒），避免被wiki封禁
REQUEST_DELAY = 10.0


# ============================================================
#  输入解析
# ============================================================
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


# ============================================================
#  五围擅长计算
# ============================================================
def compute_specialty(stats):
    """根据五围数据计算擅长"""
    labels = ["建造", "农牧", "制作", "理财", "探险"]
    max_v = max(stats)
    best = [labels[i] for i, v in enumerate(stats) if v == max_v]
    return best


# ============================================================
#  从 bilibili wiki 抓取图片 URL（MediaWiki API）
# ============================================================
def fetch_image_urls_from_api(char_name):
    """
    通过 MediaWiki API 查询角色的头像和立绘图片URL。
    文件命名规则：头像_角色名.png / 立绘_角色名.png
    返回: {"avatar": url_or_None, "art": url_or_None}
    """
    result = {"avatar": None, "art": None}
    # MediaWiki 会自动将下划线转为空格，所以用下划线传入
    file_titles = f"File:头像_{char_name}.png|File:立绘_{char_name}.png"
    params = {
        "action": "query",
        "titles": file_titles,
        "prop": "imageinfo",
        "iiprop": "url",
        "format": "json",
    }
    try:
        resp = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for page_id, page_info in pages.items():
            if "imageinfo" not in page_info:
                continue
            title = page_info.get("title", "")
            url = page_info["imageinfo"][0]["url"]
            if "头像" in title:
                result["avatar"] = url
            elif "立绘" in title:
                result["art"] = url
    except Exception as e:
        print(f"    API查询失败 ({char_name}): {e}")
    return result


def fetch_image_urls_from_page(char_name):
    """
    备用方案：直接抓取角色wiki页面HTML，从页面中提取头像和立绘URL。
    适用于API查询不到的情况（如文件名不标准）。
    """
    result = {"avatar": None, "art": None}
    page_url = WIKI_BASE + urllib.parse.quote(char_name)
    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # 提取立绘：alt="立绘 角色名.png"
        lihui_pattern = (
            r'<img[^>]+alt="立绘\s+' + re.escape(char_name) + r'\.png"'
            r'[^>]+src="([^"]+)"'
        )
        m = re.search(lihui_pattern, html)
        if m:
            thumb_url = m.group(1)
            # 将缩略图URL转为原图URL
            # /thumb/a/ab/hash/200px-立绘_角色名.png -> /a/ab/hash.png
            full_url = re.sub(
                r"/thumb/((?:[^/]+/){2}[^/]+)/\d+px-[^/]+$",
                r"/\1",
                thumb_url,
            )
            if full_url != thumb_url:
                result["art"] = full_url
            else:
                result["art"] = thumb_url

        # 提取头像：alt="头像 角色名.png"
        avatar_pattern = (
            r'<img[^>]+alt="头像\s+' + re.escape(char_name) + r'\.png"'
            r'[^>]+src="([^"]+)"'
        )
        m = re.search(avatar_pattern, html)
        if m:
            thumb_url = m.group(1)
            # 头像使用90px缩略图即可（与现有头像尺寸一致）
            # 如果URL是缩略图，尝试获取90px版本
            if "/thumb/" in thumb_url:
                # 替换尺寸前缀为90px
                url_90 = re.sub(
                    r"/thumb/((?:[^/]+/){2}[^/]+)/\d+px-",
                    r"/thumb/\1/90px-",
                    thumb_url,
                )
                result["avatar"] = url_90
            else:
                result["avatar"] = thumb_url

    except Exception as e:
        print(f"    页面抓取失败 ({char_name}): {e}")
    return result


def fetch_image_urls(char_name, json_cache=None):
    """
    获取角色的头像和立绘URL。
    优先级：本地JSON缓存 > MediaWiki API > 页面HTML抓取
    """
    # 1. 尝试从本地JSON缓存获取
    if json_cache and char_name in json_cache:
        entry = json_cache[char_name]
        return {"avatar": entry.get("avatar"), "art": entry.get("art")}

    # 2. 尝试 MediaWiki API
    result = fetch_image_urls_from_api(char_name)
    if result["avatar"] and result["art"]:
        return result

    # 3. API未完全获取，尝试页面抓取补充
    page_result = fetch_image_urls_from_page(char_name)
    if not result["avatar"]:
        result["avatar"] = page_result["avatar"]
    if not result["art"]:
        result["art"] = page_result["art"]

    return result


# ============================================================
#  图片下载与处理
# ============================================================
def download_image(url):
    """下载图片，返回 PIL Image 对象；失败返回 None"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
        return img
    except Exception as e:
        print(f"    下载失败 ({url[:80]}...): {e}")
        return None


def resize_avatar(img):
    """将头像调整为 90x90 像素（RGBA）"""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return img.resize(AVATAR_SIZE, Image.LANCZOS)


def resize_art(img):
    """将立绘调整为宽度400像素，高度等比缩放（RGBA）"""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    w, h = img.size
    if w == ART_WIDTH:
        return img
    ratio = ART_WIDTH / w
    new_h = int(h * ratio)
    return img.resize((ART_WIDTH, new_h), Image.LANCZOS)


def fetch_and_save_images(new_chars, output_base):
    """
    为所有新角色抓取头像和立绘，保存到指定目录。
    <output_base>/
      image/   <- 头像 (编号_角色名.png)
      art/     <- 立绘 (编号_角色名.png)
    返回: 成功保存的角色列表
    """
    # 创建输出目录
    avatar_dir = os.path.join(output_base, "image")
    art_dir = os.path.join(output_base, "art")
    os.makedirs(avatar_dir, exist_ok=True)
    os.makedirs(art_dir, exist_ok=True)

    # 尝试加载本地JSON缓存
    json_cache = {}
    json_paths = [
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "chars_with_art_v2.json"
        ),
        os.path.join(output_base, "..", "chars_with_art_v2.json"),
    ]
    for jp in json_paths:
        if os.path.exists(jp):
            try:
                with open(jp, "r", encoding="utf-8") as f:
                    cache_list = json.load(f)
                json_cache = {c["name"]: c for c in cache_list}
                print(f"  已加载本地缓存: {jp} ({len(json_cache)} 个角色)")
                break
            except Exception:
                pass

    success_chars = []
    for i, char in enumerate(new_chars):
        name = char["name"]
        char_id = char["id"]
        filename = f"{char_id}_{name}.png"
        avatar_path = os.path.join(avatar_dir, filename)
        art_path = os.path.join(art_dir, filename)

        print(f"\n  [{i+1}/{len(new_chars)}] {name} (编号{char_id})")

        # 获取图片URL
        urls = fetch_image_urls(name, json_cache)

        # 下载并保存头像
        if urls["avatar"]:
            print(f"    头像URL: {urls['avatar'][:80]}...")
            img = download_image(urls["avatar"])
            if img:
                avatar_img = resize_avatar(img)
                avatar_img.save(avatar_path, "PNG")
                print(f"    头像已保存: {avatar_path}")
            else:
                print(f"    头像下载失败，需手动放置: {avatar_path}")
        else:
            print(f"    未找到头像URL，需手动放置: {avatar_path}")

        # 下载并保存立绘
        if urls["art"]:
            print(f"    立绘URL: {urls['art'][:80]}...")
            img = download_image(urls["art"])
            if img:
                art_img = resize_art(img)
                art_img.save(art_path, "PNG")
                print(f"    立绘已保存: {art_path}")
            else:
                print(f"    立绘下载失败，需手动放置: {art_path}")
        else:
            print(f"    未找到立绘URL，需手动放置: {art_path}")

        # 检查是否至少有一个图片成功
        avatar_ok = os.path.exists(avatar_path)
        art_ok = os.path.exists(art_path)
        if avatar_ok or art_ok:
            success_chars.append(char)
            if not avatar_ok or not art_ok:
                missing = []
                if not avatar_ok:
                    missing.append("头像")
                if not art_ok:
                    missing.append("立绘")
                print(f"    注意: {name} 缺少 {'、'.join(missing)}，请手动补充")
        else:
            print(f"    警告: {name} 头像和立绘均未获取成功")

        # 请求间隔，避免被封
        if i < len(new_chars) - 1:
            time.sleep(REQUEST_DELAY)

    return success_chars


# ============================================================
#  HTML 更新
# ============================================================
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

    print(f"\n成功添加 {added} 个新角色！")
    return True


# ============================================================
#  主流程
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    html_file = sys.argv[1]
    input_file = sys.argv[2]

    # 输出目录（可选参数，默认为脚本所在目录下的 NEW/）
    if len(sys.argv) >= 4:
        output_dir = sys.argv[3]
    else:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "NEW/")

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

    # 解析输入文件
    print(f"\n解析文件：{input_file}")
    new_chars = parse_input_file(input_file)
    if not new_chars:
        print("无有效角色数据")
        sys.exit(1)
    print(f"找到 {len(new_chars)} 个角色")

    # 抓取并保存图片
    print("\n=== 从Bilibili Wiki抓取图片 ===")
    print(f"输出目录: {output_dir}")
    success_chars = fetch_and_save_images(new_chars, output_dir)

    # 更新HTML
    print("\n=== 更新HTML ===")
    print(f"更新HTML：{html_file}")
    if update_html(html_file, new_chars):
        # 提示需要手动复制的文件
        avatar_dir = os.path.join(output_dir, "image")
        art_dir = os.path.join(output_dir, "art")
        print("\n图片已保存到：")
        print(f"  头像目录: {avatar_dir}")
        print(f"  立绘目录: {art_dir}")
        print("\n请将图片复制到index.html对应目录：")
        for char in new_chars:
            filename = f"{char['id']}_{char['name']}.png"
            print(f"  {avatar_dir}/{filename} -> images/{filename}")
            print(f"  {art_dir}/{filename} -> art/{filename}")
        print("\n完成！新角色已插入列表头部~")
    else:
        print("\n未修改任何内容")
