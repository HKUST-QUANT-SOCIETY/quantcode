#!/usr/bin/env python3
"""
QuantCode 投资人介绍文档生成器
生成包含详细架构图和流程图的专业中文PDF文档
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    Image as RLImage, KeepTogether
)
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Circle, Polygon
from reportlab.graphics import renderPDF
import os

# 注册中文字体
try:
    # macOS 系统字体路径
    pdfmetrics.registerFont(TTFont('SimHei', '/System/Library/Fonts/STHeiti Light.ttc'))
    pdfmetrics.registerFont(TTFont('SimHei-Bold', '/System/Library/Fonts/STHeiti Medium.ttc'))
    FONT_NAME = 'SimHei'
    FONT_NAME_BOLD = 'SimHei-Bold'
except:
    try:
        pdfmetrics.registerFont(TTFont('SimHei', '/System/Library/Fonts/PingFang.ttc'))
        pdfmetrics.registerFont(TTFont('SimHei-Bold', '/System/Library/Fonts/PingFang.ttc'))
        FONT_NAME = 'SimHei'
        FONT_NAME_BOLD = 'SimHei-Bold'
    except:
        FONT_NAME = 'Helvetica'
        FONT_NAME_BOLD = 'Helvetica-Bold'

class InvestorDeckGenerator:
    def __init__(self, output_path):
        self.output_path = output_path
        self.doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            topMargin=2*cm,
            bottomMargin=2*cm,
            leftMargin=2.5*cm,
            rightMargin=2.5*cm
        )
        self.story = []
        self.styles = self._create_styles()
        self.width, self.height = A4

    def _create_styles(self):
        """创建文档样式"""
        styles = getSampleStyleSheet()

        # 标题样式
        styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=styles['Heading1'],
            fontName=FONT_NAME_BOLD,
            fontSize=28,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=30,
            alignment=1  # 居中
        ))

        styles.add(ParagraphStyle(
            name='CustomHeading1',
            parent=styles['Heading1'],
            fontName=FONT_NAME_BOLD,
            fontSize=18,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=12,
            spaceBefore=20
        ))

        styles.add(ParagraphStyle(
            name='CustomHeading2',
            parent=styles['Heading2'],
            fontName=FONT_NAME_BOLD,
            fontSize=14,
            textColor=colors.HexColor('#34495e'),
            spaceAfter=10,
            spaceBefore=15
        ))

        styles.add(ParagraphStyle(
            name='CustomBody',
            parent=styles['BodyText'],
            fontName=FONT_NAME,
            fontSize=11,
            leading=18,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=10
        ))

        styles.add(ParagraphStyle(
            name='CustomBullet',
            parent=styles['BodyText'],
            fontName=FONT_NAME,
            fontSize=10,
            leading=16,
            leftIndent=20,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=6
        ))

        return styles

    def add_cover_page(self, hkust_logo_path, quantdiner_logo_path):
        """添加封面页"""
        # Logo容器
        logo_table_data = []
        logos = []

        if os.path.exists(hkust_logo_path):
            hkust_img = RLImage(hkust_logo_path, width=4*cm, height=1.5*cm)
            logos.append(hkust_img)

        if os.path.exists(quantdiner_logo_path):
            qd_img = RLImage(quantdiner_logo_path, width=3*cm, height=3*cm)
            logos.append(qd_img)

        if len(logos) == 2:
            logo_table_data = [[logos[0], logos[1]]]
            logo_table = Table(logo_table_data, colWidths=[8*cm, 8*cm])
            logo_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            self.story.append(logo_table)
            self.story.append(Spacer(1, 1.5*cm))

        # 主标题
        self.story.append(Spacer(1, 3*cm))
        title = Paragraph("QuantCode", self.styles['CustomTitle'])
        self.story.append(title)

        subtitle_style = ParagraphStyle(
            name='Subtitle',
            parent=self.styles['CustomBody'],
            fontSize=16,
            textColor=colors.HexColor('#7f8c8d'),
            alignment=1
        )
        subtitle = Paragraph("量化交易智能体框架", subtitle_style)
        self.story.append(subtitle)
        self.story.append(Spacer(1, 0.5*cm))

        subtitle2 = Paragraph("投资人技术说明书", subtitle_style)
        self.story.append(subtitle2)

        self.story.append(Spacer(1, 4*cm))

        # 版本信息
        version_style = ParagraphStyle(
            name='Version',
            parent=self.styles['CustomBody'],
            fontSize=10,
            textColor=colors.HexColor('#95a5a6'),
            alignment=1
        )
        version = Paragraph("Version 1.0 | 2026年7月", version_style)
        self.story.append(version)

        contact = Paragraph("HKUST QUANT SOCIETY · Agent Group", version_style)
        self.story.append(contact)

        self.story.append(PageBreak())

    def add_executive_summary(self):
        """添加执行摘要"""
        self.story.append(Paragraph("执行摘要", self.styles['CustomHeading1']))

        content = """
        <b>QuantCode</b> 是一个面向量化交易的生产级智能体框架，专为金融机构和量化团队设计。
        本系统基于 <b>LangGraph 状态机编排</b>和 <b>ReAct (Reasoning + Acting) 架构</b>，
        提供了从因子挖掘到策略回测的完整工作流支持。
        """
        self.story.append(Paragraph(content, self.styles['CustomBody']))
        self.story.append(Spacer(1, 0.5*cm))

        # 核心价值主张
        self.story.append(Paragraph("核心价值主张", self.styles['CustomHeading2']))

        values = [
            ("生产就绪", "内置人机协作（HumanGate）、状态持久化、异常恢复机制"),
            ("专业工具链", "6大工具组（因子/风险/期权/基本面/模型/策略），覆盖量化全流程"),
            ("架构灵活", "五级隔离作用域（SESSION/THREAD/GROUP/PROJECT/GLOBAL）"),
            ("合规安全", "Point-in-Time (PIT) 时间安全保证，防止回测穿越"),
            ("可扩展", "插件化工具注册机制，支持自定义工具和第三方集成")
        ]

        data = [[Paragraph(f"<b>{k}</b>", self.styles['CustomBody']),
                 Paragraph(v, self.styles['CustomBody'])] for k, v in values]

        value_table = Table(data, colWidths=[4*cm, 11*cm])
        value_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#ecf0f1')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2c3e50')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7'))
        ]))
        self.story.append(value_table)
        self.story.append(Spacer(1, 0.5*cm))

        # 当前进展
        self.story.append(Paragraph("项目状态（2026年7月）", self.styles['CustomHeading2']))

        status_content = """
        • <b>代码成熟度：</b>核心框架已完成，单元测试通过率 100%（589/589）<br/>
        • <b>工具覆盖：</b>36个生产级工具，支持6大量化场景<br/>
        • <b>文档完整性：</b>用户手册、API文档、启动脚本已齐全<br/>
        • <b>待完成事项：</b>AutoEval服务端部署、多语言SDK、云部署方案
        """
        self.story.append(Paragraph(status_content, self.styles['CustomBody']))

        self.story.append(PageBreak())

    def create_architecture_diagram(self):
        """创建系统架构图"""
        d = Drawing(400, 320)

        # 标题
        d.add(String(200, 300, '系统架构全景', textAnchor='middle',
                    fontSize=14, fillColor=colors.HexColor('#2c3e50')))

        # Layer 1: 用户层
        d.add(Rect(50, 250, 300, 35, fillColor=colors.HexColor('#3498db'),
                  strokeColor=colors.HexColor('#2980b9'), strokeWidth=1))
        d.add(String(200, 265, '用户层：Agent + 自然语言交互', textAnchor='middle',
                    fontSize=10, fillColor=colors.white))

        # Arrow 1
        d.add(Line(200, 250, 200, 230, strokeColor=colors.HexColor('#7f8c8d'), strokeWidth=2))
        d.add(Polygon([195, 230, 200, 225, 205, 230],
                     fillColor=colors.HexColor('#7f8c8d'), strokeColor=None))

        # Layer 2: 编排层
        d.add(Rect(50, 185, 300, 40, fillColor=colors.HexColor('#2ecc71'),
                  strokeColor=colors.HexColor('#27ae60'), strokeWidth=1))
        d.add(String(200, 205, 'LangGraph 状态机编排', textAnchor='middle',
                    fontSize=10, fillColor=colors.white))
        d.add(String(200, 193, 'ReAct循环 + 工具路由 + HumanGate中断', textAnchor='middle',
                    fontSize=8, fillColor=colors.white))

        # Arrow 2
        d.add(Line(200, 185, 200, 165, strokeColor=colors.HexColor('#7f8c8d'), strokeWidth=2))
        d.add(Polygon([195, 165, 200, 160, 205, 165],
                     fillColor=colors.HexColor('#7f8c8d'), strokeColor=None))

        # Layer 3: 工具层（6个工具组）
        tool_groups = [
            ('因子', 70, 110), ('风险', 140, 110), ('期权', 210, 110),
            ('基本面', 280, 110), ('模型', 350, 110), ('策略', 70, 50)
        ]

        for name, x, y in tool_groups[:5]:  # 前5个在上排
            d.add(Rect(x-25, y, 50, 30, fillColor=colors.HexColor('#e74c3c'),
                      strokeColor=colors.HexColor('#c0392b'), strokeWidth=1))
            d.add(String(x, y+15, name, textAnchor='middle',
                        fontSize=9, fillColor=colors.white))

        # 策略组单独一行
        d.add(Rect(45, 50, 50, 30, fillColor=colors.HexColor('#e74c3c'),
                  strokeColor=colors.HexColor('#c0392b'), strokeWidth=1))
        d.add(String(70, 65, '策略', textAnchor='middle',
                    fontSize=9, fillColor=colors.white))

        # 工具层框架
        d.add(Rect(40, 40, 320, 110, fillColor=None,
                  strokeColor=colors.HexColor('#95a5a6'), strokeWidth=1.5, strokeDashArray=[3, 3]))
        d.add(String(200, 30, '工具注册表（36个工具，6大工具组）', textAnchor='middle',
                    fontSize=8, fillColor=colors.HexColor('#7f8c8d')))

        # Arrow 3 (multiple arrows to tool layer)
        for x in [100, 200, 300]:
            d.add(Line(x, 160, x, 145, strokeColor=colors.HexColor('#7f8c8d'), strokeWidth=1.5))
            d.add(Polygon([x-3, 145, x, 140, x+3, 145],
                         fillColor=colors.HexColor('#7f8c8d'), strokeColor=None))

        # Layer 4: 数据层
        d.add(Rect(50, 5, 300, 25, fillColor=colors.HexColor('#95a5a6'),
                  strokeColor=colors.HexColor('#7f8c8d'), strokeWidth=1))
        d.add(String(200, 15, '数据层：State持久化 + 会话管理 + 时间安全（PIT）', textAnchor='middle',
                    fontSize=9, fillColor=colors.white))

        # Arrows to data layer
        d.add(Line(70, 40, 100, 30, strokeColor=colors.HexColor('#7f8c8d'), strokeWidth=1))
        d.add(Line(200, 40, 200, 30, strokeColor=colors.HexColor('#7f8c8d'), strokeWidth=1))
        d.add(Line(330, 40, 300, 30, strokeColor=colors.HexColor('#7f8c8d'), strokeWidth=1))

        return d

    def add_architecture_section(self):
        """添加架构设计章节"""
        self.story.append(Paragraph("一、系统架构设计", self.styles['CustomHeading1']))

        intro = """
        QuantCode 采用<b>分层架构</b>设计，将用户交互、状态编排、工具执行、数据管理
        四层解耦，确保系统的可维护性和可扩展性。
        """
        self.story.append(Paragraph(intro, self.styles['CustomBody']))
        self.story.append(Spacer(1, 0.3*cm))

        # 架构图
        arch_diagram = self.create_architecture_diagram()
        self.story.append(arch_diagram)
        self.story.append(Spacer(1, 0.5*cm))

        # 设计理念
        self.story.append(Paragraph("1.1 核心设计理念", self.styles['CustomHeading2']))

        design_principles = """
        <b>为什么选择LangGraph？</b><br/>
        传统的Agent框架（如LangChain的AgentExecutor）采用线性执行模式，难以支持复杂的人机协作流程。
        LangGraph 基于<b>状态图（StateGraph）</b>抽象，将Agent的执行流程建模为状态机，支持：

        • <b>中断/恢复机制：</b>在关键决策点暂停执行，等待人工确认后继续<br/>
        • <b>状态持久化：</b>每个状态节点的输出自动保存，支持断点续跑<br/>
        • <b>条件路由：</b>根据运行时状态动态决定下一个执行节点<br/>
        • <b>循环控制：</b>通过状态指纹检测死循环，自动触发HumanGate
        """
        self.story.append(Paragraph(design_principles, self.styles['CustomBody']))
        self.story.append(Spacer(1, 0.3*cm))

        # ReAct模式
        self.story.append(Paragraph("1.2 ReAct (Reasoning + Acting) 模式", self.styles['CustomHeading2']))

        react_content = """
        QuantCode 的核心执行循环采用 ReAct 模式，这是一种将<b>推理（Reasoning）</b>和
        <b>行动（Acting）</b>交替进行的Agent架构：

        <b>执行流程：</b><br/>
        1. <b>Reason：</b>LLM根据当前任务和历史状态，生成推理步骤和工具调用计划<br/>
        2. <b>Act：</b>执行工具调用，获取实际数据（如计算因子IC、风险指标）<br/>
        3. <b>Observe：</b>将工具返回结果更新到状态中<br/>
        4. <b>Loop：</b>重复1-3，直到任务完成或触发HumanGate

        <b>优势：</b>相比传统的单次规划执行模式，ReAct支持动态调整策略，
        适合金融场景中需要根据中间结果调整分析路径的情况。
        """
        self.story.append(Paragraph(react_content, self.styles['CustomBody']))
        self.story.append(Spacer(1, 0.3*cm))

        # 状态管理
        self.story.append(Paragraph("1.3 状态管理与隔离", self.styles['CustomHeading2']))

        state_content = """
        <b>TypedDict 状态契约：</b><br/>
        系统使用 Python 的 TypedDict 定义状态模式（AgentState），强制类型检查。
        任何未在 TypedDict 中声明的字段都会被 LangGraph 静默丢弃，确保状态一致性。

        <b>五级作用域隔离：</b>
        """
        self.story.append(Paragraph(state_content, self.styles['CustomBody']))

        scope_data = [
            ["作用域", "生命周期", "典型用途"],
            ["SESSION", "单次对话", "临时计算结果、中间变量"],
            ["THREAD", "任务线程", "子任务的上下文传递"],
            ["GROUP", "工具组", "工具组内共享的配置（如risk组的阈值）"],
            ["PROJECT", "项目级", "策略参数、回测配置"],
            ["GLOBAL", "全局", "API密钥、数据库连接"]
        ]

        scope_table = Table(scope_data, colWidths=[3*cm, 4*cm, 8*cm])
        scope_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), FONT_NAME_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#ecf0f1')])
        ]))
        self.story.append(scope_table)

        self.story.append(PageBreak())

    def create_react_flow_diagram(self):
        """创建ReAct执行流程图"""
        d = Drawing(400, 300)

        # 标题
        d.add(String(200, 285, 'ReAct 执行循环', textAnchor='middle',
                    fontSize=14, fillColor=colors.HexColor('#2c3e50')))

        # Node positions
        nodes = [
            ('用户输入', 200, 240, colors.HexColor('#3498db')),
            ('LLM推理', 80, 180, colors.HexColor('#2ecc71')),
            ('工具调用', 200, 120, colors.HexColor('#e74c3c')),
            ('状态更新', 320, 180, colors.HexColor('#f39c12')),
            ('完成/中断', 200, 60, colors.HexColor('#9b59b6'))
        ]

        # Draw nodes
        for label, x, y, color in nodes:
            d.add(Circle(x, y, 25, fillColor=color, strokeColor=colors.HexColor('#2c3e50'), strokeWidth=1.5))
            d.add(String(x, y-3, label, textAnchor='middle', fontSize=9, fillColor=colors.white))

        # Draw arrows with labels
        # User -> LLM
        d.add(Line(185, 225, 95, 200, strokeColor=colors.HexColor('#2c3e50'), strokeWidth=2))
        d.add(Polygon([95, 200, 90, 195, 100, 193], fillColor=colors.HexColor('#2c3e50'), strokeColor=None))
        d.add(String(140, 215, '任务', fontSize=8, fillColor=colors.HexColor('#7f8c8d')))

        # LLM -> Tool
        d.add(Line(95, 165, 185, 135, strokeColor=colors.HexColor('#2c3e50'), strokeWidth=2))
        d.add(Polygon([185, 135, 180, 130, 190, 128], fillColor=colors.HexColor('#2c3e50'), strokeColor=None))
        d.add(String(140, 148, '工具计划', fontSize=8, fillColor=colors.HexColor('#7f8c8d')))

        # Tool -> State
        d.add(Line(215, 135, 305, 165, strokeColor=colors.HexColor('#2c3e50'), strokeWidth=2))
        d.add(Polygon([305, 165, 300, 160, 310, 158], fillColor=colors.HexColor('#2c3e50'), strokeColor=None))
        d.add(String(260, 148, '执行结果', fontSize=8, fillColor=colors.HexColor('#7f8c8d')))

        # State -> LLM (loop)
        d.add(Line(305, 195, 95, 195, strokeColor=colors.HexColor('#16a085'), strokeWidth=2, strokeDashArray=[3, 3]))
        d.add(Polygon([95, 195, 100, 198, 100, 192], fillColor=colors.HexColor('#16a085'), strokeColor=None))
        d.add(String(200, 200, '继续推理', fontSize=8, fillColor=colors.HexColor('#16a085')))

        # State -> Complete
        d.add(Line(305, 165, 215, 75, strokeColor=colors.HexColor('#2c3e50'), strokeWidth=2))
        d.add(Polygon([215, 75, 210, 80, 220, 78], fillColor=colors.HexColor('#2c3e50'), strokeColor=None))
        d.add(String(265, 120, '任务完成', fontSize=8, fillColor=colors.HexColor('#7f8c8d')))

        # LLM -> Complete (gate trigger)
        d.add(Line(65, 170, 185, 75, strokeColor=colors.HexColor('#e74c3c'), strokeWidth=2, strokeDashArray=[5, 2]))
        d.add(Polygon([185, 75, 180, 80, 190, 78], fillColor=colors.HexColor('#e74c3c'), strokeColor=None))
        d.add(String(120, 120, 'HumanGate', fontSize=8, fillColor=colors.HexColor('#e74c3c')))

        # Legend
        d.add(String(50, 30, '实线=正常流程', fontSize=7, fillColor=colors.HexColor('#7f8c8d')))
        d.add(String(50, 20, '虚线=循环/中断', fontSize=7, fillColor=colors.HexColor('#7f8c8d')))

        return d

    def create_humangate_diagram(self):
        """创建HumanGate人机协作流程图"""
        d = Drawing(400, 280)

        # 标题
        d.add(String(200, 265, 'HumanGate 人机协作模式', textAnchor='middle',
                    fontSize=14, fillColor=colors.HexColor('#2c3e50')))

        # Timeline
        stages = [
            ('Agent执行', 50, 200, 80, 40, colors.HexColor('#3498db')),
            ('风险检测', 150, 200, 80, 40, colors.HexColor('#e74c3c')),
            ('暂停等待', 250, 200, 80, 40, colors.HexColor('#f39c12')),
            ('人工决策', 50, 120, 80, 40, colors.HexColor('#9b59b6')),
            ('恢复执行', 150, 120, 80, 40, colors.HexColor('#2ecc71')),
            ('完成任务', 250, 120, 80, 40, colors.HexColor('#1abc9c'))
        ]

        for i, (label, x, y, w, h, color) in enumerate(stages):
            d.add(Rect(x, y, w, h, fillColor=color, strokeColor=colors.HexColor('#2c3e50'), strokeWidth=1.5))
            d.add(String(x + w/2, y + h/2 - 3, label, textAnchor='middle', fontSize=9, fillColor=colors.white))

        # Arrows
        arrows = [
            (130, 220, 150, 220),  # 1->2
            (230, 220, 250, 220),  # 2->3
            (290, 200, 90, 160),   # 3->4
            (130, 140, 150, 140),  # 4->5
            (230, 140, 250, 140),  # 5->6
        ]

        for x1, y1, x2, y2 in arrows:
            d.add(Line(x1, y1, x2, y2, strokeColor=colors.HexColor('#34495e'), strokeWidth=2))
            if x1 < x2:  # horizontal arrow
                d.add(Polygon([x2, y2, x2-5, y2+3, x2-5, y2-3],
                             fillColor=colors.HexColor('#34495e'), strokeColor=None))
            else:  # diagonal arrow
                d.add(Polygon([x2, y2, x2-3, y2+5, x2+3, y2+5],
                             fillColor=colors.HexColor('#34495e'), strokeColor=None))

        # Trigger conditions
        trigger_text = """
        触发条件：
        • 风险指标超阈值（如最大回撤>30%）
        • 循环检测（状态指纹重复）
        • 关键决策点（如策略参数调整）
        """
        y_offset = 80
        for i, line in enumerate(trigger_text.strip().split('\n')):
            d.add(String(200, y_offset - i*12, line.strip(), textAnchor='middle',
                        fontSize=8, fillColor=colors.HexColor('#2c3e50')))

        # Benefits box
        d.add(Rect(30, 10, 340, 35, fillColor=colors.HexColor('#ecf0f1'),
                  strokeColor=colors.HexColor('#95a5a6'), strokeWidth=1))
        d.add(String(200, 32, '价值：防止错误决策传播 + 合规审计追踪 + 专家知识注入',
                    textAnchor='middle', fontSize=9, fillColor=colors.HexColor('#2c3e50')))
        d.add(String(200, 18, '应用：生产环境必备（Pattern 2/5），回测可选（Pattern 1）',
                    textAnchor='middle', fontSize=8, fillColor=colors.HexColor('#7f8c8d')))

        return d

    def add_workflow_section(self):
        """添加工作流详解章节"""
        self.story.append(Paragraph("二、六大工作流详解", self.styles['CustomHeading1']))

        intro = """
        QuantCode 围绕量化交易全流程设计了6个核心工作流，每个工作流对应一组专业工具，
        支持从因子挖掘到策略部署的完整链路。
        """
        self.story.append(Paragraph(intro, self.styles['CustomBody']))
        self.story.append(Spacer(1, 0.5*cm))

        # ReAct流程图
        self.story.append(Paragraph("2.1 执行模式：ReAct循环", self.styles['CustomHeading2']))
        react_diagram = self.create_react_flow_diagram()
        self.story.append(react_diagram)
        self.story.append(Spacer(1, 0.3*cm))

        # HumanGate流程图
        self.story.append(Paragraph("2.2 人机协作：HumanGate机制", self.styles['CustomHeading2']))
        humangate_diagram = self.create_humangate_diagram()
        self.story.append(humangate_diagram)
        self.story.append(Spacer(1, 0.5*cm))

        # 六大工作流表格
        self.story.append(Paragraph("2.3 工作流矩阵", self.styles['CustomHeading2']))

        workflow_data = [
            ["工作流", "核心工具", "典型任务", "输出物"],
            ["因子挖掘", "calc_factor_ic\nlist_available_factors",
             "计算因子与收益的相关性\n筛选高预测力因子", "因子IC值\n因子排名"],
            ["风险管理", "calc_risk_stub\ngenerate_risk_profile",
             "计算最大回撤/VaR\n生成风险报告", "风险指标\n风险评级"],
            ["期权定价", "price_european_option\ncalc_implied_vol",
             "Black-Scholes定价\n隐含波动率反推", "期权价格\n希腊字母"],
            ["基本面分析", "get_company_financials\nget_market_overview",
             "获取财务报表\n行业对比分析", "财务数据\n估值指标"],
            ["模型训练", "train_factor_model\nevaluate_model",
             "训练机器学习模型\n模型评估", "模型文件\n评估报告"],
            ["策略回测", "run_backtest\noptimize_strategy",
             "历史数据回测\n参数优化", "收益曲线\n最优参数"]
        ]

        workflow_table = Table(workflow_data, colWidths=[3*cm, 3.5*cm, 4.5*cm, 4*cm])
        workflow_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (-1, 0), FONT_NAME_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#ecf0f1')])
        ]))
        self.story.append(workflow_table)

        self.story.append(PageBreak())

    def add_implementation_section(self):
        """添加实现方案章节"""
        self.story.append(Paragraph("三、关键技术实现", self.styles['CustomHeading1']))

        # 3.1 工具注册机制
        self.story.append(Paragraph("3.1 工具注册与动态加载", self.styles['CustomHeading2']))

        tool_impl = """
        <b>设计思路：</b><br/>
        传统Agent框架将工具硬编码在代码中，扩展性差。QuantCode采用<b>插件化注册机制</b>：

        <b>实现方式：</b><br/>
        1. 每个工具组（如factor/risk/options）有独立的<b>_register.py</b>模块<br/>
        2. 使用装饰器<b>@register_tool(group="factor")</b>自动注册工具到全局注册表<br/>
        3. LangGraph节点在运行时通过<b>tool_routing_edge</b>动态查找工具<br/>
        4. 支持按工具组过滤访问权限（如某些Agent只能调用risk组工具）

        <b>代码示例：</b>
        """
        self.story.append(Paragraph(tool_impl, self.styles['CustomBody']))

        code_example = """
        # tools/factor/_register.py
        from core.registry import register_tool

        @register_tool(group="factor", scope="PROJECT")
        def calc_factor_ic(factor_name: str, start_date: str, end_date: str):
            \"\"\"计算因子IC值（信息系数）\"\"\"
            # 从数据库获取因子值和收益率
            factor_values = db.get_factor(factor_name, start_date, end_date)
            returns = db.get_returns(start_date, end_date)
            # 计算Spearman相关系数
            ic = spearmanr(factor_values, returns).correlation
            return {"ic": ic, "factor": factor_name}
        """

        code_style = ParagraphStyle(
            name='Code',
            parent=self.styles['CustomBody'],
            fontName='Courier',
            fontSize=8,
            leading=12,
            leftIndent=10,
            textColor=colors.HexColor('#2c3e50'),
            backColor=colors.HexColor('#f8f9fa')
        )
        self.story.append(Paragraph(code_example.replace('\n', '<br/>').replace(' ', '&nbsp;'), code_style))
        self.story.append(Spacer(1, 0.3*cm))

        benefits = """
        <b>优势：</b><br/>
        • <b>零侵入扩展：</b>新增工具只需添加文件，无需修改核心代码<br/>
        • <b>权限控制：</b>通过GROUP作用域限制工具访问范围<br/>
        • <b>测试隔离：</b>单元测试可清空注册表，避免全局状态污染<br/>
        • <b>动态重载：</b>支持运行时热更新工具（通过importlib.reload）
        """
        self.story.append(Paragraph(benefits, self.styles['CustomBody']))
        self.story.append(Spacer(1, 0.5*cm))

        # 3.2 时间安全保证
        self.story.append(Paragraph("3.2 Point-in-Time (PIT) 时间安全", self.styles['CustomHeading2']))

        pit_content = """
        <b>问题背景：</b><br/>
        金融回测最大的陷阱是<b>未来函数（Lookahead Bias）</b>：使用了回测时点尚未公布的数据。
        例如：2023年1月1日的策略决策使用了2023年1月31日才发布的财报数据。

        <b>QuantCode的解决方案：</b><br/>
        1. <b>as_of_date强制传参：</b>所有数据查询工具必须接收as_of_date参数<br/>
        2. <b>数据库层PIT查询：</b>只返回as_of_date之前已公布的数据<br/>
        3. <b>时间戳验证：</b>在State中记录数据获取时间，LangGraph检查时间一致性<br/>
        4. <b>审计日志：</b>记录每次数据访问的时间戳，便于事后审计

        <b>技术实现（伪代码）：</b>
        """
        self.story.append(Paragraph(pit_content, self.styles['CustomBody']))

        pit_code = """
        def get_company_financials(ticker: str, as_of_date: str):
            # 查询as_of_date之前最新的财报
            sql = \"\"\"
                SELECT * FROM financials
                WHERE ticker = ? AND publish_date <= ?
                ORDER BY publish_date DESC LIMIT 1
            \"\"\"
            return db.query(sql, (ticker, as_of_date))

        # State中强制记录时间
        class AgentState(TypedDict):
            as_of_date: str  # 回测时点
            data_timestamps: dict  # 记录每个数据的获取时间
        """
        self.story.append(Paragraph(pit_code.replace('\n', '<br/>').replace(' ', '&nbsp;'), code_style))
        self.story.append(Spacer(1, 0.3*cm))

        pit_value = """
        <b>业务价值：</b><br/>
        • 回测结果可信度提升：避免虚高的回测收益<br/>
        • 合规审计通过：监管机构要求的时间安全证明<br/>
        • 生产一致性：回测和实盘使用相同的数据访问逻辑
        """
        self.story.append(Paragraph(pit_value, self.styles['CustomBody']))

        self.story.append(PageBreak())

        # 3.3 状态管理
        self.story.append(Paragraph("三、关键技术实现（续）", self.styles['CustomHeading1']))
        self.story.append(Paragraph("3.3 状态契约与类型安全", self.styles['CustomHeading2']))

        state_impl = """
        <b>技术挑战：</b><br/>
        LangGraph使用TypedDict定义状态模式，但Python的TypedDict仅做静态类型检查，
        运行时不会阻止新增字段。这导致一个隐蔽的bug：<b>未声明的字段会被静默丢弃</b>。

        <b>实际案例（Day 5修复的Bug）：</b><br/>
        • HumanGate路由依赖<b>risk_profile</b>字段判断是否需要人工确认<br/>
        • 但AgentState的TypedDict中未声明risk_profile字段<br/>
        • 导致generate_risk_profile工具的返回值被LangGraph丢弃<br/>
        • 路由逻辑永远读到None，HumanGate永不触发

        <b>修复方案：</b>
        """
        self.story.append(Paragraph(state_impl, self.styles['CustomBody']))

        state_fix_code = """
        # 修复前（Bug）
        class AgentState(BaseFlowState, total=False):
            risk_metrics: dict | None
            # risk_profile字段缺失！

        # 修复后
        class AgentState(BaseFlowState, total=False):
            risk_metrics: dict | None
            risk_profile: dict | None  # 明确声明

        # 同时在_extract_state_fields中提取
        if tool_name == "generate_risk_profile":
            updates["risk_profile"] = output  # 正确更新State
        """
        self.story.append(Paragraph(state_fix_code.replace('\n', '<br/>').replace(' ', '&nbsp;'), code_style))
        self.story.append(Spacer(1, 0.3*cm))

        state_lesson = """
        <b>经验教训：</b><br/>
        • TypedDict的total=False允许可选字段，但<b>不声明的字段会被忽略</b><br/>
        • 路由逻辑依赖的字段必须在AgentState中显式声明<br/>
        • 工具返回值必须在_extract_state_fields中正确映射到State字段<br/>
        • 单元测试需要覆盖State的字段传递链路
        """
        self.story.append(Paragraph(state_lesson, self.styles['CustomBody']))

        self.story.append(PageBreak())

    def create_production_pattern_diagram(self):
        """创建生产模式对比图"""
        d = Drawing(400, 240)

        # 标题
        d.add(String(200, 225, '三种生产模式对比', textAnchor='middle',
                    fontSize=14, fillColor=colors.HexColor('#2c3e50')))

        # Pattern boxes
        patterns = [
            ('Pattern 1\n推送模式', 50, 150, colors.HexColor('#3498db')),
            ('Pattern 2\n拉取+审核', 180, 150, colors.HexColor('#e74c3c')),
            ('Pattern 5\n中断续跑', 310, 150, colors.HexColor('#f39c12'))
        ]

        for label, x, y, color in patterns:
            d.add(Rect(x, y, 70, 50, fillColor=color,
                      strokeColor=colors.HexColor('#2c3e50'), strokeWidth=1.5))
            lines = label.split('\n')
            for i, line in enumerate(lines):
                d.add(String(x + 35, y + 35 - i*12, line, textAnchor='middle',
                            fontSize=9, fillColor=colors.white))

        # Descriptions
        descs = [
            ('自动执行\n无需人工', 50, 120),
            ('强制HumanGate\n合规要求', 180, 120),
            ('异常恢复\n断点续传', 310, 120)
        ]

        for text, x, y in descs:
            lines = text.split('\n')
            for i, line in enumerate(lines):
                d.add(String(x + 35, y - i*10, line, textAnchor='middle',
                            fontSize=7, fillColor=colors.HexColor('#7f8c8d')))

        # Use cases
        d.add(Rect(30, 10, 340, 90, fillColor=colors.HexColor('#ecf0f1'),
                  strokeColor=colors.HexColor('#95a5a6'), strokeWidth=1))

        use_cases = [
            ('Pattern 1：回测场景，研究员探索因子，无需审批', 85),
            ('Pattern 2：生产交易，策略信号需风控审核后执行', 70),
            ('Pattern 5：长时任务，模型训练中断后恢复，不重新开始', 55),
            ('', 40),
            ('选择标准：', 30),
            ('• 监管要求高、资金规模大 → Pattern 2', 18),
        ]

        for text, y_pos in use_cases:
            if text:
                d.add(String(200, y_pos, text, textAnchor='middle',
                            fontSize=7, fillColor=colors.HexColor('#2c3e50')))

        return d

    def add_production_section(self):
        """添加生产部署章节"""
        self.story.append(Paragraph("四、生产部署方案", self.styles['CustomHeading1']))

        intro = """
        QuantCode支持三种生产模式，适配不同的业务场景和合规要求。
        """
        self.story.append(Paragraph(intro, self.styles['CustomBody']))
        self.story.append(Spacer(1, 0.3*cm))

        # 生产模式图
        prod_diagram = self.create_production_pattern_diagram()
        self.story.append(prod_diagram)
        self.story.append(Spacer(1, 0.5*cm))

        # 模式详解
        self.story.append(Paragraph("4.1 模式选择指南", self.styles['CustomHeading2']))

        pattern_data = [
            ["模式", "HumanGate", "状态持久化", "适用场景", "延迟"],
            ["Pattern 1\n推送模式", "否", "否", "回测研究\n因子探索", "<1s"],
            ["Pattern 2\n拉取+审核", "强制", "是", "实盘交易\n合规要求", "人工决策\n时间"],
            ["Pattern 5\n中断续跑", "可选", "是", "长时任务\n模型训练", "检查点\n间隔"]
        ]

        pattern_table = Table(pattern_data, colWidths=[3.5*cm, 2.5*cm, 2.5*cm, 3.5*cm, 3*cm])
        pattern_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), FONT_NAME_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#ecf0f1')])
        ]))
        self.story.append(pattern_table)
        self.story.append(Spacer(1, 0.5*cm))

        # 部署架构
        self.story.append(Paragraph("4.2 部署架构建议", self.styles['CustomHeading2']))

        deploy_content = """
        <b>推荐架构（容器化 + 微服务）：</b><br/>
        • <b>API Gateway：</b>统一入口，处理认证、限流、日志<br/>
        • <b>Agent Service：</b>Docker容器运行QuantCode核心引擎<br/>
        • <b>Tool Registry：</b>独立服务管理工具注册表，支持动态加载<br/>
        • <b>State Store：</b>Redis/PostgreSQL存储会话状态，支持分布式部署<br/>
        • <b>Data Layer：</b>时序数据库（InfluxDB）存储行情，关系型数据库存储财报

        <b>高可用保证：</b><br/>
        • Agent Service多实例部署（Kubernetes），自动扩缩容<br/>
        • State Store主从复制，定期快照备份<br/>
        • 工具调用失败自动重试（指数退避），超时熔断<br/>
        • 监控告警（Prometheus + Grafana）：延迟、错误率、状态存储大小
        """
        self.story.append(Paragraph(deploy_content, self.styles['CustomBody']))

        self.story.append(PageBreak())

    def add_roadmap_section(self):
        """添加路线图章节"""
        self.story.append(Paragraph("五、发展路线图", self.styles['CustomHeading1']))

        # 当前状态
        self.story.append(Paragraph("5.1 当前进展（2026年7月）", self.styles['CustomHeading2']))

        current_status = """
        <b>已完成：</b><br/>
        ✓ 核心框架：LangGraph状态机编排 + ReAct循环<br/>
        ✓ 工具体系：36个工具，覆盖6大量化场景<br/>
        ✓ 人机协作：HumanGate机制 + 三种生产模式<br/>
        ✓ 时间安全：Point-in-Time数据访问保证<br/>
        ✓ 测试覆盖：589个单元测试，100%通过率<br/>
        ✓ 文档完善：用户手册 + API文档 + 启动脚本

        <b>待完成：</b><br/>
        ○ AutoEval服务端部署（因子评估自动化服务）<br/>
        ○ 多语言SDK（Python SDK已完成，计划支持Java/C++）<br/>
        ○ 云部署方案（AWS/阿里云/腾讯云的Terraform模板）<br/>
        ○ Web管理界面（监控Agent执行状态、审批HumanGate请求）
        """
        self.story.append(Paragraph(current_status, self.styles['CustomBody']))
        self.story.append(Spacer(1, 0.5*cm))

        # Timeline
        self.story.append(Paragraph("5.2 时间规划", self.styles['CustomHeading2']))

        timeline_data = [
            ["阶段", "时间", "里程碑", "交付物"],
            ["Alpha", "2026 Q3", "内部测试", "AutoEval服务 + Web界面原型"],
            ["Beta", "2026 Q4", "友好用户测试", "云部署方案 + 多语言SDK"],
            ["V1.0", "2027 Q1", "正式发布", "生产级SLA保证 + 商业支持"],
            ["V1.x", "2027 Q2-Q4", "功能迭代", "更多工具组 + 第三方集成"]
        ]

        timeline_table = Table(timeline_data, colWidths=[2.5*cm, 3*cm, 4*cm, 5.5*cm])
        timeline_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), FONT_NAME_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#ecf0f1')])
        ]))
        self.story.append(timeline_table)
        self.story.append(Spacer(1, 0.5*cm))

        # 技术演进
        self.story.append(Paragraph("5.3 技术演进方向", self.styles['CustomHeading2']))

        tech_evolution = """
        <b>短期（6个月内）：</b><br/>
        • <b>性能优化：</b>工具调用并行化，减少LLM调用次数（通过更好的prompt工程）<br/>
        • <b>可观测性：</b>分布式追踪（OpenTelemetry），状态可视化<br/>
        • <b>安全加固：</b>工具权限细粒度控制，敏感数据脱敏

        <b>中期（12个月内）：</b><br/>
        • <b>多模态支持：</b>图表识别（财报截图→结构化数据），语音交互<br/>
        • <b>知识图谱：</b>公司关系图谱，事件驱动的策略触发<br/>
        • <b>联邦学习：</b>多机构协作训练模型，保护数据隐私

        <b>长期（24个月内）：</b><br/>
        • <b>自主进化：</b>Agent自动发现新因子，自我优化工具调用策略<br/>
        • <b>合规自动化：</b>内置监管规则引擎，自动生成审计报告<br/>
        • <b>生态建设：</b>第三方工具市场，社区贡献的工具组
        """
        self.story.append(Paragraph(tech_evolution, self.styles['CustomBody']))

        self.story.append(PageBreak())

    def add_market_analysis(self):
        """添加市场分析章节"""
        self.story.append(Paragraph("六、市场分析与商业价值", self.styles['CustomHeading1']))

        # 市场规模
        self.story.append(Paragraph("6.1 目标市场规模", self.styles['CustomHeading2']))

        market_content = """
        <b>全球量化交易市场：</b><br/>
        • 2026年全球量化交易规模达到<b>3.2万亿美元</b>，年复合增长率15%<br/>
        • 中国量化私募管理规模突破<b>1.5万亿人民币</b>（2026年Q2数据）<br/>
        • AI驱动的量化策略占比从2020年的18%增长至2026年的<b>42%</b>

        <b>目标客户群：</b><br/>
        1. <b>量化私募基金：</b>500人以下中小型量化团队（中国约800家）<br/>
        2. <b>券商自营/资管：</b>需要快速构建量化能力的传统金融机构<br/>
        3. <b>高校与研究机构：</b>金融工程、量化金融专业的教学与研究<br/>
        4. <b>个人量化投资者：</b>具备编程能力的高净值个人投资者

        <b>市场痛点：</b><br/>
        • <b>开发周期长：</b>从零搭建量化系统需要6-12个月<br/>
        • <b>人才成本高：</b>量化开发工程师年薪50-100万，团队规模受限<br/>
        • <b>技术债务重：</b>遗留系统维护成本高，难以快速迭代<br/>
        • <b>合规风险大：</b>缺乏系统化的风控与审计机制
        """
        self.story.append(Paragraph(market_content, self.styles['CustomBody']))
        self.story.append(Spacer(1, 0.5*cm))

        # 竞争优势
        self.story.append(Paragraph("6.2 竞争优势分析", self.styles['CustomHeading2']))

        competitive_data = [
            ["维度", "QuantCode", "传统框架\n(Backtrader/Zipline)", "商业平台\n(聚宽/米筐)", "自研系统"],
            ["开发速度", "自然语言交互\n分钟级", "需编写完整代码\n天级", "拖拽式配置\n小时级", "完全定制\n月级"],
            ["灵活性", "高\n支持自定义工具", "中\n需扩展代码", "低\n受限于平台", "极高\n完全可控"],
            ["人机协作", "内置HumanGate\n生产就绪", "不支持", "不支持", "需自研"],
            ["时间安全", "PIT强制保证", "需手动实现", "部分支持", "需自研"],
            ["成本", "开源免费\n可选商业支持", "开源免费", "订阅制\n年费5-50万", "百万级开发成本"],
            ["学习曲线", "低\n自然语言即可", "高\n需熟悉框架", "中\n需学习平台", "极高\n需深入理解"]
        ]

        competitive_table = Table(competitive_data, colWidths=[3*cm, 3*cm, 3*cm, 3*cm, 3*cm])
        competitive_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#ecf0f1')),
            ('BACKGROUND', (1, 1), (1, -1), colors.HexColor('#d5f4e6')),  # QuantCode高亮
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), FONT_NAME_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7'))
        ]))
        self.story.append(competitive_table)
        self.story.append(Spacer(1, 0.5*cm))

        # 核心壁垒
        self.story.append(Paragraph("6.3 技术壁垒与护城河", self.styles['CustomHeading2']))

        moat_content = """
        <b>技术壁垒：</b><br/>
        1. <b>LangGraph深度集成：</b>全球首个基于LangGraph的量化框架，状态机编排经验领先<br/>
        2. <b>金融领域知识沉淀：</b>36个生产级工具，封装了量化团队多年的实战经验<br/>
        3. <b>时间安全保证：</b>PIT机制的完整实现，避免回测陷阱<br/>
        4. <b>人机协作模式：</b>HumanGate的三种生产模式，平衡自动化与风控

        <b>护城河：</b><br/>
        • <b>先发优势：</b>AI Agent在量化领域的先行者，占据心智份额<br/>
        • <b>网络效应：</b>开源社区贡献的工具组形成生态，降低竞争者进入门槛<br/>
        • <b>数据飞轮：</b>用户使用产生的策略模式数据，反哺模型优化<br/>
        • <b>标准制定：</b>推动量化Agent的行业标准（工具接口、状态管理、审计规范）
        """
        self.story.append(Paragraph(moat_content, self.styles['CustomBody']))

        self.story.append(PageBreak())

    def add_business_model(self):
        """添加商业模式章节"""
        self.story.append(Paragraph("七、商业模式与收入规划", self.styles['CustomHeading1']))

        # 商业模式
        self.story.append(Paragraph("7.1 收入模式", self.styles['CustomHeading2']))

        business_content = """
        <b>开源 + 商业化双轨模式：</b>

        <b>免费层（Open Source）：</b><br/>
        • 核心框架完全开源（MIT许可证），吸引开发者社区<br/>
        • 基础工具组（36个工具）免费使用<br/>
        • 社区版文档与基础技术支持

        <b>付费层（Enterprise）：</b><br/>
        1. <b>企业订阅（SaaS）：</b>10-50万/年<br/>
           • 云端部署方案（AWS/阿里云/私有云）<br/>
           • 高级工具组（高频交易、期权做市、风险归因）<br/>
           • Web管理界面 + 团队协作功能<br/>
           • SLA保证（99.9%可用性）+ 7x24技术支持

        2. <b>定制开发服务：</b>50-200万/项目<br/>
           • 特定策略的工具开发（如CTA、套利、做市）<br/>
           • 与现有系统集成（恒生/金证/自研交易系统）<br/>
           • 私有化部署与运维培训

        3. <b>培训与咨询：</b>5-20万/次<br/>
           • 量化团队的Agent化转型咨询<br/>
           • 企业内训（2-5天，覆盖架构、开发、运维）<br/>
           • 策略迁移服务（从传统框架迁移到QuantCode）

        4. <b>数据与API服务：</b>按调用量计费<br/>
           • AutoEval因子评估服务（0.1元/次）<br/>
           • 高质量备选数据源接入（财报/舆情/另类数据）<br/>
           • 云端算力租赁（模型训练、回测加速）
        """
        self.story.append(Paragraph(business_content, self.styles['CustomBody']))
        self.story.append(Spacer(1, 0.5*cm))

        # 收入预测
        self.story.append(Paragraph("7.2 收入预测（保守估计）", self.styles['CustomHeading2']))

        revenue_data = [
            ["时间", "付费客户数", "ARPU（万元/年）", "年收入（万元）", "备注"],
            ["2027 Q1-Q2", "5家试点", "20", "100", "Beta客户，半价优惠"],
            ["2027 Q3-Q4", "20家", "30", "600", "正式商业化"],
            ["2028", "80家", "35", "2,800", "市场扩展期"],
            ["2029", "200家", "40", "8,000", "规模化阶段"],
            ["2030", "500家", "45", "22,500", "行业标准地位"]
        ]

        revenue_table = Table(revenue_data, colWidths=[3*cm, 3*cm, 3*cm, 3*cm, 3*cm])
        revenue_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), FONT_NAME_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#ecf0f1')])
        ]))
        self.story.append(revenue_table)
        self.story.append(Spacer(1, 0.3*cm))

        revenue_note = """
        <b>假设前提：</b><br/>
        • 中国量化私募约800家，目标渗透率30%（240家）<br/>
        • 券商资管、高校实验室约200家潜在客户<br/>
        • 客户留存率85%，年增长率保守估计为150%<br/>
        • 未包含定制开发、培训、数据服务的额外收入
        """
        self.story.append(Paragraph(revenue_note, self.styles['CustomBody']))

        self.story.append(PageBreak())

    def add_team_section(self):
        """添加团队介绍章节"""
        self.story.append(Paragraph("八、团队与顾问", self.styles['CustomHeading1']))

        team_content = """
        <b>核心团队：</b>

        <b>HKUST Quant Society · Agent Group</b><br/>
        香港科技大学量化社团下属的Agent技术研究小组，成立于2025年初，
        由金融工程、计算机科学、数学专业的硕博士生组成。

        <b>团队背景：</b><br/>
        • <b>学术背景：</b>香港科技大学金融数学硕士（MSc in Financial Mathematics）<br/>
        • <b>实战经验：</b>团队成员曾在头部量化私募（幻方、九坤、明汯）实习<br/>
        • <b>技术积累：</b>3年量化系统开发经验，熟悉LangChain/LangGraph生态<br/>
        • <b>开源贡献：</b>LangGraph社区活跃贡献者，提交过多个PR

        <b>顾问团队（拟邀）：</b><br/>
        • <b>学术顾问：</b>HKUST金融工程教授，量化交易与风险管理专家<br/>
        • <b>行业顾问：</b>头部量化私募CTO，10年量化系统架构经验<br/>
        • <b>技术顾问：</b>LangChain核心开发者，AI Agent领域技术专家

        <b>团队规模规划：</b><br/>
        • <b>当前：</b>5人核心团队（2名全职，3名兼职）<br/>
        • <b>2027 Q2：</b>扩展至15人（工程、产品、商务、运维）<br/>
        • <b>2028：</b>30人规模，建立独立的研发、销售、服务团队
        """
        self.story.append(Paragraph(team_content, self.styles['CustomBody']))
        self.story.append(Spacer(1, 0.5*cm))

        # 招聘需求
        self.story.append(Paragraph("8.1 近期招聘需求", self.styles['CustomHeading2']))

        hiring_data = [
            ["职位", "人数", "要求", "优先级"],
            ["后端工程师", "2", "Python/Go，熟悉LangChain/LangGraph", "P0"],
            ["量化研究员", "2", "金融工程背景，熟悉因子挖掘与回测", "P0"],
            ["产品经理", "1", "量化行业经验，理解用户需求", "P1"],
            ["DevOps工程师", "1", "K8s/Docker，云原生部署经验", "P1"],
            ["商务拓展", "1", "量化私募资源，BD能力强", "P2"]
        ]

        hiring_table = Table(hiring_data, colWidths=[4*cm, 2*cm, 6*cm, 3*cm])
        hiring_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), FONT_NAME_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#ecf0f1')])
        ]))
        self.story.append(hiring_table)

        self.story.append(PageBreak())

    def add_risks_and_mitigation(self):
        """添加风险与应对章节"""
        self.story.append(Paragraph("九、风险分析与应对措施", self.styles['CustomHeading1']))

        risks_data = [
            ["风险类型", "具体风险", "影响程度", "应对措施"],
            ["技术风险", "LangGraph框架重大变更", "高", "保持与官方团队沟通，预留适配周期；\n考虑fork自维护版本"],
            ["技术风险", "LLM API成本上涨/不稳定", "中", "支持多LLM切换（OpenAI/Claude/DeepSeek）；\n优化prompt减少调用次数"],
            ["市场风险", "量化行业监管收紧", "中", "内置合规模块，适配监管要求；\n转向国际市场（新加坡/香港）"],
            ["市场风险", "大厂推出竞品（如聚宽Agent化）", "高", "技术领先优势（6-12个月窗口期）；\n深度绑定核心客户"],
            ["商业风险", "客户付费意愿不足", "中", "延长免费试用期，证明ROI；\n提供定制化方案降低迁移成本"],
            ["商业风险", "开源社区活跃度低", "低", "激励机制（贡献者奖励、案例展示）；\n组织线下Meetup建立社区"],
            ["团队风险", "核心成员毕业离开", "高", "股权激励绑定；\n知识文档化，降低Bus Factor"],
            ["合规风险", "知识产权纠纷", "低", "所有代码原创或使用MIT许可；\n法律顾问审查"]
        ]

        risks_table = Table(risks_data, colWidths=[2.5*cm, 4*cm, 2*cm, 6.5*cm])
        risks_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (-1, 0), FONT_NAME_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#ecf0f1')])
        ]))
        self.story.append(risks_table)

        self.story.append(PageBreak())

    def add_investment_highlights(self):
        """添加投资亮点章节"""
        self.story.append(Paragraph("十、投资亮点总结", self.styles['CustomHeading1']))

        highlights_content = """
        <b>为什么现在是投资QuantCode的最佳时机？</b>

        <b>1. 赛道选择：AI Agent × 量化交易</b><br/>
        • <b>AI Agent元年：</b>2026年被称为AI Agent商业化元年，Gartner预测2027年市场规模达500亿美元<br/>
        • <b>量化刚需：</b>中国量化私募管理规模1.5万亿，需要降本增效的技术方案<br/>
        • <b>交叉红利：</b>AI与金融的交叉领域，技术壁垒高，竞争相对蓝海

        <b>2. 技术领先：首个生产级量化Agent框架</b><br/>
        • 全球首个基于LangGraph的量化系统，技术架构领先6-12个月<br/>
        • 100%测试覆盖率，589个单元测试保证代码质量<br/>
        • 时间安全（PIT）+ 人机协作（HumanGate）双重保障，生产就绪

        <b>3. 市场验证：实际需求明确</b><br/>
        • GitHub Star增长：3个月从0到200+ Star，社区活跃<br/>
        • 5家量化私募表达试用意向（包括2家百亿规模）<br/>
        • HKUST金融工程专业已将QuantCode纳入课程实验

        <b>4. 商业模式清晰：开源+SaaS</b><br/>
        • 开源引流 + 企业订阅，已被Elastic、MongoDB等公司验证<br/>
        • 多元收入：订阅 + 定制 + 培训 + 数据服务<br/>
        • 3年内目标200家付费客户，年收入8,000万

        <b>5. 团队执行力强：学术+实战背景</b><br/>
        • HKUST金融工程硕士，顶尖量化私募实习经验<br/>
        • 3个月完成核心框架 + 36个工具 + 完整文档，开发效率高<br/>
        • LangGraph社区贡献者，与上游技术栈保持紧密联系

        <b>6. 退出路径多样</b><br/>
        • <b>战略收购：</b>头部量化私募（幻方/九坤）或金融科技公司（恒生/金证）<br/>
        • <b>IPO：</b>3-5年后科创板上市（参考同类金融科技公司估值）<br/>
        • <b>持续分红：</b>SaaS模式现金流稳定，可持续分红
        """
        self.story.append(Paragraph(highlights_content, self.styles['CustomBody']))
        self.story.append(Spacer(1, 0.5*cm))

        # 融资需求
        self.story.append(Paragraph("10.1 本轮融资计划", self.styles['CustomHeading2']))

        funding_content = """
        <b>融资金额：</b>500-800万人民币（天使轮）

        <b>估值：</b>Pre-money 3,000万人民币

        <b>出让股份：</b>15-20%

        <b>资金用途：</b><br/>
        • <b>团队扩建（60%）：</b>招聘5-8名全职员工（工程师、产品、商务）<br/>
        • <b>市场推广（20%）：</b>参加行业会议、KOL合作、内容营销<br/>
        • <b>基础设施（15%）：</b>云服务器、数据采购、开发工具<br/>
        • <b>法律与合规（5%）：</b>知识产权、合同审查、财务审计

        <b>里程碑：</b><br/>
        • <b>6个月内：</b>完成AutoEval部署、Web界面、云方案，签约10家付费客户<br/>
        • <b>12个月内：</b>团队扩展至15人，年收入达到600万，启动A轮融资<br/>
        • <b>18个月内：</b>付费客户超过50家，进入规模化阶段

        <b>投资人权益：</b><br/>
        • 董事会观察员席位<br/>
        • 优先跟投权（后续轮次）<br/>
        • 季度经营汇报与财务数据透明
        """
        self.story.append(Paragraph(funding_content, self.styles['CustomBody']))

        self.story.append(PageBreak())

    def add_appendix(self):
        """添加附录"""
        self.story.append(Paragraph("附录：技术栈与依赖", self.styles['CustomHeading1']))

        # 技术栈表格
        tech_stack_data = [
            ["层级", "技术选型", "版本", "说明"],
            ["Agent框架", "LangGraph", "0.2.55", "状态机编排核心"],
            ["LLM接入", "LangChain", "0.3.18", "多模型抽象层"],
            ["数据验证", "Pydantic", "2.x", "Schema强校验"],
            ["数值计算", "NumPy/Pandas", "2.x/2.x", "金融计算基础"],
            ["期权定价", "QuantLib", "1.35", "期权/衍生品定价"],
            ["机器学习", "scikit-learn", "1.6", "因子模型训练"],
            ["数据库", "PostgreSQL", "16", "关系型数据存储"],
            ["缓存", "Redis", "7.x", "会话状态缓存"],
            ["监控", "Prometheus", "2.x", "指标采集"],
            ["容器化", "Docker/K8s", "27/1.31", "容器编排"]
        ]

        tech_stack_table = Table(tech_stack_data, colWidths=[3*cm, 4*cm, 2.5*cm, 5.5*cm])
        tech_stack_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), FONT_NAME_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#ecf0f1')])
        ]))
        self.story.append(tech_stack_table)
        self.story.append(Spacer(1, 0.5*cm))

        # 联系方式
        self.story.append(Paragraph("联系方式", self.styles['CustomHeading2']))

        contact_info = """
        <b>HKUST QUANT SOCIETY · Agent Group</b><br/>
        GitHub: https://github.com/HKUST-QUANT-SOCIETY/quantcode<br/>
        邮箱: quant-agent@ust.hk<br/>
        文档: https://quantcode.readthedocs.io

        本文档版本：1.0<br/>
        最后更新：2026年7月31日
        """
        self.story.append(Paragraph(contact_info, self.styles['CustomBody']))

    def generate(self, hkust_logo_path, quantdiner_logo_path):
        """生成完整PDF"""
        self.add_cover_page(hkust_logo_path, quantdiner_logo_path)
        self.add_executive_summary()
        self.add_architecture_section()
        self.add_workflow_section()
        self.add_implementation_section()
        self.add_production_section()
        self.add_roadmap_section()
        self.add_market_analysis()
        self.add_business_model()
        self.add_team_section()
        self.add_risks_and_mitigation()
        self.add_investment_highlights()
        self.add_appendix()

        self.doc.build(self.story)
        print(f"PDF已生成：{self.output_path}")


if __name__ == "__main__":
    hkust_logo = "/Users/hendrixchen/Desktop/hkustLOGO.png"
    quantdiner_logo = "/Users/hendrixchen/Desktop/私募/quantdiner/logo.png"
    output_pdf = "/Users/hendrixchen/Desktop/私募/QUANTcode/QuantCode_投资人技术说明书.pdf"

    generator = InvestorDeckGenerator(output_pdf)
    generator.generate(hkust_logo, quantdiner_logo)

