#!/usr/bin/env python3
"""Validate reviewed observations and regenerate the public evidence tables.

Python standard library only. No network, credentials or web scraping.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LABELS = {'development': '开发周期', 'globalization': '全球化',
          'recall': '正式召回历史', 'labor': '足额五险一金', 'sku': 'SKU'}
GLOBAL_LABELS = {'international_family': '海外正式车型家族', 'derived_family': '海外衍生家族/新旧硬件待匹配',
                 'global_design': '仅全球设计/发布证据', 'china_only': '官方中国专属',
                 'planned': '出海计划，未代替实售', 'unknown': '待核查'}


def load():
    def read(name):
        return json.loads((ROOT / 'data' / name).read_text(encoding='utf-8'))
    return read('models.json'), read('brands.json'), read('sources.json'), read('methodology.json')


def cycle_points(months: float, config: dict) -> float:
    zero = config['cycle_zero_months']
    maximum = config['cycle_max_months']
    return max(0.0, min(100.0, 100.0 * (zero - months) / (zero - maximum)))


def sku_points(count: int, config: dict) -> float:
    for ceiling, points in config['sku_bands']:
        if ceiling is None or count <= ceiling:
            return float(points)
    raise ValueError('Missing final SKU band')


def components(model: dict, brand: dict, config: dict) -> dict:
    bounds = {}
    cycle = model['development']['months_range']
    # More time means less compression; reverse the endpoint order.
    bounds['development'] = (0.0, 100.0) if cycle is None else (
        0.0 if cycle[1] is None else cycle_points(cycle[1], config),
        cycle_points(cycle[0], config))
    gp = config['globalization_points'][model['globalization']['level']]
    bounds['globalization'] = (0.0, 100.0) if gp is None else (float(gp), float(gp))
    recall = {'formal_history_found': (0.0, 0.0), 'not_verified': (0.0, 100.0),
              'documented_failure': (100.0, 100.0)}
    labor = {'verified_full_scope': (0.0, 0.0), 'not_verified': (0.0, 100.0),
             'documented_unresolved_shortfall': (100.0, 100.0)}
    bounds['recall'] = recall[brand['recall_status']]
    bounds['labor'] = labor[brand['labor_status']]
    sku = model['sku']['count_range']
    bounds['sku'] = (0.0, 100.0) if sku is None else (
        sku_points(sku[0], config),
        100.0 if sku[1] is None else sku_points(sku[1], config))
    return bounds


def weighted(bounds: dict, weights: dict) -> tuple[float, float]:
    return tuple(round(sum(weights[k] * bounds[k][end] / 100 for k in weights), 1)
                 for end in (0, 1))


def score(model: dict, brand: dict, config: dict) -> dict:
    bounds = components(model, brand, config)
    low, high = weighted(bounds, config['weights'])
    unresolved = [LABELS[k] for k, pair in bounds.items() if pair[0] != pair[1]]
    thresholds = config['sku_attention_threshold']
    sku = model['sku']['count_range']
    confirmed_objections = []
    if model['globalization']['level'] == 'china_only':
        confirmed_objections.append('与全球化优先偏好不符')
    if sku is not None and sku[0] >= thresholds:
        confirmed_objections.append('SKU 已达较多阈值')
    if brand['labor_status'] == 'documented_unresolved_shortfall':
        confirmed_objections.append('足额缴费存在尚未整改的实证问题')
    if brand['recall_status'] == 'documented_failure':
        confirmed_objections.append('召回整改存在实证问题')
    # A low index is never allowed to erase an unresolved user prerequisite.
    missing_prerequisites = []
    if brand['recall_status'] != 'formal_history_found':
        missing_prerequisites.append('正式召回历史')
    if brand['labor_status'] != 'verified_full_scope':
        missing_prerequisites.append('当前用工主体足额五险一金')
    if model['globalization']['level'] != 'international_family':
        missing_prerequisites.append('当前车型全球化对应')
    if sku is None:
        missing_prerequisites.append('完整现售 SKU')
    status = '偏好冲突，优先核查' if confirmed_objections else '购前条件待核'
    if not confirmed_objections and not missing_prerequisites:
        status = '偏好条件已核实；还需核对具体 VIN'
    return dict(id=model['id'], name=model['name'], scope=model['scope'],
                low=low, high=high, component_bounds=bounds,
                unresolved=unresolved, objections=confirmed_objections,
                missing_prerequisites=missing_prerequisites, status=status,
                scenarios={name: weighted(bounds, w) for name,w in config['scenarios'].items()})


def validate(models, brands, sources, config):
    for collection, label in [(models,'model'), (brands,'brand'), (sources,'source')]:
        ids = [item['id'] for item in collection]
        if len(ids) != len(set(ids)):
            raise ValueError(f'Duplicate {label} id')
    source_ids = {s['id'] for s in sources}
    brand_map = {b['id']:b for b in brands}
    for source in sources:
        parsed = urlparse(source['url'])
        if parsed.scheme != 'https' or not parsed.netloc:
            raise ValueError(f'Invalid source URL: {source["id"]}')
        if not source['reviewed_facts'] or not source['limitations']:
            raise ValueError(f'Missing source interpretation: {source["id"]}')
    for weights in [config['weights'], *config['scenarios'].values()]:
        if set(weights) != set(LABELS) or sum(weights.values()) != 100 or min(weights.values()) < 0:
            raise ValueError('Weights must be nonnegative and sum to 100')
    def refs(ref_list):
        missing = set(ref_list) - source_ids
        if missing:
            raise ValueError(f'Missing references: {missing}')
    for brand in brands:
        refs(brand['recall_sources'] + brand['related_recall_sources'] + brand['labor_sources'])
        if brand['recall_status'] == 'formal_history_found' and not brand['recall_sources']:
            raise ValueError('A positive recall-history claim requires a formal notice')
        if any(next(s for s in sources if s['id']==r)['type'] != 'recall_notice' for r in brand['recall_sources']):
            raise ValueError('Recall evidence must be a formal notice')
        if brand['labor_status'] != 'not_verified' and not brand['labor_sources']:
            raise ValueError('Labor findings require evidence')
    for m in models:
        if m['brand_id'] not in brand_map or not m['sale_sources']:
            raise ValueError(f'Incomplete eligibility: {m["id"]}')
        refs(m['sale_sources'] + m['development']['sources'] + m['globalization']['sources'] + m['sku']['sources'])
        if m['globalization']['level'] not in config['globalization_points']:
            raise ValueError('Unknown globalization level')
        if m['globalization']['level'] != 'unknown' and not m['globalization']['sources']:
            raise ValueError('Globalization observation requires a source')
        for block, field in [('development','months_range'),('sku','count_range')]:
            value = m[block][field]
            if value is not None:
                if value[0] <= 0 or (value[1] is not None and value[1] < value[0]):
                    raise ValueError('Invalid observed bounds')
                if block == 'sku' and any(v is not None and not isinstance(v,int) for v in value):
                    raise ValueError('SKU counts must be integers')
                if not m[block]['sources']:
                    raise ValueError('A quantitative observation requires a source')
        r = score(m, brand_map[m['brand_id']], config)
        if not 0 <= r['low'] <= r['high'] <= 100:
            raise ValueError('Out-of-range composite')
    return brand_map


def number(x):
    return str(int(x)) if float(x).is_integer() else f'{x:.1f}'


def rng(value, unit=''):
    if value is None:
        return '未知'
    lo, hi = value
    if hi is None:
        return f'≥{number(lo)}{unit}'
    if lo == hi:
        return f'{number(lo)}{unit}'
    return f'{number(lo)}–{number(hi)}{unit}'


def refs_md(refs, source_map):
    return '、'.join(f'[{r}]({source_map[r]["url"]})' for r in dict.fromkeys(refs)) or '未取得足够证据'


def render(models, brands, sources, config):
    bm = validate(models,brands,sources,config)
    sm = {s['id']:s for s in sources}
    scored = [score(m,bm[m['brand_id']],config) for m in models]
    by_id = {m['id']:m for m in models}
    # This is a display order of established points, never an asserted safety ranking.
    display = sorted(scored, key=lambda r:(-r['low'],r['name']))
    docs = ROOT/'docs'
    docs.mkdir(exist_ok=True)
    lines = ['# 车型指数与购前条件', '',
             f'数据版本：{config["version"]}；来源检索窗口：2026-10-12 至 2026-10-13；市场：中国大陆。', '',
             '**分数越高表示本指南的核查优先度越高。区间是未知项的可能计分上下界，不是事故概率、统计置信区间或安全测评。表格按已确认计分下界排列，仅为方便阅读；不能按下界、上界或中点宣称车的安全优劣。**', '',
             '大部分车型未公开本代立项时间；全部品牌的当前员工级足额缴费情况仍未证实。所有车型均有购前待核条件。', '',
             '关于四项偏好的规则见 [方法](METHODOLOGY.md)，详细事实及边界见 [逐车证据](MODEL_DETAILS.md)。', '',
             '| 车型/动力分支 | 开发月数 | 全球化证据 | 基本 SKU | 指数区间 | 正式召回历史 | 购前状态 |',
             '|---|---:|---|---:|---:|---|---|']
    for r in display:
        m = by_id[r['id']]
        recall = '有品牌记录' if bm[m['brand_id']]['recall_status']=='formal_history_found' else '尚未证实'
        lines.append(f'| [{m["name"]}](MODEL_DETAILS.md#{m["id"]}) | {rng(m["development"]["months_range"])} | {GLOBAL_LABELS[m["globalization"]["level"]]} | {rng(m["sku"]["count_range"])} | {rng([r["low"],r["high"]])} | {recall} | {r["status"]} |')
    lines += ['', 'P7+ 的纯电与增程共四个基础配置，拆成两条是因为欧洲 BEV 证据不能自动授予 EREV。', '',
              '低分且没有完整证据的车型不能进入“已核实推荐”。旧年款、集团关联召回、未来出海计划均不自动变成当前车型通过项。', '',
              '## 权重敏感性', '', '以下两套权重只展示偏好变化对区间的影响，不提供名次。未披露研发和用工证据仍是最大缺口。', '',
              '| 车型 | 默认 | 周期优先 | 治理优先 |', '|---|---:|---:|---:|']
    for r in display:
        lines.append(f'| {r["name"]} | {rng([r["low"],r["high"]])} | {rng(r["scenarios"]["cycle_first"])} | {rng(r["scenarios"]["governance_first"])} |')
    (docs/'RANKING.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')

    details = ['# 逐车证据卡', '', '每条对应明确的车系、世代或动力分支。销售目录存在不等于当地有现车；实际购车应核对年款、生产企业、配置表及 VIN。', '']
    for m in models:
        b = bm[m['brand_id']]
        r = score(m,b,config)
        details += [f'<a id="{m["id"]}"></a>', f'## {m["name"]}', '',
            f'- 研究范围：{m["scope"]}；动力：{", ".join(m["powertrains"])}。',
            f'- 在售依据：{refs_md(m["sale_sources"],sm)}。本轮未确认地区现车库存。',
            f'- 整车开发跨度：{rng(m["development"]["months_range"],"个月")}。{m["development"]["note"]} 来源：{refs_md(m["development"]["sources"],sm)}。',
            f'- 全球化：{GLOBAL_LABELS[m["globalization"]["level"]]}。{m["globalization"]["note"]} 来源：{refs_md(m["globalization"]["sources"],sm)}。',
            f'- 中国销售版本与海外配置等同性、国内 eCall：均待核。',
            f'- SKU：{rng(m["sku"]["count_range"])}。{m["sku"]["note"]} 来源：{refs_md(m["sku"]["sources"],sm)}。',
            f'- 正式召回历史：{"已取得品牌记录" if b["recall_status"]=="formal_history_found" else "未获得充分品牌记录"}。{b["note"]} 来源：{refs_md(b["recall_sources"],sm)}。',
            f'- 集团/其他品牌关联记录（不充当通过项）：{refs_md(b["related_recall_sources"],sm)}。',
            f'- 足额五险一金：待核。{b["labor_note"]} 相关披露：{refs_md(b["labor_sources"],sm)}。',
            f'- 当前具体生产法人：尚未逐车验证；品牌级召回历史不能取代当前生产法人或 VIN 的核对。',
            f'- 指数区间：**{rng([r["low"],r["high"]])}**；状态：{r["status"]}。',
            f'- 未完成购前条件：{"、".join(r["missing_prerequisites"]) or "请核对具体 VIN"}。', '']
    (docs/'MODEL_DETAILS.md').write_text('\n'.join(details),encoding='utf-8',newline='\n')

    sl = ['# 来源登记与适用边界', '',
          '保存链接、检索时间、已读到的事实及其不能证明的事项。未复制来源全文、图片、车主手册或完整年报。检索记录不是厂家测试报告的审计。', '',
          '公告日期以正文为准，网页迁移路径或搜索引擎估计年龄不替代正文日期。动态官网保存本轮观察文字，后续变化须重新核对。', '']
    for s in sources:
        sl += [f'<a id="{s["id"]}"></a>', f'## {s["id"]} · {s["title"]}', '',
               f'[{s["publisher"]}]({s["url"]})；类型：`{s["type"]}`；检索：{s["retrieved_at"]}；正文日期：{s["published_at"] or "未完整核实/动态页"}。', '',
               s['reviewed_facts'], '', f'适用边界：{s["limitations"]}', '']
    (docs/'SOURCES.md').write_text('\n'.join(sl),encoding='utf-8',newline='\n')

    raw = dict(version=config['version'], as_of=config['as_of'], results=scored)
    (ROOT/'data'/'scores.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer,lineterminator='\n')
    writer.writerow(['id','车型','研究范围','动力','开发月数下界','开发月数上界','全球化证据','SKU下界','SKU上界','指数下界','指数上界','状态','待核条件','在售来源'])
    for r in display:
        m = by_id[r['id']]
        cycle=m['development']['months_range'] or [None,None]
        sku=m['sku']['count_range'] or [None,None]
        writer.writerow([m['id'],m['name'],m['scope'],'/'.join(m['powertrains']),*cycle,
            GLOBAL_LABELS[m['globalization']['level']],*sku,r['low'],r['high'],r['status'],
            '；'.join(r['missing_prerequisites']),';'.join(sm[x]['url'] for x in m['sale_sources'])])
    (ROOT/'data'/'model-index.csv').write_text(buffer.getvalue(),encoding='utf-8-sig',newline='\n')
    return scored


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='validate observations without regenerating files')
    args=parser.parse_args()
    data=load()
    if args.check:
        validate(*data)
    else:
        render(*data)
    print(f'OK: {len(data[0])} observations; {len(data[1])} brands; {len(data[2])} source records; weights and bounds validated.')


if __name__=='__main__':
    main()
