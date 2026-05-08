import os, random
import asyncio
import aiohttp
import hashlib
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance, ImageFilter

CONFIG = {
    "IMG_SIZE": (858, 932),
    "CACHE_DIR": "../.cache/pfps", 
    "MAX_CACHE_FILES": 100,
    "TEMPLATE": "library/templates/leaderboard.webp",
    "UNKNOWN_PFP": "./templates/unknownPfp.webp",
    "PODIUMS": {
        1: {"cx": 430, "cy": 227, "r": 68, "name_y": 361, "time_y": 386, "color": "#FFD700", "time_color": "#FFEC8B"},
        2: {"cx": 213, "cy": 223, "r": 57, "name_y": 358, "time_y": 383, "color": "#C0C0C0", "time_color": "#E8E8E8"},
        3: {"cx": 643, "cy": 223, "r": 57, "name_y": 358, "time_y": 383, "color": "#CD7F32", "time_color": "#E3AF66"}
    },
    "LIST_ROWS": {
        "start_y": 439, "height": 52, "width": 52, "step": 65,
        "avatar_x": 37, "name_x": 223, "time_end_x": 774, "CORNER_RADIUS": 12  
    }
}

def cleanup_cache():
    try:
        if not os.path.exists(CONFIG["CACHE_DIR"]): return
        files = [os.path.join(CONFIG["CACHE_DIR"], f) for f in os.listdir(CONFIG["CACHE_DIR"])]
        if len(files) <= CONFIG["MAX_CACHE_FILES"]: return
        files.sort(key=os.path.getatime)
        for i in range(len(files) - CONFIG["MAX_CACHE_FILES"]):
            os.remove(files[i])
    except: pass

async def fetch_avatar(session, url):
    if not url: return None
    os.makedirs(CONFIG["CACHE_DIR"], exist_ok=True)
    url_hash = hashlib.md5(url.encode()).hexdigest()
    path = os.path.join(CONFIG["CACHE_DIR"], f"{url_hash}.img")
    
    if os.path.exists(path):
        os.utime(path, None)
        with open(path, "rb") as f: return f.read()
    
    try:
        async with session.get(url, timeout=5) as r:
            if r.status == 200:
                data = await r.read()
                with open(path, "wb") as f: f.write(data)
                return data
    except: return None

def process_img(data, size, circular=True, radius=0):
    try:
        img = Image.open(BytesIO(data)).convert("RGBA") if data else \
              Image.open(CONFIG["UNKNOWN_PFP"]).convert("RGBA") if os.path.exists(CONFIG["UNKNOWN_PFP"]) else \
              Image.new("RGBA", size, (40, 40, 40, 255))
        
        img = ImageOps.fit(img, size, centering=(0.5, 0.5))
        mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(mask)
        if circular: draw.ellipse((0, 0) + size, fill=255)
        else: draw.rounded_rectangle((0, 0) + size, radius=radius, fill=255)
        
        out = Image.new("RGBA", size, (0, 0, 0, 0))
        out.paste(img, (0, 0), mask=mask)
        return out
    except: 
        return Image.new("RGBA", size, (30, 30, 30, 255))

def add_premium_border(img: Image.Image, style: str = "gold", padding: int = 28) -> Image.Image:
    w, h = img.size
    new_w = w + 2 * padding
    new_h = h + 2 * padding
    
    canvas = Image.new("RGBA", (new_w, new_h), (18, 18, 22, 255))
    canvas.paste(img, (padding, padding), img if img.mode == "RGBA" else None)

    border_layer = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(border_layer)

    
    if style == "silver":
        colors = [
            (120, 125, 140), (170, 175, 190), (215, 220, 235),
            (245, 248, 255), (180, 185, 205), (100, 105, 125)
        ]
        highlight_color = (235, 240, 255)

    elif style == "bronze":
        colors = [
            (35, 18, 8),       
            (55, 28, 12),      
            (85, 42, 20),      
            (125, 60, 32),     
            (170, 85, 48),     
            (100, 48, 22),     
            (40, 20, 10)       
        ]
        highlight_color = (235, 160, 95)   

    elif style == "wood":
        colors = [
            (101, 67, 33), (139, 90, 50), (170, 115, 65),
            (145, 95, 50), (90, 55, 25)
        ]
        highlight_color = (205, 165, 105)
        
    else:  
        colors = [
            (140, 90, 30), (220, 160, 55), (255, 235, 140),
            (255, 215, 90), (200, 135, 45), (120, 75, 25)
        ]
        highlight_color = (255, 248, 200)

    
    max_dist = new_w + new_h
    for i in range(max_dist * 2):
        progress = i / (max_dist * 2)
        idx = int(progress * (len(colors) - 1))
        mix = (progress * (len(colors) - 1)) % 1.0

        c1 = colors[idx]
        c2 = colors[min(idx + 1, len(colors)-1)]
        color = tuple(int(c1[j] + (c2[j] - c1[j]) * mix) for j in range(3))
        alpha = 255 if 0.06 < progress < 0.94 else 195
        
        draw.line([(i, 0), (0, i)], fill=(*color, alpha), width=padding + 6)

    
    hl = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
    hld = ImageDraw.Draw(hl)

    if style == "wood":
        import random
        for i in range(0, max_dist * 2, 3):
            alpha = random.randint(35, 95)
            offset = random.randint(-15, 15)
            hld.line([(i + offset, 0), (0, i + offset)], 
                    fill=(205, 165, 105, alpha), width=2)
    else:
        step = 2 if style == "silver" else 3
        for i in range(-60, max_dist + 60, step):
            progress = (i + 60) / (max_dist + 120)
            intensity = int(155 * max(0, 1 - abs(progress - 0.32)))
            hld.line([(i, 0), (0, i)], fill=(*highlight_color, intensity), width=3)

    border_layer = Image.alpha_composite(border_layer, hl)

    
    mask = Image.new("L", (new_w, new_h), 255)
    mdraw = ImageDraw.Draw(mask)
    mdraw.rounded_rectangle(
        [padding-3, padding-3, new_w-padding+3, new_h-padding+3],
        radius=58, fill=0
    )
    border_layer.putalpha(mask)

    
    final = Image.alpha_composite(canvas, border_layer)
    final = final.convert("RGB")
    final = ImageEnhance.Brightness(final).enhance(0.79)
    final = ImageEnhance.Contrast(final).enhance(1.55)
    final = final.filter(ImageFilter.SHARPEN)
    final = final.filter(ImageFilter.DETAIL)

    return final

async def getNovaLeaderboard(data, border_style: str = "gold"):
    """Orchestrates the image generation using the leaderboard.webp template."""
    try:
        async with aiohttp.ClientSession() as session:
            p_tasks = [fetch_avatar(session, i.get("avatar_url")) for i in data["podium"]]
            r_tasks = [fetch_avatar(session, i.get("avatar_url")) for i in data["rows"]]
            p_res = await asyncio.gather(*p_tasks)
            r_res = await asyncio.gather(*r_tasks)

        
        if not os.path.exists(CONFIG["TEMPLATE"]):
            raise FileNotFoundError(f"Template not found at {CONFIG['TEMPLATE']}")
            
        img = Image.open(CONFIG["TEMPLATE"]).convert("RGBA")
        draw = ImageDraw.Draw(img)

        try:
            f_p_name = ImageFont.truetype('arial.ttf', 20)
            f_p_time = ImageFont.truetype('arial.ttf', 18)
            f_row = ImageFont.truetype('arial.ttf', 24)
            f_rank = ImageFont.truetype('arial.ttf', 28)
        except:
            f_p_name = f_p_time = f_row = f_rank = ImageFont.load_default()

        
        for i, item in enumerate(data["podium"]):
            cfg = CONFIG["PODIUMS"].get(item["rank"])
            if cfg:
                av = process_img(p_res[i], (cfg["r"]*2, cfg["r"]*2), circular=True)
                img.paste(av, (cfg["cx"] - cfg["r"], cfg["cy"] - cfg["r"]), av)
                draw.text((cfg["cx"], cfg["name_y"]), item["name"], fill=cfg["color"], anchor="mm", font=f_p_name)
                draw.text((cfg["cx"], cfg["time_y"]), item["time"], fill=cfg["time_color"], anchor="mm", font=f_p_time)

        
        rc = CONFIG["LIST_ROWS"]
        for i, item in enumerate(data["rows"]):
            curr_y = rc["start_y"] + (i * rc["step"])
            av = process_img(r_res[i], (rc["width"], rc["height"]), False, rc["CORNER_RADIUS"])
            img.paste(av, (rc["avatar_x"], curr_y), av)
            
            mid_y = curr_y + (rc["height"] // 2)
            draw.text((150, mid_y), str(item["rank"]), fill="white", anchor="mm", font=f_rank)
            draw.text((rc["name_x"], mid_y), item["name"], fill="white", anchor="lm", font=f_row)
            draw.text((rc["time_end_x"], mid_y), item["time"], fill="white", anchor="rm", font=f_row)

        
        final_img = add_premium_border(img, style=border_style, padding=28)

        buf = BytesIO()
        final_img.save(buf, "WEBP", quality=95, method=6)
        buf.seek(0)
        
        cleanup_cache()
        return buf

    except Exception as e:
        print(f"[Error] Leaderboard gen failed: {e}")
        return None