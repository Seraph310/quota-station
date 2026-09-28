"""Build the four-page Chinese training case PDF from public demo screenshots.

Run with a Python environment containing reportlab, Pillow, pypdf, pypdfium2.
The script writes only output/pdf/ and tmp/pdfs/ under the project root.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "images"
OUTPUT = ROOT / "output" / "pdf" / "额度小站-AI工作辅助实践案例.pdf"
QA = ROOT / "tmp" / "pdfs"
PAGE_W, PAGE_H = A4
MARGIN = 42
CONTENT = PAGE_W - MARGIN * 2
CREAM = "#F8F6EE"
PAPER = "#FFFEFB"
INK = "#2F3D37"
MUTED = "#66756D"
GREEN = "#577966"
MINT = "#E4EDDF"
LAVENDER = "#EDE7F4"
PURPLE = "#827094"
LINE = "#DADFD4"


def register_fonts() -> None:
    fonts = Path("C:/Windows/Fonts")
    pdfmetrics.registerFont(TTFont("CN", str(fonts / "msyh.ttc"), subfontIndex=0))
    pdfmetrics.registerFont(TTFont("CN-Bold", str(fonts / "msyhbd.ttc"), subfontIndex=0))
    pdfmetrics.registerFontFamily("CN", normal="CN", bold="CN-Bold", italic="CN", boldItalic="CN-Bold")


class CasePDF:
    def __init__(self, test_count: int, repo_url: str):
        self.test_count = test_count
        self.repo_url = repo_url
        self.c = canvas.Canvas(str(OUTPUT), pagesize=A4, pageCompression=1)
        self.c.setTitle("额度小站 - AI工作辅助实践案例")
        self.c.setAuthor("Seraph310")
        self.c.setSubject("20款AIGC工具实战：从零打造你的AI工作矩阵 - 真实工作辅助案例")
        self.c.setCreator("Seraph310 / quota-station")
        self.bounds = []
        self.current_page = 0

    def rect(self, x, top, w, h, fill=PAPER, radius=12, stroke=None):
        self.c.setFillColor(colors.HexColor(fill))
        if stroke:
            self.c.setStrokeColor(colors.HexColor(stroke))
        self.c.roundRect(x, PAGE_H - top - h, w, h, radius, fill=1, stroke=bool(stroke))

    def text(self, text, x, top, w, size=10.6, leading=17.5, color=INK, bold=False, align=TA_LEFT, max_h=None):
        style = ParagraphStyle(
            "body", fontName="CN-Bold" if bold else "CN", fontSize=size,
            leading=leading, textColor=colors.HexColor(color), wordWrap="CJK",
            alignment=align, spaceAfter=0, splitLongWords=True,
        )
        p = Paragraph(text, style)
        _, h = p.wrap(w, PAGE_H)
        if max_h is not None and h > max_h + 0.1:
            raise ValueError(f"Text overflow on page {self.current_page}: {h:.1f} > {max_h:.1f}: {text[:50]}")
        if top + h > PAGE_H - 42:
            raise ValueError(f"Text crosses footer on page {self.current_page}: {text[:50]}")
        p.drawOn(self.c, x, PAGE_H - top - h)
        self.bounds.append({"page": self.current_page, "kind": "text", "top": top, "height": round(h, 1), "preview": text[:40]})
        return h

    def label(self, text, x, top, w=100, fill=MINT, color=GREEN):
        self.rect(x, top, w, 23, fill, 10)
        self.text(text, x + 6, top + 4.2, w - 12, size=8.5, leading=12, color=color, bold=True, align=TA_CENTER)

    def image(self, filename, x, top, w, h, background=None):
        p = IMAGES / filename
        if not p.is_file():
            raise FileNotFoundError(f"Public demo image is missing: {p}")
        with Image.open(p) as im:
            iw, ih = im.size
        scale = min(w / iw, h / ih)
        dw, dh = iw * scale, ih * scale
        if background:
            self.rect(x, top, w, h, background, 12)
        self.c.drawImage(str(p), x + (w - dw) / 2, PAGE_H - top - (h + dh) / 2, width=dw, height=dh, mask="auto")
        self.bounds.append({"page": self.current_page, "kind": "image", "file": filename, "width": round(dw, 1), "height": round(dh, 1)})

    def start_page(self, number, title=None, subtitle=None):
        self.current_page = number
        self.c.setFillColor(colors.HexColor(CREAM))
        self.c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        self.text("额度小站  /  AI 工作辅助实践案例", MARGIN, 24, CONTENT, size=8, leading=12, color=MUTED)
        self.c.setStrokeColor(colors.HexColor(LINE))
        self.c.line(MARGIN, PAGE_H - 45, PAGE_W - MARGIN, PAGE_H - 45)
        if title:
            self.text(title, MARGIN, 62, CONTENT, size=23, leading=32, bold=True)
        if subtitle:
            self.text(subtitle, MARGIN, 104, CONTENT, size=10.2, leading=17, color=MUTED)

    def finish_page(self, number):
        self.c.setStrokeColor(colors.HexColor(LINE))
        self.c.line(MARGIN, 37, PAGE_W - MARGIN, 37)
        self.c.setFont("CN", 8)
        self.c.setFillColor(colors.HexColor(MUTED))
        self.c.drawString(MARGIN, 22, "Seraph310  ·  2026.09")
        self.c.drawRightString(PAGE_W - MARGIN, 22, f"{number:02d} / 04")
        self.c.showPage()

    def page_one(self):
        self.start_page(1)
        self.label("真实需求 · 成品已使用", MARGIN, 63, 144)
        self.text("把 AI 额度<br/>放在桌面一角", MARGIN, 105, CONTENT, size=33, leading=46, bold=True)
        self.text("额度小站", MARGIN, 215, CONTENT, size=18, leading=25, color=GREEN, bold=True)
        self.text("一个由 Codex 协助完成的 Windows 桌面小组件，<br/>把 Codex、Qoder、WorkBuddy 的额度集中到一个入口。", MARGIN, 251, CONTENT, size=11.5, leading=20)
        self.image("overview.png", MARGIN, 309, CONTENT, 252)
        self.text("成品界面概览  ·  图中均为演示数据", MARGIN, 568, CONTENT, size=8.7, leading=14, color=MUTED, align=TA_CENTER)
        self.rect(MARGIN, 603, CONTENT, 147, PAPER, 14)
        self.text("培训作业", MARGIN + 18, 619, 90, size=10, leading=16, bold=True, color=GREEN)
        self.text("《20款AIGC工具实战：从零打造你的AI工作矩阵》", MARGIN + 18, 646, CONTENT - 36, size=11, leading=19, bold=True)
        self.text("任务：结合实际工作，运用任一或多款工具完成真实工作辅助案例。", MARGIN + 18, 680, CONTENT - 36, size=10.2, leading=17.5)
        self.text("作者：Seraph310", MARGIN + 18, 722, CONTENT - 36, size=9.2, leading=14, color=MUTED)
        self.finish_page(1)

    def page_two(self):
        self.start_page(2, "从工作习惯，长出交互细节", "需求来自生物信息学日常工作；每一次反馈，都落实为可直接使用的修改。")
        self.rect(MARGIN, 145, CONTENT, 86, PAPER)
        self.text("原本的不便", MARGIN + 16, 159, 105, size=10.7, leading=17, bold=True, color=GREEN)
        self.text("多种 AI 工具的额度分散在各自客户端。逐个打开查看会打断正在进行的工作；原有 WorkBuddy 积分球也只覆盖一家工具，外观不够贴合桌面。", MARGIN + 16, 186, CONTENT - 32, size=10.2, leading=17, max_h=38)
        gap = 12
        w = (CONTENT - gap * 2) / 3
        for index, (file, name, note) in enumerate((
            ("card.png", "小卡片", "安静地放在桌面角落"),
            ("ball.png", "悬浮球", "换一种更紧凑的外形"),
            ("note.png", "展开便签", "集中查看三家明细"),
        )):
            x = MARGIN + index * (w + gap)
            self.rect(x, 250, w, 192, PAPER)
            self.image(file, x + 7, 260, w - 14, 122)
            self.text(name, x + 8, 390, w - 16, size=10.8, leading=17, bold=True, align=TA_CENTER)
            self.text(note, x + 5, 418, w - 10, size=8.4, leading=13, color=MUTED, align=TA_CENTER)
        self.text("由用户反馈推动的五次落地", MARGIN, 463, CONTENT, size=14, leading=22, bold=True)
        rows = [
            ("外观与便签融合", "奶白、淡绿、淡紫配色；三种显示形态。"),
            ("小而够用", "单击轮换工具，双击展开便签。"),
            ("缩放要自然", "拖住右下角折角等比例缩放，文字同步变化。"),
            ("保持使用习惯", "记住位置、大小和外形；收起保留当前选择。"),
            ("跟随新客户端", "适配独立 Qoder App，无需再打开旧 IDE。"),
        ]
        for index, (left, right) in enumerate(rows):
            top = 499 + index * 49
            self.rect(MARGIN, top, CONTENT, 42, MINT if index % 2 == 0 else PAPER, 8)
            self.text(f"{index+1:02d}  {left}", MARGIN + 12, top + 11, 151, size=9.2, leading=15, bold=True, color=GREEN)
            self.text(right, MARGIN + 173, top + 10, CONTENT - 185, size=9.4, leading=16, max_h=30)
        self.finish_page(2)

    def page_three(self):
        self.start_page(3, "Codex 怎样把想法变成工具", "我判断需求与使用感受，Codex 负责实现、适配、排查和测试。")
        self.rect(MARGIN, 147, CONTENT, 96, LAVENDER)
        self.text("协作分工", MARGIN + 17, 164, CONTENT - 34, size=12.4, leading=20, bold=True, color=PURPLE)
        self.text("主要创作工具是 Codex，承担开发与验证；Qoder 和 WorkBuddy 是额度监测对象。用户持续提供需求与反馈，决定作品的使用体验。", MARGIN + 17, 195, CONTENT - 34, size=10.6, leading=18, max_h=38)
        self.text("从需求到成品的协作过程", MARGIN, 266, CONTENT, size=14, leading=22, bold=True)
        stages = [("01 明确需求", "集中看额度，外观贴合桌面"), ("02 看成品反馈", "调整便签、轮换、展开与缩放"), ("03 接入真实来源", "分别适配三家账户读取方式"), ("04 验证再迭代", "测试异常路径与实际桌面交互")]
        for i, (title, body) in enumerate(stages):
            x = MARGIN + (i % 2) * ((CONTENT - 12) / 2 + 12)
            top = 304 + (i // 2) * 76
            self.rect(x, top, (CONTENT - 12) / 2, 64, PAPER, 9)
            self.text(title, x + 12, top + 10, (CONTENT - 12) / 2 - 24, size=10.2, leading=17, bold=True, color=GREEN)
            self.text(body, x + 12, top + 36, (CONTENT - 12) / 2 - 24, size=9.1, leading=15)
        self.text("让它能长期放在桌面上的处理", MARGIN, 472, CONTENT, size=14, leading=22, bold=True)
        notes = [
            ("本地读取", "Python / PySide6 构建窗口。每家有独立的读取模块，再统一显示；不靠提交模型任务探测额度。"),
            ("失败可辨认", "读取失败保留上次成功值，并显示更新状态与时间；缺失或异常字段不当成零。"),
            ("来源不混用", "新版 Qoder App 账号存在时，查询失败保留该来源并提示状态，避免账号混用。"),
            ("信息各归各位", "额度窗口与积分分别呈现；不公开登录信息，公开展示图使用演示数值。"),
        ]
        for i, (title, body) in enumerate(notes):
            top = 510 + i * 59
            self.label(title, MARGIN, top + 4, 91, MINT)
            self.text(body, MARGIN + 106, top + 1, CONTENT - 106, size=10.2, leading=17, max_h=40)
        self.finish_page(3)

    def page_four(self):
        self.start_page(4, "交付的是一个用起来的作品", "成品已在真实 Windows 桌面使用；判断价值，同时保留验证边界。")
        w = (CONTENT - 14) / 2
        self.rect(MARGIN, 151, w, 124, MINT)
        self.text("本机实测", MARGIN + 18, 168, w - 36, size=10.5, leading=17, bold=True, color=GREEN)
        self.text("三家读取成功", MARGIN + 18, 199, w - 36, size=20, leading=29, bold=True)
        self.text("含 Qoder App 0.4.3 适配", MARGIN + 18, 246, w - 36, size=9.5, leading=15, color=MUTED)
        x = MARGIN + w + 14
        self.rect(x, 151, w, 124, LAVENDER)
        self.text("本轮基础验证", x + 18, 168, w - 36, size=10.5, leading=17, bold=True, color=PURPLE)
        self.text(f"{self.test_count} 项测试通过", x + 18, 199, w - 36, size=20, leading=29, bold=True)
        self.text("解析、异常、来源与交互等行为", x + 18, 246, w - 36, size=9.2, leading=15, color=MUTED)
        self.text("获得了什么", MARGIN, 307, CONTENT, size=14, leading=22, bold=True)
        self.text("把分散的额度查看入口集中到桌面，把一次性的外观设想落实为可持续使用的小工具。支持自动刷新、手动刷新、状态提示与偏好保存。", MARGIN, 341, CONTENT, size=11, leading=19, max_h=42)
        self.rect(MARGIN, 403, CONTENT, 142, PAPER)
        self.text("当前边界", MARGIN + 17, 419, CONTENT - 34, size=12.2, leading=19, bold=True, color=GREEN)
        self.text("• 尚未开展定量效率评估，收益以实际功能和使用体验描述。<br/>• 部分客户端兼容接口可能随版本变化，需要持续维护。<br/>• 目前依赖 Windows，尚未进行大规模跨机器测试。<br/>• 本机成功不等同于所有账号、网络与版本都已兼容。", MARGIN + 17, 448, CONTENT - 34, size=10.2, leading=20, max_h=83)
        self.text("公开交付与复现入口", MARGIN, 573, CONTENT, size=14, leading=22, bold=True)
        self.text("源码、测试与使用说明保留在 GitHub；配套 Markdown 说明与本 PDF 可用于培训展示。公开材料不包含真实余额或登录文件。", MARGIN, 607, CONTENT, size=10.5, leading=18, max_h=40)
        self.rect(MARGIN, 669, CONTENT, 72, MINT, 12)
        self.text("GitHub  ·  Seraph310 / quota-station", MARGIN + 16, 682, CONTENT - 32, size=11.4, leading=18, bold=True, color=GREEN)
        self.text(f'<link href="{self.repo_url}" color="{GREEN}">{self.repo_url}</link>', MARGIN + 16, 711, CONTENT - 32, size=9.2, leading=15)
        self.finish_page(4)

    def build(self):
        self.page_one()
        self.page_two()
        self.page_three()
        self.page_four()
        self.c.save()


def render_pdf() -> str:
    poppler = shutil.which("pdftoppm")
    if poppler:
        completed = subprocess.run([poppler, "-r", "145", "-png", str(OUTPUT), str(QA / "case-page")], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if completed.returncode == 0:
            return "Poppler pdftoppm (145 dpi)"
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(str(OUTPUT))
    for i in range(len(document)):
        page = document[i]
        page.render(scale=145 / 72).to_pil().save(QA / f"case-page-{i + 1}.png")
    document.close()
    return "pypdfium2 (145 dpi)"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-count", type=int, default=92)
    parser.add_argument("--repo-url", default="https://github.com/Seraph310/quota-station")
    args = parser.parse_args()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    for name in ("overview.png", "card.png", "ball.png", "note.png"):
        if not (IMAGES / name).is_file():
            raise SystemExit(f"Missing public demo screenshot: {IMAGES / name}")
    register_fonts()
    book = CasePDF(args.test_count, args.repo_url)
    book.build()
    reader = PdfReader(str(OUTPUT))
    if len(reader.pages) != 4:
        raise AssertionError("Expected exactly four PDF pages")
    texts = [page.extract_text() or "" for page in reader.pages]
    if not all("Seraph310" in text for text in texts):
        raise AssertionError("Missing author footer")
    joined = "\n".join(texts)
    if "演示数据" not in joined or str(args.test_count) not in joined:
        raise AssertionError("Expected content missing from PDF text extraction")
    renderer = render_pdf()
    (QA / "case-study-extracted.txt").write_text(joined, encoding="utf-8")
    qa = {
        "pages": len(reader.pages), "output_bytes": OUTPUT.stat().st_size,
        "renderer": renderer, "test_count_stated": args.test_count,
        "author": "Seraph310", "repo_url": args.repo_url,
        "page_text_lengths": [len(t) for t in texts],
        "elements": book.bounds, "visual_review": "pending",
    }
    (QA / "case-study-qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pdf": str(OUTPUT), "pages": 4, "renderer": renderer, "bytes": OUTPUT.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    main()
