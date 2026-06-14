#!/usr/bin/env python3
"""
generate_icon.py — 自动生成 .ico 图标（法律天平主题）
运行一次即可，生成 app_icon.ico
"""
from PIL import Image, ImageDraw, ImageFont
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "app_icon.ico")

def create_icon():
    """创建一个法律天平主题的多尺寸图标"""
    sizes = [16, 32, 48, 64, 128, 256]
    images = []

    for size in sizes:
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 背景圆形（深蓝色）
        margin = max(1, size // 16)
        circle_bbox = [margin, margin, size - margin, size - margin]
        draw.ellipse(circle_bbox, fill=(15, 44, 92, 255))  # #0F2C5C

        # 中间金色天平 ⚖️ 符号
        if size >= 32:
            try:
                font_size = int(size * 0.55)
                # 尝试使用系统字体
                font = None
                for font_name in ['Segoe UI Symbol', 'Segoe UI Emoji', 'Arial Unicode MS', 'Microsoft YaHei']:
                    try:
                        font = ImageFont.truetype(font_name + '.ttf', font_size)
                        break
                    except (OSError, IOError):
                        try:
                            font = ImageFont.truetype(font_name, font_size)
                            break
                        except (OSError, IOError):
                            continue

                if font is None:
                    font = ImageFont.load_default()

                bbox = draw.textbbox((0, 0), '⚖', font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                x = (size - text_w) // 2
                y = (size - text_h) // 2
                draw.text((x, y), '⚖', fill=(230, 184, 0, 255), font=font)
            except Exception:
                # 回退：画简化的金色天平图案
                center_x = size // 2
                # 横梁
                draw.rectangle([size//4, size//3, 3*size//4, size//3 + max(1, size//20)],
                              fill=(230, 184, 0, 255))
                # 竖杆
                draw.rectangle([center_x - max(1, size//20), size//3,
                               center_x + max(1, size//20), 3*size//4],
                              fill=(230, 184, 0, 255))
                # 底座
                draw.rectangle([size//4, 3*size//4 - max(1, size//16),
                               3*size//4, 3*size//4],
                              fill=(230, 184, 0, 255))
                # 左盘
                draw.ellipse([size//8, size//6, size//3, size//3],
                            outline=(230, 184, 0, 255), width=max(1, size//30))
                # 右盘
                draw.ellipse([2*size//3, size//6, 7*size//8, size//3],
                            outline=(230, 184, 0, 255), width=max(1, size//30))

        images.append(img)

    # 保存为 .ico
    images[0].save(
        OUTPUT_PATH,
        format='ICO',
        sizes=[(s, s) for s in sizes],
        append_images=images[1:]
    )
    print(f"[OK] 图标已生成: {OUTPUT_PATH}")

if __name__ == "__main__":
    create_icon()
