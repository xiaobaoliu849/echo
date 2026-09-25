import os
import glob
import subprocess
import shutil
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def format_ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def draw_sparkle(draw, cx, cy, r_outer, r_inner, fill):
    points = []
    for i in range(8):
        angle = i * math.pi / 4 - math.pi / 2
        r = r_outer if i % 2 == 0 else r_inner
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(points, fill=fill)

def main():
    print("=== Echo Gemini 3.8 Live: Ground-Truth Aligned Video Builder ===")
    
    videos = glob.glob(r"C:\Users\WINDOWS\Videos\*\*.mp4")
    target_files = [f for f in videos if "124625" in f]
    if not target_files:
        raise FileNotFoundError("Could not find source video 2026-09-16 124625.mp4")
    src_video = target_files[0]
    print(f"Source video: {src_video}")

    work_dir = r"C:\Users\WINDOWS\.gemini\antigravity\brain\975abe82-0e8e-4d2a-b0a2-8bbe65e87181\scratch"
    os.makedirs(work_dir, exist_ok=True)
    final_output = r"C:\Users\WINDOWS\Videos\Echo_Gemini_3.8_Live_30s_Demo.mp4"
    desktop_output = r"C:\Users\WINDOWS\Desktop\9月16日_Echo_Gemini3.8Live_动态高亮双语.mp4"
    artifact_output = r"C:\Users\WINDOWS\.gemini\antigravity\brain\975abe82-0e8e-4d2a-b0a2-8bbe65e87181\Echo_Gemini_3.8_Live_30s_Demo.mp4"

    W, H = 1914, 1342
    windir = os.environ.get('WINDIR', r'C:\Windows')
    logo_path = r"resources\icons\logo.png"

    # -------------------------------------------------------------
    # 1. Generate High-Res V6 Intro Card (PNG -> MP4, 2.2 seconds)
    # -------------------------------------------------------------
    print("1. Generating Intro Card with Echo App Logo and Sage Brand Palette...")
    intro_png = os.path.join(work_dir, "intro_card_v6.png")
    intro_mp4 = os.path.join(work_dir, "intro_v6.mp4")

    font_logo_text = ImageFont.truetype(os.path.join(windir, 'Fonts', 'segoeuib.ttf'), 76)
    font_gemini = ImageFont.truetype(os.path.join(windir, 'Fonts', 'segoeuib.ttf'), 42)
    font_gemini_cn = ImageFont.truetype(os.path.join(windir, 'Fonts', 'msyhbd.ttc'), 34)
    font_badge = ImageFont.truetype(os.path.join(windir, 'Fonts', 'msyhbd.ttc'), 24)
    font_sub = ImageFont.truetype(os.path.join(windir, 'Fonts', 'msyh.ttc'), 25)
    font_url = ImageFont.truetype(os.path.join(windir, 'Fonts', 'segoeuib.ttf'), 34)
    font_out_gemini = ImageFont.truetype(os.path.join(windir, 'Fonts', 'msyhbd.ttc'), 36)

    cx = W // 2
    cy = 440

    logo_raw = Image.open(logo_path).convert('RGBA')
    logo_200 = logo_raw.resize((200, 200), Image.Resampling.LANCZOS)
    s_intro = Image.new('RGBA', (260, 260), (0, 0, 0, 0))
    sd_intro = ImageDraw.Draw(s_intro)
    sd_intro.rounded_rectangle([20, 20, 240, 240], radius=52, fill=(0, 0, 0, 180))
    s_intro = s_intro.filter(ImageFilter.GaussianBlur(20))

    glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow)
    for r in range(500, 0, -10):
        alpha = int(24 * (1.0 - r / 500.0))
        g_draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(97, 132, 115, alpha))

    badge_text = "● 实时双向语音通话   |   ◆ Live Canvas 动态交互渲染   |   ★ 深度长程逻辑推理"
    sub_text = "本地优先 · 自由可控 · 全能语音 AI 桌面助手"

    def draw_url_badge(img, y_pos):
        url_text = "github.com/xiaobaoliu849/echo"
        draw_temp = ImageDraw.Draw(img)
        bbox = draw_temp.textbbox((0, 0), url_text, font=font_url)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        
        pad_x, pad_y = 32, 12
        pill_box = [cx - tw//2 - pad_x, y_pos - pad_y, cx + tw//2 + pad_x, y_pos + th + pad_y]
        
        s = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(s)
        sd.rounded_rectangle(pill_box, radius=24, fill=(0, 0, 0, 160))
        s = s.filter(ImageFilter.GaussianBlur(10))
        img = Image.alpha_composite(img, s)
        
        p_bg = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        pd = ImageDraw.Draw(p_bg)
        pd.rounded_rectangle(pill_box, radius=24, fill=(24, 36, 31, 230), outline=(97, 132, 115, 200), width=2)
        pd.text((cx - tw // 2, y_pos - 2), url_text, fill=(240, 248, 244, 255), font=font_url)
        img = Image.alpha_composite(img, p_bg)
        return img

    # --- Intro Card ---
    img_intro = Image.new('RGBA', (W, H), (14, 20, 18, 255))
    img_intro = Image.alpha_composite(img_intro, glow)
    img_intro.paste(s_intro, (cx - 130, cy - 115), s_intro)
    img_intro.paste(logo_200, (cx - 100, cy - 100), logo_200)

    draw = ImageDraw.Draw(img_intro)
    title_text = "E C H O"
    bbox = draw.textbbox((0, 0), title_text, font=font_logo_text)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, cy + 135), title_text, fill=(245, 248, 246, 255), font=font_logo_text)

    # Centered Gemini line with sparkle
    gemini_en = "Gemini 3.8 Live"
    gemini_cn = "  (Extended Thinking 深度思考)"
    bbox_ge = draw.textbbox((0, 0), gemini_en, font=font_gemini)
    gew = bbox_ge[2] - bbox_ge[0]
    bbox_gc = draw.textbbox((0, 0), gemini_cn, font=font_gemini_cn)
    gcw = bbox_gc[2] - bbox_gc[0]
    total_line_w = 36 + gew + gcw
    start_x = cx - total_line_w // 2
    draw_sparkle(draw, start_x + 14, cy + 258, 16, 6, fill=(255, 230, 0, 255))
    draw.text((start_x + 36, cy + 235), gemini_en, fill=(255, 230, 0, 255), font=font_gemini)
    draw.text((start_x + 36 + gew, cy + 241), gemini_cn, fill=(210, 230, 222, 255), font=font_gemini_cn)

    bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw = bbox[2] - bbox[0]
    bh = bbox[3] - bbox[1]
    pill_box = [cx - bw // 2 - 36, cy + 320 - 14, cx + bw // 2 + 36, cy + 320 + bh + 14]
    pill_bg = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    p_draw = ImageDraw.Draw(pill_bg)
    p_draw.rounded_rectangle(pill_box, radius=26, fill=(28, 42, 36, 220), outline=(97, 132, 115, 180), width=2)
    img_intro = Image.alpha_composite(img_intro, pill_bg)

    draw = ImageDraw.Draw(img_intro)
    draw.text((cx - bw // 2, cy + 320), badge_text, fill=(230, 242, 236, 255), font=font_badge)

    bbox = draw.textbbox((0, 0), sub_text, font=font_sub)
    sw = bbox[2] - bbox[0]
    draw.text((cx - sw // 2, cy + 400), sub_text, fill=(150, 180, 170, 220), font=font_sub)

    # Identical enlarged URL badge at cy + 480
    img_intro = draw_url_badge(img_intro, cy + 480)
    img_intro.save(intro_png)

    # 2.2 seconds intro video (Clean, static, crystal-clear presentation)
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-t", "2.20", "-i", intro_png,
        "-f", "lavfi", "-t", "2.20", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf", "fps=30,scale=1914:1342,format=yuv420p",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-t", "2.20",
        intro_mp4
    ], check=True, capture_output=True)

    # -------------------------------------------------------------
    # 2. Generate Outro Card (PNG -> MP4, 1.8 seconds, Static & Clean)
    # -------------------------------------------------------------
    print("2. Generating Outro Card with Brand Wrap-Up...")
    outro_png = os.path.join(work_dir, "outro_card_v6.png")
    outro_mp4 = os.path.join(work_dir, "outro_v6.mp4")

    # --- Outro Card (100% Identical Coordinates & Symmetric Styling) ---
    img_outro = Image.new('RGBA', (W, H), (14, 20, 18, 255))
    img_outro = Image.alpha_composite(img_outro, glow)
    img_outro.paste(s_intro, (cx - 130, cy - 115), s_intro)
    img_outro.paste(logo_200, (cx - 100, cy - 100), logo_200)

    draw_out = ImageDraw.Draw(img_outro)
    draw_out.text((cx - tw // 2, cy + 135), title_text, fill=(245, 248, 246, 255), font=font_logo_text)

    out_gemini_text = "Experience Gemini 3.8 Live with Realtime Voice & Interactive Canvas"
    bbox = draw_out.textbbox((0, 0), out_gemini_text, font=font_out_gemini)
    gw = bbox[2] - bbox[0]
    draw_out.text((cx - gw // 2, cy + 240), out_gemini_text, fill=(255, 230, 0, 255), font=font_out_gemini)

    pill_bg_out = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    p_draw_out = ImageDraw.Draw(pill_bg_out)
    p_draw_out.rounded_rectangle(pill_box, radius=26, fill=(28, 42, 36, 220), outline=(97, 132, 115, 180), width=2)
    img_outro = Image.alpha_composite(img_outro, pill_bg_out)

    draw_out = ImageDraw.Draw(img_outro)
    draw_out.text((cx - bw // 2, cy + 320), badge_text, fill=(230, 242, 236, 255), font=font_badge)
    draw_out.text((cx - sw // 2, cy + 400), sub_text, fill=(150, 180, 170, 220), font=font_sub)

    # Identical enlarged URL badge at EXACT SAME position: cy + 480
    img_outro = draw_url_badge(img_outro, cy + 480)
    img_outro.save(outro_png)

    # 1.8 seconds outro video (Clean, static, crystal-clear presentation)
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-t", "1.80", "-i", outro_png,
        "-f", "lavfi", "-t", "1.80", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf", "fps=30,scale=1914:1342,format=yuv420p",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-t", "1.80",
        outro_mp4
    ], check=True, capture_output=True)

    # -------------------------------------------------------------
    # 3. Generate Persistent Top Island HUD Pills (Scenes 1-4)
    # -------------------------------------------------------------
    print("3. Generating Persistent Top Island HUD Pills...")
    font_bold = ImageFont.truetype(os.path.join(windir, 'Fonts', 'segoeuib.ttf'), 19)
    font_regular = ImageFont.truetype(os.path.join(windir, 'Fonts', 'msyh.ttc'), 17)
    font_cn_bold = ImageFont.truetype(os.path.join(windir, 'Fonts', 'msyhbd.ttc'), 18)
    logo_28 = logo_raw.resize((28, 28), Image.Resampling.LANCZOS)

    def generate_top_pill(badge_color, badge_tag, desc_text):
        pill_w = 1040
        pill_h = 46
        img = Image.new('RGBA', (pill_w, pill_h), (0, 0, 0, 0))
        s = Image.new('RGBA', (pill_w, pill_h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(s)
        sd.rounded_rectangle([4, 4, pill_w-4, pill_h-2], radius=22, fill=(0, 0, 0, 140))
        s = s.filter(ImageFilter.GaussianBlur(6))
        img.paste(s, (0, 2), s)
        
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([2, 2, pill_w-2, pill_h-2], radius=22, fill=(18, 26, 23, 242), outline=(97, 132, 115, 180), width=1)
        img.paste(logo_28, (16, 9), logo_28)
        draw.text((54, 11), 'Echo', fill=(255, 255, 255, 255), font=font_bold)
        draw.text((106, 11), '×', fill=(150, 175, 165, 255), font=font_cn_bold)
        draw_sparkle(draw, 134, 23, 8, 3, fill=(255, 230, 0, 255))
        draw.text((148, 11), 'Gemini 3.8 Live', fill=(255, 230, 0, 255), font=font_bold)
        draw.text((312, 12), '(Extended Thinking)', fill=(175, 205, 195, 255), font=font_regular)
        draw.line([(485, 11), (485, 35)], fill=(75, 105, 95, 220), width=1)
        draw.ellipse([505, 18, 517, 30], fill=badge_color)
        draw.text((526, 11), badge_tag, fill=badge_color, font=font_bold)
        draw.text((665, 12), desc_text, fill=(235, 245, 240, 255), font=font_cn_bold)
        return img

    pills_info = {
        'pill_s1.png': ((74, 222, 128, 255), 'LIVE VOICE', '实时双向语音通话'),
        'pill_s2.png': ((56, 189, 248, 255), 'TOOL CALL', 'render_canvas -> 交互式组件渲染'),
        'pill_s3.png': ((251, 191, 36, 255), 'LIVE SANDBOX', 'Interactive Tokenizer 原理解析与试用'),
        'pill_s4.png': ((192, 132, 252, 255), 'ECHO AGENT', '本地优先 · 全能 AI 桌面助手')
    }
    pill_paths = {}
    for filename, (color, tag, desc) in pills_info.items():
        p_img = generate_top_pill(color, tag, desc)
        p_path = os.path.join(work_dir, filename)
        p_img.save(p_path)
        pill_paths[filename] = p_path

    # -------------------------------------------------------------
    # 4. Ground-Truth Accurate Cuts for Scenes C1 - C4
    # -------------------------------------------------------------
    print("4. Cutting Ground-Truth Aligned Scenes C1-C4 (Decoded Frame-Accurate)...")
    scenes = [
        {"id": "c1", "ss": "12.65", "dur": "5.40", "pill": "pill_s1.png"},
        {"id": "c2", "ss": "107.80", "dur": "5.90", "pill": "pill_s2.png"},
        {"id": "c3", "ss": "149.90", "dur": "6.20", "pill": "pill_s3.png"},
        {"id": "c4", "ss": "395.10", "dur": "4.00", "pill": "pill_s4.png"},
    ]

    cut_files = []
    px = (W - 1040) // 2
    py = 10

    for sc in scenes:
        out_clip = os.path.join(work_dir, f"{sc['id']}_v6.mp4")
        pill_file = pill_paths[sc['pill']]
        
        filter_str = (
            f"[0:v]fps=30,scale=1914:1342:force_original_aspect_ratio=decrease,pad=1914:1342:(ow-iw)/2:(oh-ih)/2[v0];"
            f"[v0][1:v]overlay=x={px}:y={py}[vout]"
        )

        # -i before -ss guarantees exact decoding-time sample alignment
        cmd = [
            "ffmpeg", "-y",
            "-i", src_video,
            "-i", pill_file,
            "-ss", sc["ss"], "-t", sc["dur"],
            "-filter_complex", filter_str,
            "-map", "[vout]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            out_clip
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        cut_files.append(out_clip)
        print(f"  Rendered {sc['id']} (ss={sc['ss']}, dur={sc['dur']}s)")

    # -------------------------------------------------------------
    # 5. Assemble Clips with Transitions & Smooth Audio Crossfades
    # -------------------------------------------------------------
    print("5. Assembling 6 Clips with Transitions (Eliminating Thumps & Pops)...")
    assembled_mp4 = os.path.join(work_dir, "assembled_v6.mp4")

    filter_complex = (
        "[0:v][1:v]xfade=transition=circleopen:duration=0.4:offset=1.8[v01];"
        "[0:a][1:a]acrossfade=d=0.4:c1=tri:c2=tri[a01];"
        "[v01][2:v]xfade=transition=smoothleft:duration=0.5:offset=6.7[v02];"
        "[a01][2:a]acrossfade=d=0.5:c1=tri:c2=tri[a02];"
        "[v02][3:v]xfade=transition=zoomin:duration=0.5:offset=12.1[v03];"
        "[a02][3:a]acrossfade=d=0.5:c1=tri:c2=tri[a03];"
        "[v03][4:v]xfade=transition=fadeblack:duration=0.5:offset=17.8[v04];"
        "[a03][4:a]acrossfade=d=0.5:c1=tri:c2=tri[a04];"
        "[v04][5:v]xfade=transition=dissolve:duration=0.4:offset=21.4[vout];"
        "[a04][5:a]acrossfade=d=0.4:c1=tri:c2=tri[aout]"
    )

    cmd_assemble = [
        "ffmpeg", "-y",
        "-i", intro_mp4,
        "-i", cut_files[0],
        "-i", cut_files[1],
        "-i", cut_files[2],
        "-i", cut_files[3],
        "-i", outro_mp4,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        assembled_mp4
    ]
    subprocess.run(cmd_assemble, check=True, capture_output=True)
    print("  Assembled 6-clip video successfully!")

    # -------------------------------------------------------------
    # 6. Generate 100% Mathematically Aligned Bilingual Subtitles
    # -------------------------------------------------------------
    print("6. Writing Subtitle ASS File with Ground-Truth Whisper Alignment...")
    subtitles_ass = os.path.join(work_dir, "ground_truth_v6_subtitles.ass")

    phrases = [
        # Scene 1:
        {
            "start": 2.10, "end": 4.50,
            "words": [
                ("I", 0.24), ("have", 0.14), ("put", 0.14), ("together", 0.44),
                ("an", 0.14), ("interactive", 0.52), ("visual", 0.46), ("guide", 0.32)
            ],
            "zh": "我已在画布上为您生成了交互式可视化指南"
        },
        {
            "start": 4.52, "end": 6.90,
            "words": [
                ("on", 0.16), ("your", 0.14), ("canvas", 0.40), ("to", 0.36),
                ("explain", 0.42), ("what", 0.26), ("a", 0.08), ("token", 0.24), ("is.", 0.32)
            ],
            "zh": "通过动态代码与组件，清晰解释 Token 的核心概念"
        },
        # Scene 2:
        {
            "start": 7.05, "end": 9.20,
            "words": [
                ("I", 0.56), ("have", 0.18), ("re-rendered", 0.50), ("the", 0.16),
                ("token", 0.22), ("explainer", 0.53)
            ],
            "zh": "已在画布上重新编译 Token 交互组件"
        },
        {
            "start": 9.22, "end": 12.05,
            "words": [
                ("using", 0.28), ("standard", 0.54), ("self-contained", 0.70),
                ("markup", 0.42), ("directly", 0.34), ("on", 0.32), ("the", 0.10), ("canvas.", 0.32)
            ],
            "zh": "采用原生标准自包含代码，直接在画布中实时呈现"
        },
        # Scene 3:
        {
            "start": 12.40, "end": 14.75,
            "words": [
                ("That", 0.54), ("number", 0.32), ("is", 0.20), ("simply", 0.32),
                ("the", 0.20), ("specific", 0.54), ("index", 0.43)
            ],
            "zh": "那个数字就是该 Token 在词表中的唯一索引"
        },
        {
            "start": 14.78, "end": 17.85,
            "words": [
                ("assigned", 0.44), ("to", 0.20), ("that", 0.12), ("particular", 0.44),
                ("token", 0.34), ("within", 0.30), ("the", 0.18), ("model's", 0.36),
                ("vocabulary", 0.38), ("list.", 0.48)
            ],
            "zh": "每个文本块都有固定编号，供大模型精准识别与计算"
        },
        # Scene 4:
        {
            "start": 18.05, "end": 21.35,
            "words": [
                ("You", 0.48), ("are", 0.48), ("very", 0.36), ("welcome,", 0.48),
                ("and", 0.10), ("I'm", 0.16), ("glad", 0.18), ("that", 0.22),
                ("explanation", 0.38), ("was", 0.36), ("helpful.", 0.32)
            ],
            "zh": "很高兴这能帮您彻底理清概念！"
        }
    ]

    ass_header = """[Script Info]
Title: Echo Gemini 3.8 Live Showcase - Stable Master
ScriptType: v4.00+
PlayResX: 1914
PlayResY: 1342
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ChineseSimple, Microsoft YaHei, 34, &H00FFFFFF, &H000000FF, &H00000000, &H00000000, 1, 0, 0, 0, 100, 100, 1, 0, 1, 3.4, 2.0, 2, 60, 60, 132, 1
Style: EnglishKaraoke, Segoe UI, 38, &H0000E6FF, &H00E0E0E0, &H00000000, &H00000000, 1, 0, 0, 0, 100, 100, 0, 0, 1, 3.6, 2.0, 2, 60, 60, 74, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_lines = []
    for ph in phrases:
        p_start = ph["start"]
        p_end = ph["end"]
        words = ph["words"]
        zh = ph["zh"]
        
        k_parts = []
        for word, dur in words:
            cs = int(round(dur * 100))
            k_parts.append(f"{{\\k{cs}}}{word} ")
        en_karaoke = "".join(k_parts).strip()
        
        # Chinese on TOP (MarginV 132)
        dialogue_lines.append(
            f"Dialogue: 0,{format_ass_time(p_start)},{format_ass_time(p_end)},ChineseSimple,,0,0,132,,{zh}"
        )
        # English on BOTTOM (MarginV 74), word-by-word golden yellow karaoke highlight
        dialogue_lines.append(
            f"Dialogue: 0,{format_ass_time(p_start)},{format_ass_time(p_end)},EnglishKaraoke,,0,0,74,,{en_karaoke}"
        )

    with open(subtitles_ass, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(dialogue_lines) + "\n")
    print("  Subtitles ASS written successfully.")

    # -------------------------------------------------------------
    # 7. Burn Subtitles and Clean Mastering (Zero Thump, True Sync)
    # -------------------------------------------------------------
    print("7. Burning Subtitles & Clean Mastering (Zero Thump, True Sync)...")
    escaped_subtitles_ass = subtitles_ass.replace("\\", "/").replace(":", "\\:")
    audio_filter = "afade=t=in:st=1.80:d=0.20,afade=t=out:st=21.20:d=0.40,volume=1.15"

    final_cmd = [
        "ffmpeg", "-y",
        "-i", assembled_mp4,
        "-vf", f"ass='{escaped_subtitles_ass}'",
        "-af", audio_filter,
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "256k",
        final_output
    ]
    subprocess.run(final_cmd, check=True, capture_output=True)
    print(f"Final output created at: {final_output}")

    # Copy to Desktop and Artifact
    shutil.copy(final_output, desktop_output)
    print(f"Copied to Desktop: {desktop_output}")
    shutil.copy(final_output, artifact_output)
    print(f"Copied to Artifact: {artifact_output}")

    size_mb = os.path.getsize(final_output) / (1024 * 1024)
    print(f"=== BUILD COMPLETE! File size: {size_mb:.2f} MB, Total Duration: ~23.20s ===")

if __name__ == "__main__":
    main()
