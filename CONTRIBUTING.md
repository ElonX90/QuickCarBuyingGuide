# 补充证据、纠错与参与维护

不会改代码也能贡献：[提交证据](https://github.com/ElonX90/QuickCarBuyingGuide/issues/new?template=evidence.yml)；先了解[审核标准](docs/REVIEW_GUIDE.md)。有疑问或不同解释可提交[争议/纠错](https://github.com/ElonX90/QuickCarBuyingGuide/issues/new?template=correction.yml)。

## 一条数据需要什么

| 字段 | 要求 |
|---|---|
| 对象 | 车型车系、世代/年款、动力、国内/海外版本；涉及员工还需明确企业法人及岗位范围 |
| 要修改的值 | 当前值、建议值或区间、单位，以及影响的评分维度 |
| 证据 | 可访问的原始公开 URL；PDF 页码、网页段落/表格或视频时间点；必要的简短摘记 |
| 时间和地域 | 事实发生时间、报告覆盖期、适用地区、检索时间 |
| 适用边界 | 证据能确认什么，不能确认什么；旧款、集团、子公司和不同动力不能混用 |
| 冲突和整改 | 相反资料、完整上下文、最新进展及整改状态 |

优先原始立项/项目披露、监管召回公告、厂家完整配置表、公司年报和可核实的具名完整访谈。新闻和招聘可作为线索，匿名帖、孤立截图、转述或关键词命中不能独自支持全品牌定性。仅摘录核查所需事实，不上传来源全文或个人身份证、缴费账号等信息。

## 无代码流程

1. 用证据表单提交，一条事实尽量一个 Issue。问题提交后处于待审，不自动改分。
2. 维护者读原文，核对主体、车型版本、时间、口径和矛盾资料；需要补证时在 Issue 中说明。
3. 接受、拒绝或暂存争议，都公开记录理由。接受后由维护者将出处和有限事实写入数据，关联 Issue 与对应 PR/提交。
4. 程序复算、检查通过后发布；新证据推翻旧结论时，保留历史并更正。

## 代码流程

Fork 仓库，在分支修改 sources.json，然后修改 models.json、brands.json 或销量数据中的具体字段；勿手改生成表和最终分数。首次登记来源可设 review.status=pending，但被正式观察引用前必须经维护者接受并补齐审阅记录。未获核实数值使用 null，开口范围使用 [下界, null]。

足额缴费或欠缴结论必须有 labor_sources、labor_entity、labor_period、labor_scope；生产法人对应必须有 manufacturer_mapping_sources，所引来源也须 accepted。

外包用工存在/不存在的结论必须有 outsourcing_sources、outsourcing_entity、outsourcing_period、outsourcing_scope；“无外包”尤其需要完整范围实证，不能从招聘空白推定。

运行：

```bash
python scripts/build.py --check
python -m unittest discover -s tests -v
python scripts/build.py
```

提交数据和生成结果；PR 说明新增证据、关联 Issue、计分变化、适用边界与未解决的问题。权重改变须更新方法版本和说明。CODEOWNERS 指定维护者审核，**通过 CI 不代表证据已经真实可信**，不自动合并投稿。
