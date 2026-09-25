import os
import glob
import json
import subprocess
import shutil
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 2052, 1340
windir = os.environ.get('WINDIR', r'C:\Windows')
work_dir = r"d:\voicespirit\output_showcase"
os.makedirs(work_dir, exist_ok=True)

logo_path = r"d:\voicespirit\resources\icons\logo.png"
src_video = r"C:\Users\WINDOWS\Videos\屏幕录制\屏幕录制 2026-09-17 150016.mp4"
final_output = os.path.join(work_dir, "Echo_2026-09-17_Showcase_Master.mp4")
desktop_output = r"C:\Users\WINDOWS\Desktop\Echo_2026-09-17_双语精修演示.mp4"
videos_output = r"C:\Users\WINDOWS\Videos\Echo_2026-09-17_双语精修演示.mp4"

# -------------------------------------------------------------
# 1. Generate High-Res Intro Card and Outro Card (NO GITHUB LINK)
# -------------------------------------------------------------
def generate_brand_cards():
    print("1. Generating Intro and Outro Cards (Strictly No External Links)...")
    font_title = ImageFont.truetype(os.path.join(windir, 'Fonts', 'msyhbd.ttc'), 76)
    font_slogan = ImageFont.truetype(os.path.join(windir, 'Fonts', 'msyhbd.ttc'), 38)
    font_sub = ImageFont.truetype(os.path.join(windir, 'Fonts', 'msyh.ttc'), 32)
    font_badge = ImageFont.truetype(os.path.join(windir, 'Fonts', 'msyhbd.ttc'), 28)

    logo_raw = Image.open(logo_path).convert('RGBA')
    logo_220 = logo_raw.resize((220, 220), Image.Resampling.LANCZOS)
    cx, cy = W // 2, 420

    # Intro Card
    kite_path = r'd:\voicespirit\ChatGPT Image Sep 17, 2026, 03_33_41 PM.png'
    bg_kite = Image.open(kite_path).convert('RGBA').resize((W, H), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(35))
    darken = Image.new('RGBA', (W, H), (10, 16, 14, 215))
    img_intro = Image.alpha_composite(bg_kite, darken)

    glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow)
    for r in range(500, 0, -10):
        alpha = int(35 * (1.0 - r / 500.0))
        g_draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(80, 160, 130, alpha))
    img_intro = Image.alpha_composite(img_intro, glow)

    s_logo = Image.new('RGBA', (280, 280), (0, 0, 0, 0))
    sd_logo = ImageDraw.Draw(s_logo)
    sd_logo.rounded_rectangle([20, 20, 260, 260], radius=56, fill=(0, 0, 0, 180))
    s_logo = s_logo.filter(ImageFilter.GaussianBlur(22))
    img_intro.paste(s_logo, (cx - 140, cy - 130), s_logo)
    img_intro.paste(logo_220, (cx - 110, cy - 110), logo_220)

    draw = ImageDraw.Draw(img_intro)
    title_text = 'E C H O  ·  回 声'
    bbox = draw.textbbox((0, 0), title_text, font=font_title)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, cy + 145), title_text, fill=(245, 250, 248, 255), font=font_title)

    slogan_text = '全模态实时语音通话  ×  Live Canvas 动态交互渲染'
    bbox = draw.textbbox((0, 0), slogan_text, font=font_slogan)
    sw = bbox[2] - bbox[0]
    draw.text((cx - sw // 2, cy + 250), slogan_text, fill=(255, 225, 85, 255), font=font_slogan)

    sub_text = '本地优先 · 自由可控 · 全能 AI 桌面助手'
    bbox = draw.textbbox((0, 0), sub_text, font=font_sub)
    suw = bbox[2] - bbox[0]
    draw.text((cx - suw // 2, cy + 325), sub_text, fill=(185, 220, 205, 255), font=font_sub)

    badge_text = '● 多模型互联 (Gemini / DashScope / Tavus)   |   ◆ 边聊边画   |   ★ 极速打断'
    bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pill_box = [cx - bw // 2 - 36, cy + 415 - 14, cx + bw // 2 + 36, cy + 415 + bh + 14]
    pill_bg = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    p_draw = ImageDraw.Draw(pill_bg)
    p_draw.rounded_rectangle(pill_box, radius=26, fill=(24, 38, 33, 230), outline=(97, 150, 125, 210), width=2)
    img_intro = Image.alpha_composite(img_intro, pill_bg)

    draw = ImageDraw.Draw(img_intro)
    draw.text((cx - bw // 2, cy + 415), badge_text, fill=(230, 248, 240, 255), font=font_badge)
    intro_png = os.path.join(work_dir, 'intro_card.png')
    img_intro.save(intro_png)

    # Outro Card
    moon_path = r'd:\voicespirit\ChatGPT Image Sep 17, 2026, 03_34_14 PM.png'
    bg_moon = Image.open(moon_path).convert('RGBA').resize((W, H), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(35))
    img_outro = Image.alpha_composite(bg_moon, darken)
    img_outro = Image.alpha_composite(img_outro, glow)
    img_outro.paste(s_logo, (cx - 140, cy - 130), s_logo)
    img_outro.paste(logo_220, (cx - 110, cy - 110), logo_220)

    draw_out = ImageDraw.Draw(img_outro)
    draw_out.text((cx - tw // 2, cy + 145), title_text, fill=(245, 250, 248, 255), font=font_title)
    out_slogan = '让 AI 与你共鸣  ·  让灵感自由飞翔'
    bbox = draw_out.textbbox((0, 0), out_slogan, font=font_slogan)
    ow = bbox[2] - bbox[0]
    draw_out.text((cx - ow // 2, cy + 250), out_slogan, fill=(255, 225, 85, 255), font=font_slogan)
    draw_out.text((cx - suw // 2, cy + 325), sub_text, fill=(185, 220, 205, 255), font=font_sub)

    action_text = '【点赞收藏】    【转发分享】    【关注获取最新实测】'
    bbox = draw_out.textbbox((0, 0), action_text, font=font_badge)
    aw, ah = bbox[2] - bbox[0], bbox[3] - bbox[1]
    action_box = [cx - aw // 2 - 40, cy + 415 - 16, cx + aw // 2 + 40, cy + 415 + ah + 16]
    p_out = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    pd_out = ImageDraw.Draw(p_out)
    pd_out.rounded_rectangle(action_box, radius=28, fill=(28, 48, 40, 240), outline=(110, 180, 145, 220), width=2)
    img_outro = Image.alpha_composite(img_outro, p_out)
    draw_out = ImageDraw.Draw(img_outro)
    draw_out.text((cx - aw // 2, cy + 415), action_text, fill=(255, 255, 255, 255), font=font_badge)
    outro_png = os.path.join(work_dir, 'outro_card.png')
    img_outro.save(outro_png)

    # Render Intro Video (2.0s) and Outro Video (2.2s)
    intro_mp4 = os.path.join(work_dir, "intro.mp4")
    outro_mp4 = os.path.join(work_dir, "outro.mp4")

    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-t", "2.00", "-i", intro_png,
        "-f", "lavfi", "-t", "2.00", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf", f"fps=30,scale={W}:{H},format=yuv420p",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-t", "2.00", intro_mp4
    ], check=True, capture_output=True)

    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-t", "2.20", "-i", outro_png,
        "-f", "lavfi", "-t", "2.20", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf", f"fps=30,scale={W}:{H},format=yuv420p",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-t", "2.20", outro_mp4
    ], check=True, capture_output=True)

    return intro_mp4, outro_mp4

# -------------------------------------------------------------
# 2. Generate HUD Pills & 4 Promotional Poster Cards
# -------------------------------------------------------------
def generate_overlays():
    print("2. Generating HUD Pills and 4 GPT Promotional Poster Cards...")
    font_cn_bold = ImageFont.truetype(os.path.join(windir, 'Fonts', 'msyhbd.ttc'), 18)
    logo_raw = Image.open(logo_path).convert('RGBA')
    logo_30 = logo_raw.resize((30, 30), Image.Resampling.LANCZOS)

    def create_top_pill(badge_color, tag_text, desc_text, pill_w=1120, pill_h=48):
        img = Image.new('RGBA', (pill_w, pill_h), (0, 0, 0, 0))
        s = Image.new('RGBA', (pill_w, pill_h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(s)
        sd.rounded_rectangle([4, 4, pill_w-4, pill_h-2], radius=24, fill=(0, 0, 0, 140))
        s = s.filter(ImageFilter.GaussianBlur(6))
        img.paste(s, (0, 2), s)
        
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([2, 2, pill_w-2, pill_h-2], radius=24, fill=(18, 26, 23, 245), outline=(97, 142, 120, 200), width=1)
        img.paste(logo_30, (16, 9), logo_30)
        draw.text((56, 12), 'Echo · 回声', fill=(255, 255, 255, 255), font=font_cn_bold)
        draw.line([(175, 12), (175, 36)], fill=(75, 110, 95, 220), width=1)
        
        draw.rounded_rectangle([190, 10, 190 + 130, 38], radius=14, fill=(35, 52, 45, 240), outline=badge_color, width=1)
        bbox = draw.textbbox((0, 0), tag_text, font=font_cn_bold)
        tw = bbox[2] - bbox[0]
        draw.text((190 + (130 - tw)//2, 12), tag_text, fill=badge_color, font=font_cn_bold)
        
        draw.line([(335, 12), (335, 36)], fill=(75, 110, 95, 220), width=1)
        draw.text((350, 12), desc_text, fill=(235, 245, 240, 255), font=font_cn_bold)
        return img

    pills = {
        'pill_dota.png': ((251, 191, 36, 255), 'DOTA 2 彩蛋', 'Echo Slam「回音击」· 让 AI 回应每一次呼唤'),
        'pill_models.png': ((56, 189, 248, 255), '多模型互联', 'DashScope · Gemini · Tavus 虚拟人面对面'),
        'pill_canvas.png': ((192, 132, 252, 255), 'LIVE CANVAS', '边聊边写代码 · 交互式动态组件即时渲染'),
        'pill_voice.png': ((74, 222, 128, 255), '实时语音通话', 'Gemini 3.8 Live · 毫秒级全双工自然对话'),
        'pill_render.png': ((244, 114, 182, 255), '动态插画渲染', '振翅夜光帝王蝶 · 实时代码与动画生成演示')
    }
    pill_paths = {}
    for name, (color, tag, desc) in pills.items():
        p = create_top_pill(color, tag, desc)
        p_path = os.path.join(work_dir, name)
        p.save(p_path)
        pill_paths[name] = p_path

    # Generate 4 Promotional Cards
    imgs = [
        ('card_kite.png', r'd:\voicespirit\ChatGPT Image Sep 17, 2026, 03_33_41 PM.png'),
        ('card_boat.png', r'd:\voicespirit\ChatGPT Image Sep 17, 2026, 03_34_02 PM.png'),
        ('card_moon.png', r'd:\voicespirit\ChatGPT Image Sep 17, 2026, 03_34_14 PM.png'),
        ('card_desk.png', r'd:\voicespirit\ChatGPT Image Sep 17, 2026, 03_34_20 PM.png'),
    ]

    pw, ph = 460, 818
    card_w, card_h = pw + 24, ph + 24
    mask = Image.new('L', (pw, ph), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, pw, ph], radius=24, fill=255)

    card_paths = {}
    for out_name, src_path in imgs:
        src = Image.open(src_path).convert('RGBA').resize((pw, ph), Image.Resampling.LANCZOS)
        card = Image.new('RGBA', (card_w, card_h), (0, 0, 0, 0))
        s = Image.new('RGBA', (card_w, card_h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(s)
        sd.rounded_rectangle([12, 12, card_w - 12, card_h - 12], radius=24, fill=(0, 0, 0, 110))
        s = s.filter(ImageFilter.GaussianBlur(16))
        card.paste(s, (0, 0), s)
        
        border = Image.new('RGBA', (card_w, card_h), (0, 0, 0, 0))
        bd = ImageDraw.Draw(border)
        bd.rounded_rectangle([10, 10, card_w - 10, card_h - 10], radius=24, fill=(24, 34, 30, 240), outline=(97, 142, 120, 220), width=2)
        card = Image.alpha_composite(card, border)
        card.paste(src, (12, 12), mask)
        c_path = os.path.join(work_dir, out_name)
        card.save(c_path)
        card_paths[out_name] = c_path

    return pill_paths, card_paths

# -------------------------------------------------------------
# 3. Process Video Clips with Overlays (Part 1 & Part 2)
# -------------------------------------------------------------
def process_video_clips(pill_paths, card_paths):
    print("3. Cutting Video Clips and Applying Overlays (Trimming 12.80s Waiting Period)...")
    part1_mp4 = os.path.join(work_dir, "part1_overlay.mp4")
    part2_mp4 = os.path.join(work_dir, "part2_overlay.mp4")

    pill_x = (W - 1120) // 2
    pill_y = 12
    card_x = 1480
    card_y = 140

    filter_part1 = (
        f"[0:v]fps=30,scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2[base];"
        f"[5:v]format=rgba,fade=t=in:st=8.0:d=0.4:alpha=1,fade=t=out:st=12.1:d=0.4:alpha=1[c1];"
        f"[6:v]format=rgba,fade=t=in:st=12.5:d=0.4:alpha=1,fade=t=out:st=16.6:d=0.4:alpha=1[c2];"
        f"[7:v]format=rgba,fade=t=in:st=17.0:d=0.4:alpha=1,fade=t=out:st=21.1:d=0.4:alpha=1[c3];"
        f"[8:v]format=rgba,fade=t=in:st=21.5:d=0.4:alpha=1,fade=t=out:st=26.0:d=0.5:alpha=1[c4];"
        f"[base][c1]overlay=x={card_x}:y={card_y}:enable='between(t,8.0,12.5)'[v_c1];"
        f"[v_c1][c2]overlay=x={card_x}:y={card_y}:enable='between(t,12.5,17.0)'[v_c2];"
        f"[v_c2][c3]overlay=x={card_x}:y={card_y}:enable='between(t,17.0,21.5)'[v_c3];"
        f"[v_c3][c4]overlay=x={card_x}:y={card_y}:enable='between(t,21.5,26.5)'[v_c4];"
        f"[v_c4][1:v]overlay=x={pill_x}:y={pill_y}:enable='between(t,0,7.0)'[v_p1];"
        f"[v_p1][2:v]overlay=x={pill_x}:y={pill_y}:enable='between(t,7.0,26.5)'[v_p2];"
        f"[v_p2][3:v]overlay=x={pill_x}:y={pill_y}:enable='between(t,26.5,44.0)'[v_p3];"
        f"[v_p3][4:v]overlay=x={pill_x}:y={pill_y}:enable='between(t,44.0,59.6)'[vout]"
    )

    cmd_p1 = [
        "ffmpeg", "-y",
        "-ss", "0.00", "-t", "59.60", "-i", src_video,
        "-loop", "1", "-i", pill_paths['pill_dota.png'],
        "-loop", "1", "-i", pill_paths['pill_models.png'],
        "-loop", "1", "-i", pill_paths['pill_canvas.png'],
        "-loop", "1", "-i", pill_paths['pill_voice.png'],
        "-loop", "1", "-i", card_paths['card_kite.png'],
        "-loop", "1", "-i", card_paths['card_boat.png'],
        "-loop", "1", "-i", card_paths['card_moon.png'],
        "-loop", "1", "-i", card_paths['card_desk.png'],
        "-filter_complex", filter_part1,
        "-map", "[vout]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", "59.60",
        part1_mp4
    ]
    subprocess.run(cmd_p1, check=True)
    print("  Part 1 processed successfully!")

    # Part 2: 72.40s to 95.80s (23.40s)
    filter_part2 = (
        f"[0:v]fps=30,scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2[base];"
        f"[base][1:v]overlay=x={pill_x}:y={pill_y}[vout]"
    )

    cmd_p2 = [
        "ffmpeg", "-y",
        "-ss", "72.40", "-t", "23.40", "-i", src_video,
        "-loop", "1", "-i", pill_paths['pill_render.png'],
        "-filter_complex", filter_part2,
        "-map", "[vout]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", "23.40",
        part2_mp4
    ]
    subprocess.run(cmd_p2, check=True)
    print("  Part 2 processed successfully!")

    return part1_mp4, part2_mp4

# -------------------------------------------------------------
# 4. Assemble Clips: Intro + Part 1 + Part 2 + Outro
# -------------------------------------------------------------
def assemble_clips(intro_mp4, part1_mp4, part2_mp4, outro_mp4):
    print("4. Assembling All Clips with Clean Crossfades...")
    assembled_mp4 = os.path.join(work_dir, "assembled_clean.mp4")

    filter_assemble = (
        "[0:v][1:v]xfade=transition=fade:duration=0.3:offset=1.70[v01];"
        "[0:a][1:a]acrossfade=d=0.3:c1=tri:c2=tri[a01];"
        "[v01][2:v]xfade=transition=fadefast:duration=0.2:offset=61.10[v02];"
        "[a01][2:a]acrossfade=d=0.2:c1=tri:c2=tri[a02];"
        "[v02][3:v]xfade=transition=dissolve:duration=0.3:offset=84.20[vout];"
        "[a02][3:a]acrossfade=d=0.3:c1=tri:c2=tri[aout]"
    )

    cmd_assemble = [
        "ffmpeg", "-y",
        "-i", intro_mp4,
        "-i", part1_mp4,
        "-i", part2_mp4,
        "-i", outro_mp4,
        "-filter_complex", filter_assemble,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        assembled_mp4
    ]
    subprocess.run(cmd_assemble, check=True)
    print("  Clips assembled successfully into:", assembled_mp4)
    return assembled_mp4

# -------------------------------------------------------------
# 5. Generate Mathematically Synchronized Bilingual Subtitles
# -------------------------------------------------------------
def format_ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def generate_subtitles():
    print("5. Generating Ground-Truth Bilingual ASS Subtitles with Karaoke...")
    subtitles_ass = os.path.join(work_dir, "bilingual_subtitles.ass")

    OFFSET_P1 = 1.70
    CUT_AMOUNT = 13.00

    phrases = [
        # Sentence 1: 1.54 -> 3.94
        {
            "raw_s": 1.54, "raw_e": 3.94,
            "words": [("Hey,", 0.40), ("folks,", 0.45), ("this", 0.35), ("is", 0.30), ("Echo.", 0.60)],
            "zh": "大家好，这里是 Echo · 回声。"
        },
        # Sentence 2: 3.94 -> 7.50
        {
            "raw_s": 3.94, "raw_e": 7.50,
            "words": [("The", 0.20), ("name", 0.35), ("comes", 0.35), ("from", 0.25), ("Echo", 0.45), ("Slam", 0.45), ("in", 0.20), ("Dota", 0.40), ("2.", 0.50)],
            "zh": "名字灵感源自 Dota 2 中撼地者的绝招「回音击」。"
        },
        # Sentence 3: 7.50 -> 10.82
        {
            "raw_s": 7.50, "raw_e": 10.82,
            "words": [("Echo", 0.40), ("is", 0.20), ("an", 0.15), ("app", 0.35), ("where", 0.25), ("you", 0.20), ("can", 0.20), ("talk", 0.35), ("with", 0.20), ("different", 0.45), ("AI", 0.40)],
            "zh": "Echo 是一款能让你与多种前沿大模型"
        },
        # Sentence 4: 10.82 -> 16.12
        {
            "raw_s": 10.82, "raw_e": 16.12,
            "words": [("providers", 0.55), ("in", 0.20), ("real", 0.30), ("time,", 0.45), ("including", 0.50), ("DashScope,", 0.65), ("Google", 0.50)],
            "zh": "进行实时双向语音通话的桌面应用，涵盖阿里 DashScope、"
        },
        # Sentence 5: 16.12 -> 21.73
        {
            "raw_s": 16.12, "raw_e": 21.73,
            "words": [("Gemini,", 0.60), ("and", 0.25), ("a", 0.15), ("Google", 0.45), ("Agent", 0.45), ("platform,", 0.55), ("Tavus,", 0.60), ("and", 0.25), ("more.", 0.45)],
            "zh": "谷歌 Gemini、智能体平台以及 Tavus 等等。"
        },
        # Sentence 6: 21.73 -> 24.43
        {
            "raw_s": 21.73, "raw_e": 24.43,
            "words": [("And", 0.25), ("with", 0.25), ("Tavus,", 0.55), ("you", 0.20), ("can", 0.20), ("even", 0.35), ("talk", 0.45)],
            "zh": "借助 Tavus 的强大能力，你甚至能与"
        },
        # Sentence 7: 24.43 -> 26.87
        {
            "raw_s": 24.43, "raw_e": 26.87,
            "words": [("face", 0.40), ("to", 0.20), ("face", 0.40), ("with", 0.25), ("AI", 0.35), ("avatar.", 0.60)],
            "zh": "AI 虚拟人进行面对面的实时互动。"
        },
        # Sentence 8: 26.87 -> 32.05
        {
            "raw_s": 26.87, "raw_e": 32.05,
            "words": [("And", 0.30), ("here", 0.35), ("is", 0.20), ("one", 0.25), ("of", 0.15), ("my", 0.20), ("favorite", 0.55), ("features,", 0.60), ("Canvas.", 0.80)],
            "zh": "接下来是我最喜欢的功能之一：交互式画布 (Canvas)。"
        },
        # Sentence 9: 32.05 -> 36.22
        {
            "raw_s": 32.05, "raw_e": 36.22,
            "words": [("So", 0.30), ("I", 0.20), ("can", 0.20), ("ask", 0.30), ("Gemini", 0.55), ("to", 0.20), ("create", 0.45), ("something", 0.60)],
            "zh": "我可以在与 Gemini 通话的同时让它即时创作，"
        },
        # Sentence 10: 36.22 -> 41.00
        {
            "raw_s": 36.22, "raw_e": 41.00,
            "words": [("while", 0.35), ("we", 0.20), ("are", 0.15), ("talking", 0.45), ("and", 0.20), ("show", 0.35), ("it", 0.15), ("directly", 0.55), ("on", 0.20), ("the", 0.15), ("Canvas.", 0.65)],
            "zh": "并且直接在画布上动态渲染呈现。"
        },
        # Sentence 11: 41.00 -> 44.78
        {
            "raw_s": 41.00, "raw_e": 44.78,
            "words": [("Let's", 0.35), ("choose", 0.40), ("this", 0.30), ("voice.", 0.55)],
            "zh": "我们先选择这款音色。"
        },
        # Sentence 12: 44.78 -> 49.98
        {
            "raw_s": 44.78, "raw_e": 49.98,
            "words": [("Hey,", 0.35), ("Gemini,", 0.55), ("create", 0.45), ("something", 0.50), ("for", 0.20), ("me", 0.20), ("on", 0.20), ("the", 0.15), ("Canvas,", 0.60)],
            "zh": "“嘿 Gemini，在画布上为我创作点东西吧，"
        },
        # Sentence 13: 49.98 -> 53.37
        {
            "raw_s": 49.98, "raw_e": 53.37,
            "words": [("maybe", 0.40), ("an", 0.20), ("animal,", 0.45), ("a", 0.15), ("plant,", 0.45), ("anything", 0.55), ("you", 0.25), ("want.", 0.45)],
            "zh": "也许是一只小动物、一株植物，任何你喜欢的都行。”"
        },
        # Sentence 14: 53.37 -> 54.80
        {
            "raw_s": 53.37, "raw_e": 54.80,
            "words": [("Thank", 0.35), ("you.", 0.55)],
            "zh": "“谢谢你。”"
        },
        # Sentence 15: 55.20 -> 59.20 (Gemini response before cut)
        {
            "raw_s": 55.20, "raw_e": 59.20,
            "words": [("I", 0.45), ("can", 0.25), ("certainly", 0.65), ("create", 0.45), ("something", 0.45), ("lovely", 0.40), ("on", 0.25), ("your", 0.25), ("canvas.", 0.55)],
            "zh": "“没问题，我很乐意在画布上为您创作一幅精美的作品。”"
        },

        # --- CUT 12.80s HAPPENS HERE ---

        # Sentence 16: raw 72.56 -> 75.20
        {
            "raw_s": 72.56, "raw_e": 75.20,
            "words": [("I", 0.45), ("have", 0.20), ("created", 0.45), ("an", 0.15), ("illustration", 0.65), ("for", 0.25), ("you", 0.25)],
            "zh": "“我已经为您在画布上绘制好了插画："
        },
        # Sentence 17: raw 75.20 -> 78.20
        {
            "raw_s": 75.20, "raw_e": 78.20,
            "words": [("on", 0.20), ("the", 0.15), ("canvas", 0.45), ("featuring", 0.55), ("a", 0.15), ("glowing", 0.45), ("monarch", 0.50), ("butterfly", 0.65)],
            "zh": "一只栖息在盛开花朵上的夜光帝王蝶，"
        },
        # Sentence 18: raw 78.20 -> 81.60
        {
            "raw_s": 78.20, "raw_e": 81.60,
            "words": [("resting", 0.45), ("on", 0.20), ("a", 0.15), ("blooming", 0.45), ("flower,", 0.45), ("complete", 0.50), ("with", 0.20), ("subtle", 0.40), ("fluttering", 0.55)],
            "zh": "还附带了逼真微动的振翅动画。"
        },
        # Sentence 19: raw 81.60 -> 82.60
        {
            "raw_s": 81.60, "raw_e": 82.60,
            "words": [("animations.", 0.85)],
            "zh": "栩栩如生。”"
        },
        # Sentence 20: raw 82.60 -> 84.50
        {
            "raw_s": 82.60, "raw_e": 84.50,
            "words": [("Take", 0.30), ("a", 0.15), ("look", 0.30), ("and", 0.20), ("let", 0.25), ("me", 0.20), ("know", 0.30), ("if", 0.20)],
            "zh": "“请您看看，如果需要任何修改"
        },
        # Sentence 21: raw 84.50 -> 87.60
        {
            "raw_s": 84.50, "raw_e": 87.60,
            "words": [("you", 0.20), ("would", 0.25), ("like", 0.25), ("me", 0.20), ("to", 0.15), ("add", 0.35), ("or", 0.20), ("change", 0.45), ("anything.", 0.65)],
            "zh": "或添加细节，随时告诉我。”"
        },
        # Sentence 22: raw 87.60 -> 89.15
        {
            "raw_s": 87.60, "raw_e": 89.15,
            "words": [("Very", 0.35), ("cool,", 0.45), ("right?", 0.45)],
            "zh": "非常惊艳，对吧？"
        },
        # Sentence 23: raw 89.15 -> 90.28
        {
            "raw_s": 89.15, "raw_e": 90.28,
            "words": [("Here", 0.35), ("it", 0.20), ("is.", 0.40)],
            "zh": "这就是生成的动态效果。"
        },
        # Sentence 24: raw 90.28 -> 92.86
        {
            "raw_s": 90.28, "raw_e": 92.86,
            "words": [("And", 0.25), ("that's", 0.40), ("Echo.", 0.60)],
            "zh": "这就是全新的 Echo · 回声。"
        },
        # Sentence 25: raw 92.86 -> 94.27
        {
            "raw_s": 92.86, "raw_e": 94.27,
            "words": [("Thanks", 0.45), ("for", 0.20), ("watching.", 0.55)],
            "zh": "感谢大家的观看。"
        },
        # Sentence 26: raw 94.27 -> 95.30
        {
            "raw_s": 94.27, "raw_e": 95.30,
            "words": [("Bye,", 0.40), ("guys.", 0.50)],
            "zh": "我们下期再见，拜拜！"
        }
    ]

    ass_header = """[Script Info]
Title: Echo Showcase Bilingual Master
ScriptType: v4.00+
PlayResX: 2052
PlayResY: 1340
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ChineseSimple, Microsoft YaHei, 38, &H00FFFFFF, &H000000FF, &H00000000, &H80000000, 1, 0, 0, 0, 100, 100, 1, 0, 1, 3.8, 2.2, 2, 80, 80, 140, 1
Style: EnglishKaraoke, Segoe UI, 42, &H0000E6FF, &H00E0E0E0, &H00000000, &H80000000, 1, 0, 0, 0, 100, 100, 0, 0, 1, 4.0, 2.2, 2, 80, 80, 80, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_lines = []
    for ph in phrases:
        raw_s = ph["raw_s"]
        raw_e = ph["raw_e"]
        words = ph["words"]
        zh = ph["zh"]

        if raw_s < 59.60:
            final_s = raw_s + OFFSET_P1
            final_e = raw_e + OFFSET_P1
        else:
            final_s = raw_s + OFFSET_P1 - CUT_AMOUNT
            final_e = raw_e + OFFSET_P1 - CUT_AMOUNT

        # Build karaoke
        k_parts = []
        for word, dur in words:
            cs = int(round(dur * 100))
            k_parts.append(f"{{\\k{cs}}}{word} ")
        en_karaoke = "".join(k_parts).strip()

        # Chinese line on top
        dialogue_lines.append(
            f"Dialogue: 0,{format_ass_time(final_s)},{format_ass_time(final_e)},ChineseSimple,,0,0,140,,{zh}"
        )
        # English karaoke on bottom
        dialogue_lines.append(
            f"Dialogue: 0,{format_ass_time(final_s)},{format_ass_time(final_e)},EnglishKaraoke,,0,0,80,,{en_karaoke}"
        )

    with open(subtitles_ass, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(dialogue_lines) + "\n")
    print("  Subtitles ASS written successfully:", subtitles_ass)
    return subtitles_ass

# -------------------------------------------------------------
# 6. Burn Subtitles and Output Master Video
# -------------------------------------------------------------
def burn_subtitles(assembled_mp4, subtitles_ass):
    print("6. Burning Subtitles and Mastering Audio Volume...")
    escaped_subtitles_ass = subtitles_ass.replace("\\", "/").replace(":", "\\:")
    audio_filter = "afade=t=in:st=0.00:d=0.30,afade=t=out:st=85.80:d=0.50,volume=1.20"

    cmd_burn = [
        "ffmpeg", "-y",
        "-i", assembled_mp4,
        "-vf", f"ass='{escaped_subtitles_ass}'",
        "-af", audio_filter,
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "256k",
        final_output
    ]
    subprocess.run(cmd_burn, check=True)
    print(f"  Final Master Video successfully created at:\n    {final_output}")

    # Copy to Desktop & Videos folder
    shutil.copy(final_output, desktop_output)
    print(f"  Copied to Desktop:\n    {desktop_output}")
    shutil.copy(final_output, videos_output)
    print(f"  Copied to Videos:\n    {videos_output}")

def main():
    print("=== Echo Showcase Video Remastering Started ===")
    intro_mp4, outro_mp4 = generate_brand_cards()
    pill_paths, card_paths = generate_overlays()
    part1_mp4, part2_mp4 = process_video_clips(pill_paths, card_paths)
    assembled_mp4 = assemble_clips(intro_mp4, part1_mp4, part2_mp4, outro_mp4)
    subtitles_ass = generate_subtitles()
    burn_subtitles(assembled_mp4, subtitles_ass)
    print("=== All Steps Completed Successfully! ===")

if __name__ == "__main__":
    main()
