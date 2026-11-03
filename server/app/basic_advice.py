"""Fixed basic guidance for the existing five-class leaf recognizer."""

VERSION = 'basic-2026-11-03'

BASIC_ADVICE = {
    'black_spot': {
        'status': 'matched',
        'title': '黑斑病基础建议',
        'message': '重点做好果园清洁，减少病源，并持续观察叶片和果实的变化。以下为基础管理建议，具体防治请结合现场情况咨询农技人员。',
        'actions': [
            {'title': '清理病源', 'detail': '及时清理落叶、落果和枯枝，集中妥善处理，保持果园清洁。'},
            {'title': '改善园内环境', 'detail': '合理修剪，保持通风透光；雨后及时排水，避免园内长期潮湿。'},
            {'title': '持续观察', 'detail': '留意果实是否出现新病斑，拍照记录变化；病情扩大时请农技人员现场确认。'},
        ],
        'sources': [{'title': 'UF/IFAS：柑橘黑斑病管理', 'url': 'https://edis.ifas.ufl.edu/publication/CG088'}],
    },
    'canker': {
        'status': 'matched',
        'title': '溃疡病基础建议',
        'message': '重点保护新梢，减少病害随风雨和农事操作传播。以下为基础管理建议，具体防治请结合现场情况咨询农技人员。',
        'actions': [
            {'title': '保持果园清洁', 'detail': '及时清理病残枝叶，修剪工具使用后做好清洁消毒，避免交叉传播。'},
            {'title': '减少传播机会', 'detail': '避免在枝叶潮湿时修剪或穿行作业，注意防风，并留意潜叶蛾等造成的伤口。'},
            {'title': '关注新梢变化', 'detail': '定期查看新叶和嫩梢，拍照记录病斑；新病斑增多时及时咨询农技人员。'},
        ],
        'sources': [{'title': 'UF/IFAS：柑橘溃疡病管理', 'url': 'https://edis.ifas.ufl.edu/publication/CG040'}],
    },
    'greening': {
        'status': 'matched',
        'title': '黄龙病基础建议',
        'message': '黄龙病疑似症状需要专业检测确认，单张照片不能作为清除树木的依据。请尽快联系当地农技或植保人员。',
        'actions': [
            {'title': '标记并复核', 'detail': '标记疑似植株，记录叶片黄化及果实异常情况，联系农技人员采样检测。'},
            {'title': '关注柑橘木虱', 'detail': '检查嫩梢上的木虱，在当地植保人员指导下开展防控，减少传播。'},
            {'title': '避免调运繁殖材料', 'detail': '疑似植株不要用于取接穗或育苗，不随意调运苗木；确诊后的处置按当地植保要求执行。'},
        ],
        'sources': [{'title': '湖南省农业农村厅：柑橘黄龙病防控方案', 'url': 'https://agri.hunan.gov.cn/xxgk/ghjh/202411/t20241112_33498221.html'}],
    },
    'melanose': {
        'status': 'matched',
        'title': '黑点病基础建议',
        'message': '重点清理枯枝，改善通风和排水，减少病害发生条件。以下为基础管理建议，具体防治请结合现场情况咨询农技人员。',
        'actions': [
            {'title': '清除枯枝', 'detail': '及时剪除树上的枯枝并清理园内残枝，减少病源。'},
            {'title': '通风排水', 'detail': '适当疏剪过密枝条，保持通风透光；雨后及时排水，减少持续潮湿。'},
            {'title': '留意嫩叶幼果', 'detail': '关注新叶、嫩梢和幼果上的黑点变化；连续阴雨后加强观察，必要时咨询农技人员。'},
        ],
        'sources': [{'title': 'UF/IFAS：柑橘黑点病管理', 'url': 'https://edis.ifas.ufl.edu/publication/CG019'}],
    },
    'healthy': {
        'status': 'healthy',
        'title': '健康养护建议',
        'message': '本次识别结果为健康。保持合理水肥，避免积水，适当修剪以保持通风透光；定期查看新梢、叶背和果实，发现异常时及时拍照复查。',
        'actions': [],
        'sources': [{'title': '农业农村部：柑橘质量安全管控技术性指导意见', 'url': 'https://jgs.moa.gov.cn/fxpg/202212/t20221228_6417846.htm'}],
    },
}
