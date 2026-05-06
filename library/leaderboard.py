import os
import asyncio
import aiohttp
import hashlib
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps

CONFIG = {
    "IMG_SIZE": (858, 932),
    "CACHE_DIR": "../.cache/pfps", # Generalized pfps cache
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
    except: return Image.new("RGBA", size, (30, 30, 30, 255))

async def getNovaLeaderboard(data):
    """Orchestrates the image generation using the leaderboard.webp template."""
    try:
        async with aiohttp.ClientSession() as session:
            p_tasks = [fetch_avatar(session, i.get("avatar_url")) for i in data["podium"]]
            r_tasks = [fetch_avatar(session, i.get("avatar_url")) for i in data["rows"]]
            p_res = await asyncio.gather(*p_tasks)
            r_res = await asyncio.gather(*r_tasks)

        # Load Background Template
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

        # 1. Podium Placement
        for i, item in enumerate(data["podium"]):
            cfg = CONFIG["PODIUMS"].get(item["rank"])
            if cfg:
                av = process_img(p_res[i], (cfg["r"]*2, cfg["r"]*2), circular=True)
                img.paste(av, (cfg["cx"] - cfg["r"], cfg["cy"] - cfg["r"]), av)
                draw.text((cfg["cx"], cfg["name_y"]), item["name"], fill=cfg["color"], anchor="mm", font=f_p_name)
                draw.text((cfg["cx"], cfg["time_y"]), item["time"], fill=cfg["time_color"], anchor="mm", font=f_p_time)

        # 2. Rows Placement
        rc = CONFIG["LIST_ROWS"]
        for i, item in enumerate(data["rows"]):
            curr_y = rc["start_y"] + (i * rc["step"])
            av = process_img(r_res[i], (rc["width"], rc["height"]), False, rc["CORNER_RADIUS"])
            img.paste(av, (rc["avatar_x"], curr_y), av)
            
            mid_y = curr_y + (rc["height"] // 2)
            draw.text((150, mid_y), str(item["rank"]), fill="white", anchor="mm", font=f_rank)
            draw.text((rc["name_x"], mid_y), item["name"], fill="white", anchor="lm", font=f_row)
            draw.text((rc["time_end_x"], mid_y), item["time"], fill="white", anchor="rm", font=f_row)

        buf = BytesIO()
        img.convert("RGB").save(buf, "WEBP", quality=90)
        buf.seek(0)
        cleanup_cache()
        return buf
    except Exception as e:
        print(f"[Error] Leaderboard gen failed: {e}")
        return None