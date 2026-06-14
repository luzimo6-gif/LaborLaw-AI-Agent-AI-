#!/usr/bin/env python3
"""
generate_icon.py — 纯标准库生成 .ico 图标（法律天平主题）
无需任何第三方依赖，兼容 PyInstaller 打包环境
"""
import struct
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "app_icon.ico")


def create_bitmap_rgba(width, height, pixels):
    """
    创建 32-bit RGBA BMP 字节数据（用于 ICO）
    pixels: 二维列表 [y][x] = (R, G, B, A)
    """
    # BMP 行是 4 字节对齐的，从下往上存储
    row_size = width * 4
    data_size = row_size * height

    # BITMAPINFOHEADER (40 bytes)
    header_size = 40
    file_size = 14 + header_size + data_size

    bmp = bytearray()
    # BITMAPFILEHEADER (14 bytes)
    bmp += b'BM'
    bmp += struct.pack('<I', file_size)
    bmp += struct.pack('<HH', 0, 0)
    bmp += struct.pack('<I', 14 + header_size)

    # BITMAPINFOHEADER (40 bytes)
    bmp += struct.pack('<I', header_size)
    bmp += struct.pack('<i', width)
    bmp += struct.pack('<i', height * 2)  # ICO 需要双倍高度（包含 AND mask）
    bmp += struct.pack('<H', 1)
    bmp += struct.pack('<H', 32)
    bmp += struct.pack('<I', 0)  # BI_RGB
    bmp += struct.pack('<I', data_size)
    bmp += struct.pack('<i', 0)  # 水平分辨率
    bmp += struct.pack('<i', 0)  # 垂直分辨率
    bmp += struct.pack('<I', 0)
    bmp += struct.pack('<I', 0)

    # 像素数据（从下往上）
    for y in range(height - 1, -1, -1):
        for x in range(width):
            r, g, b, a = pixels[y][x]
            bmp += bytes([b, g, r, a])

    # AND mask（全0表示完全透明，全1表示不透明）
    # ICO 中 AND mask 在 XOR mask 之后，每行 4 字节对齐
    mask_row_size = ((width + 31) // 32) * 4
    for _ in range(height):
        bmp += b'\x00' * mask_row_size

    return bytes(bmp)


def draw_icon(size):
    """绘制法律天平图标，返回像素数据"""
    # 初始化透明背景
    pixels = [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]

    margin = max(1, size // 16)
    cx, cy = size // 2, size // 2

    # ── 深蓝色圆形背景 ──
    bg_color = (15, 44, 92, 255)  # #0F2C5C
    for y in range(size):
        for x in range(size):
            dx = x - cx
            dy = y - cy
            r = (size - 2 * margin) // 2
            if dx * dx + dy * dy <= r * r:
                # 抗锯齿边缘
                dist = (dx * dx + dy * dy) ** 0.5
                if dist <= r - 1:
                    pixels[y][x] = bg_color
                elif dist <= r:
                    alpha = int(255 * (r - dist))
                    pixels[y][x] = (15, 44, 92, alpha)

    # ── 金色天平图案 ──
    gold = (230, 184, 0, 255)  # 金色
    line_w = max(1, size // 20)

    # 竖杆（中心柱）
    pillar_left = cx - line_w
    pillar_right = cx + line_w
    pillar_top = int(size * 0.30)
    pillar_bottom = int(size * 0.78)
    for y in range(pillar_top, pillar_bottom):
        for x in range(pillar_left, pillar_right + 1):
            if 0 <= x < size and 0 <= y < size:
                pixels[y][x] = gold

    # 横梁
    beam_top = pillar_top
    beam_bottom = pillar_top + line_w
    beam_left = int(size * 0.18)
    beam_right = int(size * 0.82)
    for y in range(beam_top, beam_bottom):
        for x in range(beam_left, beam_right + 1):
            if 0 <= x < size and 0 <= y < size:
                pixels[y][x] = gold

    # 底座
    base_top = pillar_bottom
    base_bottom = pillar_bottom + line_w * 2
    base_left = int(size * 0.25)
    base_right = int(size * 0.75)
    for y in range(base_top, base_bottom):
        for x in range(base_left, base_right + 1):
            if 0 <= x < size and 0 <= y < size:
                pixels[y][x] = gold

    # 左托盘
    left_cx = beam_left
    left_cy = beam_top - line_w
    plate_r = int(size * 0.08)
    for y in range(size):
        for x in range(size):
            dx = x - left_cx
            dy = y - left_cy
            if dx * dx + dy * dy <= plate_r * plate_r:
                if pixels[y][x][3] == 0 or (dx * dx + dy * dy) < (plate_r - 1) ** 2:
                    pixels[y][x] = gold

    # 右托盘
    right_cx = beam_right
    right_cy = beam_top - line_w
    for y in range(size):
        for x in range(size):
            dx = x - right_cx
            dy = y - right_cy
            if dx * dx + dy * dy <= plate_r * plate_r:
                if pixels[y][x][3] == 0 or (dx * dx + dy * dy) < (plate_r - 1) ** 2:
                    pixels[y][x] = gold

    # 左连接线（托盘到横梁）
    for y_offset in range(-plate_r, 0):
        yy = left_cy + y_offset
        if 0 <= yy < size:
            for x in range(left_cx - line_w, left_cx + line_w + 1):
                if 0 <= x < size:
                    pixels[yy][x] = gold

    # 右连接线
    for y_offset in range(-plate_r, 0):
        yy = right_cy + y_offset
        if 0 <= yy < size:
            for x in range(right_cx - line_w, right_cx + line_w + 1):
                if 0 <= x < size:
                    pixels[yy][x] = gold

    return pixels


def create_icon():
    """创建多尺寸 ICO 文件"""
    sizes = [16, 32, 48, 64, 128, 256]

    # 生成各尺寸的图像数据
    icon_data_list = []
    for size in sizes:
        pixels = draw_icon(size)
        bmp_data = create_bitmap_rgba(size, size, pixels)
        icon_data_list.append((size, bmp_data))

    # 写入 ICO 文件
    with open(OUTPUT_PATH, 'wb') as f:
        # ICONDIR (6 bytes)
        f.write(struct.pack('<HHH', 0, 1, len(sizes)))

        # ICONDIRENTRY 数组
        offset = 6 + 16 * len(sizes)
        for size, data in icon_data_list:
            data_size = len(data)
            # ICO 格式：256 像素表示为 0
            w = size if size < 256 else 0
            h = size if size < 256 else 0
            f.write(struct.pack('<BBBBHHII',
                w,               # width (0 = 256)
                h,               # height (0 = 256)
                0,               # color palette count
                0,               # reserved
                1,               # color planes
                32,              # bits per pixel
                data_size,       # data size
                offset           # offset to data
            ))
            offset += data_size

        # 图像数据
        for _, data in icon_data_list:
            f.write(data)

    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"[OK] 图标已生成: {OUTPUT_PATH} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    create_icon()
