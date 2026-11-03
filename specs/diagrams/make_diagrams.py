"""生成闭环流程图与组件架构图（Pillow 绘制，无需外部渲染器）。

用法： python make_diagrams.py
输出： closed-loop-flow.png / architecture.png （与本脚本同目录）
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"

INK = (32, 38, 48)
MUTED = (108, 118, 133)
LINE = (146, 156, 170)
WHITE = (255, 255, 255)

FILL_APP, EDGE_APP = (232, 241, 255), (72, 128, 210)
FILL_SRV, EDGE_SRV = (230, 247, 239), (44, 142, 98)
FILL_EXP, EDGE_EXP = (255, 242, 228), (198, 130, 40)
FILL_TRAIN, EDGE_TRAIN = (242, 235, 255), (120, 84, 190)
FILL_NEW, EDGE_NEW = (255, 235, 235), (200, 70, 70)
FILL_OK, EDGE_OK = (232, 247, 235), (58, 150, 96)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def box(d, cx, cy, w, h, lines, fill, edge, size=22, badge=None, badge_fill=None, badge_edge=None):
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    d.rounded_rectangle([x0, y0, x1, y1], radius=14, fill=fill, outline=edge, width=2)
    fonts = [font(size, i == 0) for i in range(len(lines))]
    total = sum(f.size + 7 for f in fonts) - 7
    y = cy - total / 2
    for text, f in zip(lines, fonts):
        d.text((cx, y + f.size / 2), text, font=f, fill=INK, anchor="mm")
        y += f.size + 7
    if badge:
        bf = badge_fill or FILL_NEW
        be = badge_edge or EDGE_NEW
        bw = d.textlength(badge, font=font(15, True)) + 16
        d.rounded_rectangle([x1 - bw - 6, y0 - 12, x1 - 6, y0 + 12], radius=8, fill=be, outline=be)
        d.text((x1 - bw / 2 - 6, y0), badge, font=font(15, True), fill=WHITE, anchor="mm")


def _head(d, tip, frm, color):
    angle = math.atan2(tip[1] - frm[1], tip[0] - frm[0])
    size = 11
    d.polygon([
        tip,
        (tip[0] - size * math.cos(angle - 0.42), tip[1] - size * math.sin(angle - 0.42)),
        (tip[0] - size * math.cos(angle + 0.42), tip[1] - size * math.sin(angle + 0.42)),
    ], fill=color)


def label(d, x, y, text, size=19):
    f = font(size)
    tw = d.textlength(text, font=f)
    d.rounded_rectangle([x - tw / 2 - 7, y - f.size / 2 - 3, x + tw / 2 + 7, y + f.size / 2 + 3],
                        radius=6, fill=WHITE)
    d.text((x, y), text, font=f, fill=MUTED, anchor="mm")


def ortho(d, points, text=None, at=None, dashed=False, color=LINE):
    """按给定折点画直角折线，末端加箭头。"""
    for i in range(len(points) - 1):
        (x1, y1), (x2, y2) = points[i], points[i + 1]
        if dashed:
            length = math.dist((x1, y1), (x2, y2))
            steps = max(1, int(length // 12))
            for s in range(steps):
                if s % 2:
                    continue
                t0, t1 = s / steps, (s + 1) / steps
                d.line([(x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0),
                        (x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1)], fill=color, width=2)
        else:
            d.line([(x1, y1), (x2, y2)], fill=color, width=2)
    _head(d, points[-1], points[-2], color)
    if text:
        lx, ly = at or points[0]
        label(d, lx, ly, text)


def lane(d, x0, y0, x1, y1, title, color, title_outside=False):
    d.rounded_rectangle([x0, y0, x1, y1], radius=16, outline=color, width=2)
    if title_outside:
        d.text((x0 + 4, y0 - 24), title, font=font(20, True), fill=color, anchor="la")
    else:
        d.text((x0 + 16, y0 + 12), title, font=font(20, True), fill=color, anchor="la")


def closed_loop() -> Path:
    W, H = 1620, 1330
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    d.text((W / 2, 36), "柑橘病虫害识别 · 端到端闭环流程", font=font(34, True), fill=INK, anchor="mm")
    d.text((W / 2, 74), "红色 = 本次新增的服务端能力；虚线 = 异步或回溯路径",
           font=font(18), fill=MUTED, anchor="mm")

    lane(d, 40, 104, 512, 900, "① 农民端（Android）", EDGE_APP)
    lane(d, 570, 104, 1100, 900, "② 服务端（API + 推理 + 存储）", EDGE_SRV)
    lane(d, 1150, 560, 1580, 900, "③ 专家端（Web 管理端）", EDGE_EXP, title_outside=True)
    lane(d, 40, 950, 1580, 1300, "④ 数据闭环（训练与迭代）", EDGE_TRAIN)

    ax, bx, cx = 280, 830, 1360

    box(d, ax, 190, 400, 84, ["拍摄 / 选择照片", "填写作物、品种、部位、树龄"], FILL_APP, EDGE_APP)
    box(d, ax, 330, 400, 84, ["本地草稿 + 上传队列", "离线可用 · 失败自动重试"], FILL_APP, EDGE_APP)
    box(d, ax, 730, 400, 84, ["查看处置建议 / 专家结论", "同一张照片的最终结果"], FILL_APP, EDGE_APP)

    box(d, bx, 330, 470, 84, ["叶片闸门（YOLO 检测）", "判断画面里有没有叶片"], FILL_SRV, EDGE_SRV)
    box(d, bx, 430, 470, 84, ["五分类识别（EfficientNet-B0）", "常驻推理服务 · 单张约 0.6s"], FILL_SRV, EDGE_SRV)
    box(d, bx, 530, 470, 92, ["落库：Observation + InferenceRun", "模型版本 · Top-K · 置信度 · 耗时"],
        FILL_NEW, EDGE_NEW, badge="新增")
    box(d, bx, 630, 470, 84, ["能否给出处置建议？", "置信度 / 类别映射 / 知识命中"], FILL_SRV, EDGE_SRV)
    box(d, bx, 730, 470, 76, ["返回处置建议（知识库本期为空）", "占位：接口与表结构已就位"], FILL_SRV, EDGE_SRV, size=21)

    box(d, cx, 630, 400, 88, ["识别记录 / 工单队列", "低置信度 · 未映射 · 用户求助"], FILL_EXP, EDGE_EXP, size=21)
    box(d, cx, 720, 400, 88, ["复核：定类别 + 写说明", "农业局专家（expert 角色）"], FILL_EXP, EDGE_EXP, size=21)
    box(d, cx, 810, 400, 88, ["结论回写 Observation", "状态 → reviewed"], FILL_EXP, EDGE_EXP, size=21)

    box(d, 220, 1040, 340, 92, ["训练授权开关（每张图）", "默认关闭 · 可事后撤回"],
        FILL_TRAIN, EDGE_TRAIN, size=21, badge="新增")
    box(d, 640, 1040, 340, 92, ["训练集筛选", "consent=true 且 已核验"], FILL_TRAIN, EDGE_TRAIN,
        size=21, badge="新增")
    box(d, 1060, 1040, 340, 92, ["导出样本包", "原图 + 标签 + 来源"], FILL_TRAIN, EDGE_TRAIN, size=21)
    box(d, 1400, 1040, 280, 92, ["模型迭代", "训练 / 评估 / 灰度"], FILL_TRAIN, EDGE_TRAIN, size=21)
    box(d, 810, 1200, 700, 84, ["抽查与指标", "随机抽样复核 · 准确率 · 类别分布 · 失败聚集"],
        FILL_TRAIN, EDGE_TRAIN, size=20)

    # 主链路
    ortho(d, [(ax, 232), (ax, 288)], "上传", at=(ax + 46, 260))
    ortho(d, [(ax + 200, 330), (bx - 235, 330)], "提交识别", at=(537, 330))
    ortho(d, [(bx, 372), (bx, 388)])
    ortho(d, [(bx, 472), (bx, 484)])
    ortho(d, [(bx, 576), (bx, 588)])
    ortho(d, [(bx, 672), (bx, 692)], "是：可给建议", at=(bx + 105, 682))
    ortho(d, [(bx - 235, 730), (ax + 200, 730)], "返回建议", at=(537, 730))

    # 分支
    ortho(d, [(bx - 235, 330), (540, 330), (540, 190), (ax + 200, 190)],
          "无叶片 → 提示重拍", at=(540, 262), dashed=True)
    ortho(d, [(bx + 235, 630), (cx - 200, 630)], "否：转专家", at=(1125, 610))
    ortho(d, [(cx, 674), (cx, 676)])
    ortho(d, [(cx, 764), (cx, 766)])
    ortho(d, [(cx - 200, 810), (1125, 810), (1125, 530), (bx + 235, 530)],
          "回写结论", at=(1125, 700))
    # 专家结论 → 农民可见（沿三条泳道底部）
    ortho(d, [(cx, 854), (cx, 880), (ax, 880), (ax, 772)],
          "农民可见专家结论", at=(820, 880), dashed=True)

    # 数据闭环
    ortho(d, [(ax, 772), (ax, 994)], "逐张授权", at=(ax + 70, 955))
    ortho(d, [(cx - 60, 854), (cx - 60, 925), (700, 925), (700, 994)],
          "已核验 + 已授权样本", at=(1030, 925), dashed=True)
    ortho(d, [(390, 1040), (470, 1040)])
    ortho(d, [(810, 1040), (890, 1040)])
    ortho(d, [(1230, 1040), (1260, 1040)], "训练", at=(1245, 1022))
    ortho(d, [(1400, 994), (1600, 994), (1600, 430), (bx + 235, 430)],
          "灰度上线 / 下一轮", at=(1470, 430), dashed=True)
    ortho(d, [(1060, 1086), (1060, 1158)], dashed=True)

    out = HERE / "closed-loop-flow.png"
    img.save(out)
    return out


def architecture() -> Path:
    W, H = 1620, 1000
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    d.text((W / 2, 38), "系统组件与数据流", font=font(34, True), fill=INK, anchor="mm")
    d.text((W / 2, 76), "红色 = 本次新增；绿色徽标 = 已上线能力",
           font=font(18), fill=MUTED, anchor="mm")

    def band(y0, y1, title):
        d.rounded_rectangle([40, y0, W - 40, y1], radius=14, outline=(225, 229, 236), width=2)
        d.text((58, y0 + 10), title, font=font(18, True), fill=MUTED, anchor="la")

    band(104, 240, "客户端")
    band(262, 392, "接入层")
    band(414, 714, "应用层（FastAPI，单进程）")
    band(740, 940, "数据层")

    box(d, 390, 178, 560, 88, ["Android App（农民端）",
                               "拍照 / 离线草稿 / 上传队列 / 训练授权"], FILL_APP, EDGE_APP, size=21)
    box(d, 1230, 178, 560, 88, ["Web 管理端（Vue）",
                                "专家队列 / 抽查 / 导出 / 知识库占位"], FILL_EXP, EDGE_EXP, size=21)

    box(d, 810, 333, 800, 76, ["Nginx 网关",
                               "TLS · 限流 · gzip · 媒体缓存 · 真实 IP 还原"], FILL_SRV, EDGE_SRV, size=20)

    box(d, 270, 500, 380, 110, ["认证与账号", "手机号登录", "会话 · 角色"], FILL_SRV, EDGE_SRV, size=20)
    box(d, 810, 500, 420, 110, ["观察记录模块", "Observation 状态机", "批次上下文 · 幂等"],
        FILL_NEW, EDGE_NEW, size=20, badge="新增")
    box(d, 1330, 500, 420, 110, ["复核 / 导出模块", "转办工单 · 训练集筛选", "抽查与指标"],
        FILL_SRV, EDGE_SRV, size=20)
    box(d, 810, 640, 600, 80, ["推理守护进程（systemd 常驻）", "YOLO 闸门 + 五分类 · Unix socket"],
        FILL_OK, EDGE_OK, size=19, badge="已上线", badge_edge=EDGE_OK)

    box(d, 300, 840, 420, 96, ["PostgreSQL", "observations · inference_runs", "review_case · knowledge_entry"],
        FILL_TRAIN, EDGE_TRAIN, size=19)
    box(d, 1300, 840, 460, 96, ["文件存储（可替换为 OSS）", "原图 / 预览 / 导出 ZIP"],
        FILL_TRAIN, EDGE_TRAIN, size=19)

    ortho(d, [(390, 222), (390, 258), (620, 258), (620, 295)])
    ortho(d, [(1230, 222), (1230, 258), (1000, 258), (1000, 295)])

    # 网关 → 应用层（总线式分发）
    d.line([(810, 371), (810, 410)], fill=LINE, width=2)
    d.line([(270, 410), (1330, 410)], fill=LINE, width=2)
    for x in (270, 810, 1330):
        ortho(d, [(x, 410), (x, 445)])
    label(d, 930, 410, "127.0.0.1:18080")

    ortho(d, [(1020, 500), (1120, 500)], "状态流转", at=(1070, 484), dashed=True)
    ortho(d, [(810, 555), (810, 600)], "unix socket", at=(900, 578))
    ortho(d, [(270, 555), (270, 792)], "会话 / 角色", at=(325, 690))
    ortho(d, [(700, 555), (490, 555), (490, 770), (300, 770), (300, 792)], "落库", at=(490, 660))
    ortho(d, [(1300, 555), (1300, 792)], "原图 / 预览", at=(1395, 700))

    out = HERE / "architecture.png"
    img.save(out)
    return out


def listbox(d, x0, y0, w, h, title, items, fill, edge, badge=None):
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=14, fill=fill, outline=edge, width=2)
    d.text((x0 + w / 2, y0 + 26), title, font=font(21, True), fill=INK, anchor="mm")
    d.line([(x0 + 18, y0 + 46), (x0 + w - 18, y0 + 46)], fill=edge, width=1)
    y = y0 + 70
    for text, is_new in items:
        d.ellipse([x0 + 22, y - 4, x0 + 30, y + 4], fill=edge)
        d.text((x0 + 40, y), text, font=font(19), fill=INK, anchor="lm")
        if is_new:
            tw = d.textlength(text, font=font(19))
            d.rounded_rectangle([x0 + 44 + tw, y - 12, x0 + 52 + tw + 34, y + 12],
                                radius=7, fill=EDGE_NEW)
            d.text((x0 + 48 + tw + 17, y), "新增", font=font(14, True), fill=WHITE, anchor="mm")
        y += 36
    if badge:
        bw = d.textlength(badge, font=font(15, True)) + 16
        d.rounded_rectangle([x0 + w - bw - 8, y0 - 12, x0 + w - 8, y0 + 12], radius=8,
                           fill=EDGE_NEW, outline=EDGE_NEW)
        d.text((x0 + w - bw / 2 - 8, y0), badge, font=font(15, True), fill=WHITE, anchor="mm")


def modules() -> Path:
    W, H = 1620, 700
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    d.text((W / 2, 36), "功能模块图", font=font(34, True), fill=INK, anchor="mm")
    d.text((W / 2, 74), "系统由三端 + 一组共享能力组成；红标为本次要新增的模块",
           font=font(18), fill=MUTED, anchor="mm")

    box(d, 810, 140, 620, 76, ["柑橘采集与病虫害识别系统", "闭环：识别 → 建议 → 专家 → 训练 → 迭代"],
        (240, 244, 250), (120, 130, 145), size=22)

    listbox(d, 80, 230, 470, 300, "① 农民端（Android）", [
        ("拍照与单张识别", False),
        ("采集批次与上传队列", False),
        ("我的记录（含专家结论）", False),
        ("训练授权开关", True),
        ("专家咨询", False),
        ("个人中心与授权管理", False),
    ], FILL_APP, EDGE_APP)

    listbox(d, 575, 230, 470, 340, "② Web 管理端（农业局 / 管理员）", [
        ("识别记录列表", True),
        ("专家复核工单", True),
        ("样本核验与质量排除", False),
        ("抽查与指标", True),
        ("训练集导出", False),
        ("基础字典维护", False),
        ("知识库（本期占位）", False),
    ], FILL_EXP, EDGE_EXP)

    listbox(d, 1070, 230, 470, 340, "③ 服务端与共享能力", [
        ("认证与账号", False),
        ("观察记录 Observation", True),
        ("推理网关与守护进程", False),
        ("复核工单与结论回写", True),
        ("导出与打包", False),
        ("文件存储（可换 OSS）", False),
        ("短信验证码登录", False),
    ], FILL_SRV, EDGE_SRV)

    for x in (315, 810, 1305):
        ortho(d, [(810, 178), (810, 200), (x, 200), (x, 226)])

    out = HERE / "modules.png"
    img.save(out)
    return out


def state_machine() -> Path:
    W, H = 1620, 780
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    d.text((W / 2, 36), "Observation 状态机", font=font(34, True), fill=INK, anchor="mm")
    d.text((W / 2, 74), "一张照片从本地草稿到可进入训练集，中间只有专家结论能改变标签",
           font=font(18), fill=MUTED, anchor="mm")

    box(d, 190, 220, 240, 88, ["draft", "本地草稿 · 未上传"], FILL_APP, EDGE_APP, size=20)
    box(d, 560, 220, 260, 88, ["recognized", "已识别 · 已落库"], FILL_SRV, EDGE_SRV, size=20)
    box(d, 950, 220, 280, 88, ["advice_matched", "已给出处置建议"], FILL_SRV, EDGE_SRV, size=20)
    box(d, 1330, 220, 300, 88, ["reviewed", "专家已定类别"], FILL_EXP, EDGE_EXP, size=20)
    box(d, 560, 420, 260, 88, ["advice_missed", "低置信 / 未映射"], FILL_SRV, EDGE_SRV, size=20)
    box(d, 950, 420, 280, 88, ["escalated", "已转专家工单"], FILL_EXP, EDGE_EXP, size=20)
    box(d, 1330, 420, 300, 88, ["training_eligible", "授权 + 已核验"], FILL_TRAIN, EDGE_TRAIN, size=20)
    box(d, 560, 620, 260, 88, ["withdrawn", "撤回 · 不参与训练"], (245, 245, 247), (150, 155, 165), size=20)

    ortho(d, [(310, 220), (430, 220)], "上传并识别", at=(370, 160))
    ortho(d, [(690, 220), (810, 220)], "置信度 ≥ 0.8 且有资料", at=(750, 160))
    ortho(d, [(560, 264), (560, 376)], "低置信 / 未映射", at=(660, 320))
    ortho(d, [(690, 420), (810, 420)], "自动建单", at=(750, 460))
    ortho(d, [(1090, 220), (1180, 220)], "用户确认 / 核验", at=(1135, 160))
    ortho(d, [(950, 376), (950, 316), (1210, 316), (1210, 264)], "专家提交结论", at=(1080, 316))
    ortho(d, [(1330, 264), (1330, 376)], "consent = true", at=(1430, 320))
    ortho(d, [(1330, 464), (1330, 560), (560, 560), (560, 576)], "撤回", at=(950, 560), dashed=True)
    ortho(d, [(190, 176), (190, 138), (260, 138), (260, 176)], "重拍", at=(225, 122))

    d.text((810, 730), "注：任意状态均可撤回，撤回后不进入训练集，记录仍可查询；模型输出不是标签，只有专家结论或用户显式确认才能改变类别。",
           font=font(18), fill=MUTED, anchor="mm")

    out = HERE / "state-machine.png"
    img.save(out)
    return out


def deployment() -> Path:
    W, H = 1620, 1000
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    d.text((W / 2, 36), "部署架构", font=font(34, True), fill=INK, anchor="mm")
    d.text((W / 2, 74), "单台阿里云香港 ECS：systemd 管三个服务，数据库只监听回环，发布由 GitHub Actions 触发",
           font=font(18), fill=MUTED, anchor="mm")

    box(d, 210, 180, 300, 100, ["农民手机 App", "农业局浏览器"], FILL_APP, EDGE_APP, size=20)
    box(d, 210, 360, 300, 100, ["Cloudflare", "DNS + 代理 + 缓存"], (245, 247, 250), (120, 130, 145), size=20)
    box(d, 210, 640, 300, 100, ["GitHub 仓库", "Actions：CI + 部署"], (240, 240, 245), (110, 118, 130), size=20)

    d.rounded_rectangle([430, 130, 1590, 820], radius=18, outline=EDGE_SRV, width=2, fill=(250, 253, 251))
    d.text((452, 146), "阿里云香港 ECS · 8.217.13.178 · 2 vCPU / 7.6GB / 40GB", font=font(20, True),
           fill=EDGE_SRV, anchor="la")

    box(d, 1030, 240, 820, 76, ["Nginx 网关（citrus-gateway）", ":80 ACME + 308 · :443 TLS · 限流 · gzip · 媒体缓存"],
        FILL_SRV, EDGE_SRV, size=19)
    box(d, 1030, 350, 820, 76, ["Uvicorn API（citrus-app）", "127.0.0.1:18080 · 单进程 · 观察记录 / 复核 / 导出"],
        FILL_SRV, EDGE_SRV, size=19)
    box(d, 1030, 460, 660, 76, ["推理守护进程（citrus-inference）", "/run/citrus-inference/inference.sock"],
        FILL_OK, EDGE_OK, size=19, badge="已上线", badge_edge=EDGE_OK)
    box(d, 700, 640, 380, 88, ["PostgreSQL 14", "127.0.0.1:5432 · citrus_app"], FILL_TRAIN, EDGE_TRAIN, size=19)
    box(d, 1290, 640, 420, 88, ["文件目录 /var/lib/citrus-app", "原图 · 预览 · 导出 ZIP"], FILL_TRAIN, EDGE_TRAIN, size=19)
    box(d, 1030, 745, 820, 56, ["证书 Let's Encrypt（certbot.timer 自动续期）· 发布由 publish.sh 执行，健康检查失败自动回滚"],
        (247, 251, 248), EDGE_OK, size=18)

    ortho(d, [(210, 230), (210, 310)], "HTTPS", at=(300, 270))
    ortho(d, [(360, 360), (430, 360), (430, 240), (620, 240)], "TLS 回源 443", at=(500, 300))
    ortho(d, [(1030, 388), (1030, 422)], "本地 socket", at=(1130, 405))
    ortho(d, [(620, 350), (560, 350), (560, 596)], "落库", at=(516, 470))
    ortho(d, [(1440, 350), (1500, 350), (1500, 560), (1300, 560), (1300, 596)], "原图 / 预览", at=(1412, 540))
    ortho(d, [(360, 690), (430, 690)], "SSH 部署", at=(395, 668))

    out = HERE / "deployment.png"
    img.save(out)
    return out


if __name__ == "__main__":
    for path in (closed_loop(), architecture(), modules(), state_machine(), deployment()):
        print(path)
