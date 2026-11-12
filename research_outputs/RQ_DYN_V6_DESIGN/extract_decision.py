#!/usr/bin/env python3
"""决定书HTML提取器V2(2026-11-10):修正版
教训: V1的导航过滤用子串正则(法律/联系/行政处罚等),命中正文段落时整段静默丢弃
——万福'移送司法'段/金亚'一事不二罚'段/盈方微'复核第三点'段均因此丢失。
V2原则: 只剥标签+合并碎行;导航过滤仅限精确整行匹配(白名单),不匹配任何内容子串。
输出: 连续无空白正文(供槽位构建) + 带行号分行视图(供span定位)。
"""
import re, html, sys

NAV_EXACT = {"首页",">","‖","|","-->","无障碍","English","移动端","微博","微信",
             "大","中","小","【打印】","【关闭窗口】","中国政府网","行业相关网站",
             "中国投资者网","中国资本市场标准网","政府网站年度报表","其他链接",
             "联系我们","法律声明","归档数据","机构概况","新闻发布","统计信息",
             "证监局介绍","辖区监管动态","政务信息","办事服务","辖区数据","互动交流",
             "专题专栏","当前位置","政府信息公开","主动公开","按主题查看","行政执法","行政处罚"}

def extract(fp):
    raw = open(fp, encoding="utf-8", errors="ignore").read()
    raw = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', raw, flags=re.S|re.I)
    t = re.sub(r'<[^>]+>', '\n', raw)
    t = html.unescape(t).replace('\u3000', ' ')
    lines = [l.strip() for l in t.split("\n") if l.strip()]
    # 仅整行精确匹配导航白名单 或 纯符号/时间戳行 才丢弃
    lines = [l for l in lines
             if l not in NAV_EXACT
             and not re.fullmatch(r'[>/|·\-\s]+', l)
             and not re.fullmatch(r'\d{13}', l)
             and not l.startswith(('网站识别码','京ICP备','京公网安备','版权所有','主办单位'))]
    merged = []
    for l in lines:
        if merged and len(l) <= 4 and (re.match(r'^[\d.,%年月日号（）()元万亿%％\-]+$', l) or set(l) <= set('，。；：、')):
            merged[-1] += l
        else:
            merged.append(l)
    continuous = re.sub(r'\s+', '', " ".join(merged))  # 无空白连续正文
    return merged, continuous

if __name__ == "__main__":
    merged, cont = extract(sys.argv[1])
    print(f"分段视图 {len(merged)} 段; 连续正文 {len(cont)} 字")
    if len(sys.argv) > 2 and sys.argv[2] == "lines":
        for i, l in enumerate(merged): print(f"{i+1}|{l}")
