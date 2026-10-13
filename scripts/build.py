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
          'recall': '正式召回历史', 'labor': '用工保障（缴费与外包）', 'sku': 'SKU'}
OUTSOURCING_LABELS = {'not_verified': '待核', 'verified_present': '已确认存在外包/派遣用工',
                      'verified_absent_full_scope': '指定主体及时间范围内已核实无外包/派遣用工'}
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
    payment = labor[brand['labor_status']]
    outsourcing = {'not_verified': (0.0, 100.0), 'verified_present': (100.0, 100.0),
                   'verified_absent_full_scope': (0.0, 0.0)}[brand['outsourcing_status']]
    # Either labor objection is enough; adding a second objection cannot dilute the first.
    bounds['labor'] = (max(payment[0], outsourcing[0]), max(payment[1], outsourcing[1]))
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
    if brand['outsourcing_status'] == 'verified_present':
        confirmed_objections.append('存在已核实外包/派遣用工，不建议购买')
    if brand['recall_status'] == 'documented_failure':
        confirmed_objections.append('召回整改存在实证问题')
    # A low index is never allowed to erase an unresolved user prerequisite.
    missing_prerequisites = []
    if brand['recall_status'] != 'formal_history_found':
        missing_prerequisites.append('正式召回历史')
    if brand['labor_status'] != 'verified_full_scope':
        missing_prerequisites.append('当前用工主体足额五险一金')
    if brand['outsourcing_status'] != 'verified_absent_full_scope':
        missing_prerequisites.append('当前用工主体无外包/派遣员工')
    if model['globalization']['level'] != 'international_family':
        missing_prerequisites.append('当前车型全球化对应')
    if sku is None:
        missing_prerequisites.append('完整现售 SKU')
    status = '偏好冲突，优先核查' if confirmed_objections else '购前条件待核'
    if brand['outsourcing_status'] == 'verified_present':
        status = '不建议购买（已核实外包/派遣用工）'
    if not confirmed_objections and not missing_prerequisites:
        status = '偏好条件已核实；还需核对具体 VIN'
    return dict(id=model['id'], name=model['name'], scope=model['scope'],
                low=low, high=high, component_bounds=bounds,
                unresolved=unresolved, objections=confirmed_objections,
                missing_prerequisites=missing_prerequisites, status=status,
                known_weight=sum(config['weights'][k] for k,v in bounds.items() if v[0] == v[1]),
                outsourcing_status=brand['outsourcing_status'],
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
        review = source.get('review', {})
        if review.get('status') not in {'pending', 'accepted', 'rejected', 'conflicting'}:
            raise ValueError(f'Missing evidence review state: {source["id"]}')
        if review['status'] == 'accepted' and not all(review.get(k) for k in ('reviewer','reviewed_at','reason')):
            raise ValueError(f'Accepted evidence needs a review receipt: {source["id"]}')
    for weights in [config['weights'], *config['scenarios'].values()]:
        if set(weights) != set(LABELS) or sum(weights.values()) != 100 or min(weights.values()) < 0:
            raise ValueError('Weights must be nonnegative and sum to 100')
    def refs(ref_list):
        missing = set(ref_list) - source_ids
        if missing:
            raise ValueError(f'Missing references: {missing}')
        if any(next(s for s in sources if s['id']==r)['review']['status'] != 'accepted' for r in ref_list):
            raise ValueError('Unreviewed, rejected or conflicting sources cannot enter published observations')
    for brand in brands:
        refs(brand['recall_sources'] + brand['related_recall_sources'] + brand['labor_sources'] + brand['outsourcing_sources'])
        if brand['outsourcing_status'] not in OUTSOURCING_LABELS:
            raise ValueError('Invalid outsourcing status')
        if brand['outsourcing_status'] != 'not_verified' and (not brand['outsourcing_sources'] or
                not all(brand.get(k) for k in ('outsourcing_entity','outsourcing_period','outsourcing_scope'))):
            raise ValueError('An outsourcing finding needs reviewed evidence, entity, period and scope')
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


def validate_cohort(models, sources, config, cohort=None):
    if cohort is None:
        cohort = json.loads((ROOT/'data'/config['sales_cohort_file']).read_text(encoding='utf-8'))
    rows = cohort['rows']
    if cohort['month'] != config['sales_month'] or len(rows) != 100:
        raise ValueError('The requested monthly cohort must contain exactly 100 rows')
    if [r['rank'] for r in rows] != list(range(1,101)):
        raise ValueError('Sales ranks must be unique, complete and ordered 1..100')
    if len({r['series_id'] for r in rows}) != 100:
        raise ValueError('Duplicate sales family')
    if any(not isinstance(r['sales'],int) or r['sales'] <= 0 for r in rows):
        raise ValueError('Invalid sales observation')
    if any(rows[i]['sales'] < rows[i+1]['sales'] for i in range(99)):
        raise ValueError('Sales cohort is not in descending order')
    mids={m['id'] for m in models}
    sm={s['id']:s for s in sources}
    for row in rows:
        if not row['observation_ids'] or not set(row['observation_ids']) <= mids:
            raise ValueError('A sales family has no valid evidence observation')
        if sm[row['source_id']]['review']['status'] != 'accepted':
            raise ValueError('Sales cohort requires accepted evidence')
        if not row['mapping_note']:
            raise ValueError('Sales-family to observation mapping must explain its scope')
    return cohort


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
    cohort = validate_cohort(models,sources,config)
    sm = {s['id']:s for s in sources}
    scored = [score(m,bm[m['brand_id']],config) for m in models]
    by_id = {m['id']:m for m in models}
    # This is a display order of established points, never an asserted safety ranking.
    display = sorted(scored, key=lambda r:(-r['low'],r['name']))
    docs = ROOT/'docs'
    docs.mkdir(exist_ok=True)
    lines = ['# 车型指数与购前条件', '',
             f'数据版本：{config["version"]}；来源检索窗口：{config["research_window"][0]} 至 {config["research_window"][1]}；市场：中国大陆。', '',
             '**分数越高表示本指南的核查优先度越高。区间是未知项的可能计分上下界，不是事故概率、统计置信区间或安全测评。表格按已确认计分下界排列，仅为方便阅读；不能按下界、上界或中点宣称车的安全优劣。**', '',
             '已纳入 2026 年 9 月固定榜单前 100 个车系，另保留首版对照车型。销量车系与明确年款的评分观察并非一一等同。[前 100 覆盖表](SALES_TOP100.md) 单独列出映射与缺口。大部分车型未公开本代立项时间；当前员工级足额缴费和无外包完整范围证明仍待补齐。', '',
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
            f'- {"9月销量入样依据（当前官方年款仍待核）" if m["sale_status"]=="sales_cohort_only" else "在售依据"}：{refs_md(m["sale_sources"],sm)}。本轮未确认地区现车库存。',
            f'- 整车开发跨度：{rng(m["development"]["months_range"],"个月")}。{m["development"]["note"]} 来源：{refs_md(m["development"]["sources"],sm)}。',
            f'- 全球化：{GLOBAL_LABELS[m["globalization"]["level"]]}。{m["globalization"]["note"]} 来源：{refs_md(m["globalization"]["sources"],sm)}。',
            f'- 中国销售版本与海外配置等同性、国内 eCall：均待核。',
            f'- SKU：{rng(m["sku"]["count_range"])}。{m["sku"]["note"]} 来源：{refs_md(m["sku"]["sources"],sm)}。',
            f'- 正式召回历史：{"已取得品牌记录" if b["recall_status"]=="formal_history_found" else "未获得充分品牌记录"}。{b["note"]} 来源：{refs_md(b["recall_sources"],sm)}。',
            f'- 集团/其他品牌关联记录（不充当通过项）：{refs_md(b["related_recall_sources"],sm)}。',
            f'- 足额五险一金：`{b["labor_status"]}`。{b["labor_note"]} 相关披露：{refs_md(b["labor_sources"],sm)}。',
            f'- 外包/派遣员工：{OUTSOURCING_LABELS[b["outsourcing_status"]]}。{b["outsourcing_note"]} 来源：{refs_md(b["outsourcing_sources"],sm)}。',
            f'- 当前具体生产法人：尚未逐车验证；品牌级召回历史不能取代当前生产法人或 VIN 的核对。',
            f'- 指数区间：**{rng([r["low"],r["high"]])}**；状态：{r["status"]}。',
            f'- 已确定计分权重：{r["known_weight"]}%（信息完整度提示，不是评分准确率）。',
            f'- 未完成购前条件：{"、".join(r["missing_prerequisites"]) or "请核对具体 VIN"}。', '']
    (docs/'MODEL_DETAILS.md').write_text('\n'.join(details),encoding='utf-8',newline='\n')

    sl = ['# 来源登记与适用边界', '',
          '保存链接、检索时间、已读到的事实及其不能证明的事项。未复制来源全文、图片、车主手册或完整年报。检索记录不是厂家测试报告的审计。', '',
          '公告日期以正文为准，网页迁移路径或搜索引擎估计年龄不替代正文日期。动态官网保存本轮观察文字，后续变化须重新核对。', '']
    for s in sources:
        sl += [f'<a id="{s["id"]}"></a>', f'## {s["id"]} · {s["title"]}', '',
               f'[{s["publisher"]}]({s["url"]})；类型：`{s["type"]}`；检索：{s["retrieved_at"]}；正文日期：{s["published_at"] or "未完整核实/动态页"}。', '',
               s['reviewed_facts'], '', f'适用边界：{s["limitations"]}', '']
        sl += [f'审阅状态：`{s["review"]["status"]}`；审阅者：{s["review"].get("reviewer") or "待分配"}；审阅日期：{s["review"].get("reviewed_at") or "待审"}。', '']
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
    render_cohort(cohort, scored, by_id, sm, config)
    quality = ['# 数据覆盖与待补证事项', '', f'版本：{config["version"]}；截至：{config["as_of"]}。本页由生成器重算，资料覆盖不能当预测准确率。', '', f'固定月榜已纳入100车系；评分观察共{len(models)}条。观察数量多于车系数量，包含动力分支及不在本月前100内的对照。', '', '| 计分维度 | 已确定计分的观察数 | 仍有未知区间的观察数 |', '|---|---:|---:|']
    for key,label in LABELS.items():
        fixed = sum(r['component_bounds'][key][0] == r['component_bounds'][key][1] for r in scored)
        quality.append(f'| {label} | {fixed} | {len(scored)-fixed} |')
    quality += ['', f'完全未确定任何计分项的观察数：{sum(r["known_weight"] == 0 for r in scored)}；这类记录保持[0,100]，无法给出结论。', '', '完整员工级足额缴费和当前无外包/派遣范围证明仍缺失。多数本代项目起点未公开；榜单入样和品牌召回历史不等于完整研发、质量或用工核查。', '', '优先补：原始整车立项/起止事件、当前完整SKU表、明确法人及报告期的用工资料、国内与海外同代同动力对应。[提交证据](../CONTRIBUTING.md)。', '']
    (ROOT/'docs'/'DATA_QUALITY.md').write_text('\n'.join(quality),encoding='utf-8',newline='\n')
    return scored


def render_cohort(cohort, scored, models, sources, config):
    scores={r['id']:r for r in scored}
    lines=['# 2026 年 9 月销量前 100 车系覆盖', '',
           f'固定来源：[{cohort["publisher"]}]({cohort["source_url"]})；月份：{cohort["month"]}；口径：**{cohort["metric"]}**；抓取日期：{cohort["retrieved_at"]}。', '',
           cohort['scope_note'], '',
           '本表的名次仅指所选销量榜的名次，不是速成车或安全排名。新增的销量车系记录仍须补本代、动力、生产主体及官方现售配置；缺少的研发、全球化、用工或 SKU 项保持未知。映射到明确年款的旧观察只代表该观察范围，不将其分数外推到整条车系。', '',
           '| 销量序号 | 销量车系 | 月销量（辆） | 评分观察 / 区间 / 已确定权重 | 映射边界 |',
           '|---:|---|---:|---|---|']
    buf=io.StringIO(newline='')
    writer=csv.writer(buf,lineterminator='\n')
    writer.writerow(['month','rank','series_id','series_name','sales','metric','observation_ids','mapping_note','source_url'])
    for row in cohort['rows']:
        obs=[]
        for mid in row['observation_ids']:
            s=scores[mid]
            obs.append(f'[{models[mid]["name"]}](MODEL_DETAILS.md#{mid})：{rng([s["low"],s["high"]])}；{s["known_weight"]}%')
        lines.append(f'| {row["rank"]} | {row["series_name"]} | {row["sales"]:,} | {"<br>".join(obs)} | {row["mapping_note"]} |')
        writer.writerow([cohort['month'],row['rank'],row['series_id'],row['series_name'],row['sales'],cohort['metric'],';'.join(row['observation_ids']),row['mapping_note'],cohort['source_url']])
    (ROOT/'docs'/'SALES_TOP100.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    (ROOT/'data'/'sales-top100.csv').write_text(buf.getvalue(),encoding='utf-8-sig',newline='\n')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='validate observations without regenerating files')
    args=parser.parse_args()
    data=load()
    if args.check:
        validate(*data)
        validate_cohort(data[0],data[2],data[3])
    else:
        render(*data)
    print(f'OK: {len(data[0])} observations; {len(data[1])} brands; {len(data[2])} source records; weights and bounds validated.')


if __name__=='__main__':
    main()
