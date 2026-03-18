#!/usr/bin/env python3
import argparse
from pathlib import Path
import json
import os
import struct
import zlib
from pathlib import Path

import requests
from dotenv import load_dotenv


MENU_NAME = "HomeVault E3 Menu"
MENU_WIDTH = 2500
MENU_HEIGHT = 1686
CELL_COLS = 3
CELL_ROWS = 2
CELL_WIDTH = MENU_WIDTH // CELL_COLS
CELL_HEIGHT = MENU_HEIGHT // CELL_ROWS

BUTTONS = [
    ("COURSE", "e3 course", (13, 110, 253)),
    ("UPCOMING", "e3 近期", (217, 119, 6)),
    ("TIMELINE", "e3 timeline", (37, 99, 235)),
    ("STATUS", "e3 狀態", (22, 163, 74)),
    ("RELOGIN", "e3 relogin", (147, 51, 234)),
    ("HELP", "e3 幫助", (71, 85, 105)),
]

FONT_5X7 = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01110"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
}


def parse_args():
    parser = argparse.ArgumentParser(description="Create and bind LINE rich menu for HomeVault.")
    project_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--env", default=str(project_root / ".env"), help="Path to .env file")
    parser.add_argument("--image", default="", help="Optional PNG image path to upload")
    parser.add_argument("--output-image", default="/tmp/homevault-richmenu.png", help="Generated PNG output path")
    parser.add_argument("--alias", default="homevault-e3", help="Rich menu alias ID")
    return parser.parse_args()


def line_headers(token):
    return {"Authorization": f"Bearer {token}"}


def build_rich_menu_definition(alias_id):
    areas = []
    for idx, (_, command, _) in enumerate(BUTTONS):
        col = idx % CELL_COLS
        row = idx // CELL_COLS
        areas.append(
            {
                "bounds": {
                    "x": col * CELL_WIDTH,
                    "y": row * CELL_HEIGHT,
                    "width": CELL_WIDTH,
                    "height": CELL_HEIGHT,
                },
                "action": {
                    "type": "message",
                    "text": command,
                    "label": command,
                },
            }
        )

    return {
        "size": {"width": MENU_WIDTH, "height": MENU_HEIGHT},
        "selected": True,
        "name": MENU_NAME,
        "chatBarText": "HomeVault",
        "areas": areas,
    }


def set_pixel(pixels, width, x, y, color):
    if 0 <= x < width and 0 <= y < len(pixels) // width:
        pixels[y * width + x] = color


def draw_rect(pixels, width, x, y, w, h, color):
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            set_pixel(pixels, width, xx, yy, color)


def draw_char(pixels, width, x, y, ch, scale, color):
    pattern = FONT_5X7.get(ch, FONT_5X7[" "])
    for row_idx, row in enumerate(pattern):
        for col_idx, bit in enumerate(row):
            if bit != "1":
                continue
            draw_rect(
                pixels,
                width,
                x + col_idx * scale,
                y + row_idx * scale,
                scale,
                scale,
                color,
            )


def draw_text_centered(pixels, width, top_x, top_y, box_width, box_height, text, scale, color):
    text = text.upper()
    char_w = 5 * scale
    gap = scale
    full_width = len(text) * char_w + max(0, len(text) - 1) * gap
    start_x = top_x + max(0, (box_width - full_width) // 2)
    start_y = top_y + max(0, (box_height - 7 * scale) // 2)
    cursor_x = start_x
    for ch in text:
        draw_char(pixels, width, cursor_x, start_y, ch, scale, color)
        cursor_x += char_w + gap


def png_chunk(chunk_type, data):
    return (
        struct.pack("!I", len(data))
        + chunk_type
        + data
        + struct.pack("!I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def write_png(path, width, height, pixels):
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            r, g, b = pixels[y * width + x]
            raw.extend([r, g, b])

    ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    compressed = zlib.compress(bytes(raw), level=9)
    png = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", compressed) + png_chunk(b"IEND", b"")
    Path(path).write_bytes(png)


def generate_default_image(output_path):
    pixels = [(245, 247, 250)] * (MENU_WIDTH * MENU_HEIGHT)
    for idx, (label, _, color) in enumerate(BUTTONS):
        col = idx % CELL_COLS
        row = idx // CELL_COLS
        x = col * CELL_WIDTH
        y = row * CELL_HEIGHT
        draw_rect(pixels, MENU_WIDTH, x, y, CELL_WIDTH - 6, CELL_HEIGHT - 6, color)
        draw_text_centered(pixels, MENU_WIDTH, x, y, CELL_WIDTH - 6, CELL_HEIGHT - 6, label, 18, (255, 255, 255))
    write_png(output_path, MENU_WIDTH, MENU_HEIGHT, pixels)
    return output_path


def request_json(method, url, token, **kwargs):
    headers = kwargs.pop("headers", {})
    merged_headers = line_headers(token)
    merged_headers.update(headers)
    response = requests.request(method, url, headers=merged_headers, timeout=20, **kwargs)
    response.raise_for_status()
    if response.content:
        return response.json()
    return {}


def list_rich_menus(token):
    data = request_json("GET", "https://api.line.me/v2/bot/richmenu/list", token)
    return data.get("richmenus", [])


def delete_existing_named_menus(token, name):
    for item in list_rich_menus(token):
        if item.get("name") == name:
            request_json("DELETE", f"https://api.line.me/v2/bot/richmenu/{item['richMenuId']}", token)


def create_rich_menu(token, definition):
    data = request_json("POST", "https://api.line.me/v2/bot/richmenu", token, json=definition)
    return data["richMenuId"]


def upload_rich_menu_image(token, rich_menu_id, image_path):
    with open(image_path, "rb") as handle:
        response = requests.post(
            f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
            headers={
                **line_headers(token),
                "Content-Type": "image/png",
            },
            data=handle.read(),
            timeout=30,
        )
    response.raise_for_status()


def create_alias(token, alias_id, rich_menu_id):
    request_json(
        "POST",
        "https://api.line.me/v2/bot/richmenu/alias",
        token,
        json={"richMenuAliasId": alias_id, "richMenuId": rich_menu_id},
    )


def set_default_rich_menu(token, rich_menu_id):
    request_json("POST", f"https://api.line.me/v2/bot/user/all/richmenu/{rich_menu_id}", token)


def main():
    args = parse_args()
    load_dotenv(args.env)
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    if not token:
        raise SystemExit("Missing LINE_CHANNEL_ACCESS_TOKEN")

    image_path = args.image or generate_default_image(args.output_image)
    delete_existing_named_menus(token, MENU_NAME)
    definition = build_rich_menu_definition(args.alias)
    rich_menu_id = create_rich_menu(token, definition)
    upload_rich_menu_image(token, rich_menu_id, image_path)
    try:
        create_alias(token, args.alias, rich_menu_id)
    except requests.HTTPError:
        pass
    set_default_rich_menu(token, rich_menu_id)
    print(json.dumps({"richMenuId": rich_menu_id, "image": image_path}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
