#!/usr/bin/env python3
"""Export the evidence-led HTML investor brief with its diagrams embedded."""
from pathlib import Path
from html import unescape
import re, subprocess, tempfile, time
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as RLImage, PageBreak, Paragraph, SimpleDocTemplate

ROOT = Path('/Users/hendrixchen/Desktop/私募/QUANTcode')
HTML, PDF = ROOT / 'QuantCode_Investor_Brief_v2.html', ROOT / 'QuantCode_Investor_Brief_v2.pdf'
for name, path in [('CN', '/System/Library/Fonts/STHeiti Light.ttc'), ('CN-Bold', '/System/Library/Fonts/STHeiti Medium.ttc')]:
    try: pdfmetrics.registerFont(TTFont(name, path))
    except Exception: pass
font = 'CN' if 'CN' in pdfmetrics.getRegisteredFontNames() else 'Helvetica'
bold = 'CN-Bold' if 'CN-Bold' in pdfmetrics.getRegisteredFontNames() else 'Helvetica-Bold'
raw = HTML.read_text(encoding='utf-8')
body = re.search(r'<body>(.*)</body>', raw, re.S).group(1)
sections = re.findall(r'<section class="sheet(?: cover)?">(.*?)</section>', body, re.S)

def clean(text):
    text = re.sub(r'<style.*?</style>|<svg.*?</svg>', '', text, flags=re.S)
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\n\s*\n+', '\n', unescape(text).replace('→', ' -> ').replace('≤', '<=' )).strip()

def render_svg(svg, directory, index):
    source, out = directory / f'flow-{index}.svg', directory / 'rendered'
    out.mkdir(exist_ok=True); source.write_text(svg, encoding='utf-8')
    subprocess.run(['qlmanage','-t','-s','1800','-o',str(out),str(source)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rendered = out / f'{source.name}.png'
    for _ in range(50):
        if rendered.exists(): break
        time.sleep(.1)
    if not rendered.exists(): raise RuntimeError(f'Quick Look did not render {source}')
    vb = re.search(r'viewBox="[^\"]*?\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"', svg)
    return rendered, (float(vb.group(2)) / float(vb.group(1)) if vb else .5)

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='CNH2', fontName=bold, fontSize=16, leading=22, textColor=colors.HexColor('#17324D'), spaceAfter=4*mm))
styles.add(ParagraphStyle(name='CNBody', fontName=font, fontSize=9.5, leading=15, textColor=colors.HexColor('#303432'), spaceAfter=3*mm))
styles.add(ParagraphStyle(name='CNMono', fontName='Courier', fontSize=8, leading=12, textColor=colors.HexColor('#555555')))
doc = SimpleDocTemplate(str(PDF), pagesize=A4, leftMargin=17*mm, rightMargin=17*mm, topMargin=17*mm, bottomMargin=17*mm)
story, temp, svg_index = [], Path(tempfile.mkdtemp(prefix='quantcode-pdf-')), 0
h2 = {'投资判断先说结论','为什么量化团队需要“编排层”','真实架构：一个可控的状态图','风险不是提示词，是路由规则','六组功能：从想法到风控交付','两条流程，展示系统如何负责','PIT：回测不能看到未来','不是一次写对，而是迭代修对','产品成熟度：可演示，不等于已规模化','投资价值：一套可被验证的基础设施'}
for index, section in enumerate(sections):
    if not clean(section): continue
    for piece in re.split(r'(<svg.*?</svg>)', section, flags=re.S):
        if not piece.strip(): continue
        if piece.lstrip().startswith('<svg'):
            svg_index += 1; image, ratio = render_svg(piece.strip(), temp, svg_index)
            story.append(RLImage(str(image), width=170*mm, height=170*mm*ratio)); continue
        for line in (x.strip() for x in clean(piece).splitlines() if x.strip()):
            if re.match(r'^(0[1-9]|10)\b', line) or line.startswith(('QuantCode /','QUANTCODE  /')): continue
            if len(line) < 80 and (line.endswith(('架构','负责')) or line in h2): story.append(Paragraph(line, styles['CNH2']))
            elif line.startswith(('FACTS AT','READING NOTE','Executive','Architecture','Safety','The problem','Six','Data','Evidence','Readiness','Closing','图 ','证据口径','边界声明','重要的诚实','文档原则')): story.append(Paragraph(line.replace('&','&amp;'), styles['CNMono']))
            else: story.append(Paragraph(line.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;'), styles['CNBody']))
    if index < len(sections)-1: story.append(PageBreak())

def footer(canvas, doc):
    canvas.saveState(); canvas.setStrokeColor(colors.HexColor('#C9C3B8')); canvas.line(17*mm,10*mm,193*mm,10*mm)
    canvas.setFont('Courier',7); canvas.setFillColor(colors.HexColor('#77736C')); canvas.drawString(17*mm,6*mm,'QUANTCODE / INVESTOR TECHNICAL BRIEF / CONFIDENTIAL'); canvas.restoreState()
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(PDF)
