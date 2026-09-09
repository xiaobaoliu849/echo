import math
from PIL import Image, ImageDraw

def create_echo_logo(size=512):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # 1. Rounded rectangle mask with smooth squircle-like radius (31% of size)
    radius = int(size * 0.31)
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    padding = int(size * 0.05)
    mask_draw.rounded_rectangle([padding, padding, size - padding, size - padding], radius=radius, fill=255)

    # 2. Exact gradient background sampled from UI .vsWelcomeHeroIcon:
    # Top: rgb(122, 142, 131) -> Bottom: rgb(88, 106, 96) (Sage Green / 鼠尾草灰绿)
    c1 = (122, 142, 131)
    c2 = (88, 106, 96)
    base_grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(base_grad)
    for y in range(size):
        ratio = y / size
        r = int(c1[0] * (1 - ratio) + c2[0] * ratio)
        g = int(c1[1] * (1 - ratio) + c2[1] * ratio)
        b = int(c1[2] * (1 - ratio) + c2[2] * ratio)
        grad_draw.line([(0, y), (size, y)], fill=(r, g, b, 255))

    img.paste(base_grad, (0, 0), mask)

    # 3. Draw the Sound Waves (Echo bars in pure white with round caps)
    bar_color = (255, 255, 255, 255)
    stroke_w = int(size * 0.076)

    # Target box centered
    box_l = size * 0.245
    box_t = size * 0.245
    box_w = size * 0.51
    box_h = size * 0.51

    def map_pt(vx, vy):
        return (box_l + (vx / 24.0) * box_w, box_t + (vy / 24.0) * box_h)

    bars = [
        (12, 3, 21),
        (8, 6, 18),
        (16, 6, 18),
        (4, 10, 14),
        (20, 10, 14),
    ]

    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    for vx, vy1, vy2 in bars:
        p1 = map_pt(vx, vy1)
        p2 = map_pt(vx, vy2)
        overlay_draw.line([p1, p2], fill=bar_color, width=stroke_w)
        r = stroke_w // 2
        overlay_draw.ellipse([p1[0] - r, p1[1] - r, p1[0] + r, p1[1] + r], fill=bar_color)
        overlay_draw.ellipse([p2[0] - r, p2[1] - r, p2[0] + r, p2[1] + r], fill=bar_color)

    img = Image.alpha_composite(img, overlay)
    return img

if __name__ == "__main__":
    logo = create_echo_logo(512)
    logo.save("d:/voicespirit/resources/icons/logo.png", format="PNG")
    logo.save("d:/voicespirit/electron/icon.png", format="PNG")
    
    # Save standard Windows ICO with 256x256 highest resolution
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    ico_images = [logo.resize(s, Image.Resampling.LANCZOS) for s in sizes]
    ico_images[0].save(
        "d:/voicespirit/resources/icons/logo.ico",
        format="ICO",
        sizes=sizes,
        append_images=ico_images[1:]
    )
    print("Exact Echo Sage-Green logo generated successfully!")
