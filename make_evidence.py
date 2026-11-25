"""Builds the documents for the YouTube API audit form.

  python3 make_evidence.py

Creates in the folder evidence/:
  terms_of_service.pdf      -> "Terms of Service Documentation" field
  upload_flow_evidence.pdf  -> "Conditional evidence" field: your screenshots (put them in evidence/screens/
                               first: OAuth consent screen, permissions page...) + the complete upload scripts
"""
import glob
import os
import re

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "evidence")
PW, PH, M = 1240, 1754, 90          # A4 at 150 dpi, margin


def _font(size, mono=False):
    cands = (["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "C:/Windows/Fonts/consola.ttf", "/System/Library/Fonts/Menlo.ttc"]
             if mono else [os.path.join(HERE, "assets", "font.otf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for c in cands:
        if os.path.exists(c):
            return ImageFont.truetype(c, size)
    return ImageFont.load_default(size)


def text_pages(title, lines, mono=False, size=22):
    f, ft = _font(size, mono), _font(40)
    pages, page, y = [], None, 0

    def new():
        nonlocal page, y
        page = Image.new("RGB", (PW, PH), "white")
        pages.append(page)
        y = M
        return ImageDraw.Draw(page)

    d = new()
    d.text((M, y), title, font=ft, fill="black")
    y += 80
    maxw = PW - 2 * M
    for raw in lines:
        line = raw.rstrip("\n")
        chunks = [""]
        for word in re.split(r"(\s+)", line):                 # wrap long lines
            if d.textlength(chunks[-1] + word, font=f) > maxw and chunks[-1]:
                chunks.append("    " + word.lstrip())
            else:
                chunks[-1] += word
        for c in chunks:
            if y > PH - M - size:
                d = new()
            d.text((M, y), c, font=f, fill="black")
            y += int(size * 1.45)
    return pages


def md_lines(path):
    out = []
    for l in open(path, encoding="utf-8").readlines()[1:]:      # skip the title line (already the page title)
        l = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", l)   # [text](url) -> text (url)
        out.append(l.replace("**", "").replace("`", "").replace("# ", "").lstrip("#"))
    return out


def image_pages(paths):
    pages = []
    for p in paths:
        im = Image.open(p).convert("RGB")
        im.thumbnail((PW - 2 * M, PH - 2 * M - 60))
        page = Image.new("RGB", (PW, PH), "white")
        ImageDraw.Draw(page).text((M, M - 50), os.path.basename(p), font=_font(26), fill="black")
        page.paste(im, (M, M))
        pages.append(page)
    return pages


def save(pages, path):
    pages[0].save(path, save_all=True, append_images=pages[1:], resolution=150)
    print("wrote", path, f"({len(pages)} pages)")


if __name__ == "__main__":
    os.makedirs(os.path.join(OUT, "screens"), exist_ok=True)
    save(text_pages("Terms of Service — Color Race Uploader", md_lines(os.path.join(HERE, "TERMS.md"))),
         os.path.join(OUT, "terms_of_service.pdf"))

    intro = [
        "Color Race Uploader — complete upload flow",
        "",
        "1. One time: the channel owner runs get_token.py. A Google OAuth consent screen opens and the owner grants",
        "   youtube.upload + youtube.force-ssl. The refresh token is stored as an encrypted GitHub Actions secret.",
        "2. Every day GitHub Actions (.github/workflows/daily.yml) runs daily.py. It renders original videos with",
        "   the project's own code, then calls upload.py -> videos.insert (and thumbnails.set for the long video).",
        "3. Videos are uploaded as scheduled (privacyStatus=private + publishAt) and go public at the set time.",
        "4. Revocation: Google Account -> Security -> Third-party access -> Color Race Uploader -> Remove access.",
        "",
        "Full source code (public): see the GitHub repository linked in this application.",
        "The following pages contain the screenshots and the complete, unmodified scripts.",
    ]
    pages = text_pages("Upload flow evidence", intro)
    shots = sorted(glob.glob(os.path.join(OUT, "screens", "*.png")) + glob.glob(os.path.join(OUT, "screens", "*.jp*g")))
    pages += image_pages(shots)
    for fn in ["get_token.py", "upload.py", "daily.py", ".github/workflows/daily.yml"]:
        pages += text_pages(fn, open(os.path.join(HERE, fn), encoding="utf-8").readlines(), mono=True, size=17)
    save(pages, os.path.join(OUT, "upload_flow_evidence.pdf"))
    if not shots:
        print("note: no screenshots in evidence/screens/ yet - add them and run this again")
