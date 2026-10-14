(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.QuickCarScoring = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // These editorial weights express buying preferences, not a calibrated probability.
  var WEIGHTS = Object.freeze({ development: 40, globalization: 20, recall: 15, labor: 15, sku: 10 });
  var GLOBAL_POINTS = Object.freeze({ international_family: 0, derived_family: 50, global_design: 80, china_only: 100, planned: null, unknown: null });
  var RECALL_POINTS = Object.freeze({ history: 0, no_history: 100, documented_failure: 100, unknown: null });
  var PAYMENT_POINTS = Object.freeze({ full: 0, shortfall: 100, unknown: null });
  var OUTSOURCING_POINTS = Object.freeze({ absent: 0, present: 100, unknown: null });
  var LABELS = Object.freeze({ developmentMonths: '立项到上市月数', globalization: '全球化程度', recall: '车企正式召回历史', socialInsurance: '五险一金缴费', outsourcing: '外包或派遣用工', skuCount: '在售基础版本数' });

  function option(value, label, note) { return Object.freeze({ value: value, label: label, note: note }); }
  var INPUT_OPTIONS = Object.freeze({
    globalization: Object.freeze([
      option('unknown', '不知道', '未知保持 0–100 分范围。'),
      option('international_family', '同代车型已在多个市场销售', '需核对同代车型及硬件版本，不能只看品牌是否全球化。'),
      option('derived_family', '海外销售的是衍生版本', '海外版本与所购版本的关系仍需核对。'),
      option('global_design', '厂家宣称按全球标准设计', '设计宣传不等于已在海外通过准入并销售。'),
      option('china_only', '已确认中国市场专属', '仅按个人全球化选购偏好计分。'),
      option('planned', '仅有海外销售计划', '计划不等于上市事实，按未知处理。')
    ]),
    recall: Object.freeze([
      option('unknown', '不知道 / 没找到', '搜索不到公告不能证明从未召回。'),
      option('history', '找到该车企正式召回公告', '需匹配车企主体；召回过其他车型可以构成车企历史。'),
      option('no_history', '已有依据确认没有正式召回历史', '这是用户输入的判断，不是系统核实的事实。'),
      option('documented_failure', '有证据表明应召回却未履行', '需提供具体事件和证据，不能由没有搜索结果推断。')
    ]),
    socialInsurance: Object.freeze([
      option('unknown', '不知道 / 只看到招聘承诺', '部分员工信息或招聘文案不能证明全部员工足额缴费。'),
      option('full', '有依据确认范围内足额缴纳', '应核对制造企业主体、员工范围与时间。'),
      option('shortfall', '有依据确认仍有欠缴 / 不足额', '只计入用户确认的现存问题，不自动认定违法。')
    ]),
    outsourcing: Object.freeze([
      option('unknown', '不知道', '未知不能作为有外包或无外包的事实。'),
      option('absent', '有依据确认范围内没有外包 / 派遣员工', '应核对制造企业主体、岗位范围与时间。'),
      option('present', '有依据确认有外包 / 派遣员工', '普通零部件采购和独立经销商人员不自动算制造企业外包员工。')
    ])
  });

  function own(object, key) { return Object.prototype.hasOwnProperty.call(object, key); }
  function isMissing(value) { return value === undefined || value === null; }
  function enumValue(input, field, allowed) {
    var value = input[field];
    if (isMissing(value)) return 'unknown';
    if (typeof value !== 'string' || !own(allowed, value)) throw new TypeError(field + ' 的选项无效');
    return value;
  }
  function numberValue(input, field, positiveInteger) {
    var value = input[field];
    if (isMissing(value)) return null;
    // UI adapters must explicitly convert nonempty numeric text; the core never coerces text.
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new TypeError(field + ' 必须是有限数字或 null');
    if (positiveInteger ? (!Number.isSafeInteger(value) || value < 1) : value <= 0) throw new RangeError(field + (positiveInteger ? ' 必须是大于等于 1 的安全整数' : ' 必须大于 0'));
    return value;
  }
  function bounds(points) { return points === null ? { lower: 0, upper: 100 } : { lower: points, upper: points }; }
  function round(value) { return Math.round(value * 1000000) / 1000000; }
  function dimension(id, label, range, unknownInputs) {
    var weight = WEIGHTS[id];
    return {
      id: id, label: label, weight: weight, lower: round(range.lower), upper: round(range.upper),
      known: range.lower === range.upper,
      contributionLower: round(range.lower * weight / 100),
      contributionUpper: round(range.upper * weight / 100),
      unknownInputs: unknownInputs.slice()
    };
  }

  /**
   * calculateIndex(input) is pure: it does not read or verify external evidence.
   * developmentMonths: finite number > 0; skuCount: safe integer >= 1.
   * Enum fields use INPUT_OPTIONS values. Omitted/null fields mean unknown.
   * Numeric strings, blank strings, invalid enum values and invalid numbers throw.
   * lower/upper are weighted endpoints; score is set when endpoints are equal.
   * knownWeight is scoring information completeness (0–100), never accuracy.
   * inputsComplete separately records whether all six original inputs are known.
   */
  function calculateIndex(input) {
    if (input === undefined) input = {};
    if (input === null || typeof input !== 'object' || Array.isArray(input)) throw new TypeError('input 必须是对象');
    var values = {
      developmentMonths: numberValue(input, 'developmentMonths', false),
      globalization: enumValue(input, 'globalization', GLOBAL_POINTS),
      recall: enumValue(input, 'recall', RECALL_POINTS),
      socialInsurance: enumValue(input, 'socialInsurance', PAYMENT_POINTS),
      outsourcing: enumValue(input, 'outsourcing', OUTSOURCING_POINTS),
      skuCount: numberValue(input, 'skuCount', true)
    };
    var unknowns = [];
    function mark(field, unknown, reason) {
      if (unknown) unknowns.push({ field: field, label: LABELS[field], reason: reason || '尚未提供明确输入' });
      return unknown ? [field] : [];
    }
    var developmentUnknown = mark('developmentMonths', values.developmentMonths === null);
    var globalUnknown = mark('globalization', GLOBAL_POINTS[values.globalization] === null, values.globalization === 'planned' ? '海外销售计划不能证明已上市全球化' : undefined);
    var recallUnknown = mark('recall', RECALL_POINTS[values.recall] === null);
    var paymentUnknown = mark('socialInsurance', PAYMENT_POINTS[values.socialInsurance] === null);
    var outsourcingUnknown = mark('outsourcing', OUTSOURCING_POINTS[values.outsourcing] === null);
    var skuUnknown = mark('skuCount', values.skuCount === null);

    var development = bounds(values.developmentMonths === null ? null : Math.min(100, Math.max(0, (36 - values.developmentMonths) / 18 * 100)));
    var payment = bounds(PAYMENT_POINTS[values.socialInsurance]);
    var outsourcing = bounds(OUTSOURCING_POINTS[values.outsourcing]);
    var labor = { lower: Math.max(payment.lower, outsourcing.lower), upper: Math.max(payment.upper, outsourcing.upper) };
    var skuPoints = values.skuCount === null ? null : values.skuCount <= 3 ? 0 : values.skuCount <= 5 ? 30 : values.skuCount <= 8 ? 60 : 100;
    var dimensions = [
      dimension('development', '开发周期', development, developmentUnknown),
      dimension('globalization', '全球化', bounds(GLOBAL_POINTS[values.globalization]), globalUnknown),
      dimension('recall', '正式召回历史', bounds(RECALL_POINTS[values.recall]), recallUnknown),
      dimension('labor', '用工与缴费', labor, paymentUnknown.concat(outsourcingUnknown)),
      dimension('sku', '基础版本数量', bounds(skuPoints), skuUnknown)
    ];
    var lower = round(dimensions.reduce(function (sum, entry) { return sum + entry.contributionLower; }, 0));
    var upper = round(dimensions.reduce(function (sum, entry) { return sum + entry.contributionUpper; }, 0));
    var isExact = lower === upper;
    var knownWeight = dimensions.reduce(function (sum, entry) { return sum + (entry.known ? entry.weight : 0); }, 0);
    var largestGap = null;
    dimensions.forEach(function (entry) {
      var gap = entry.contributionUpper - entry.contributionLower;
      if (gap > 0 && (!largestGap || gap > largestGap.contributionUpper - largestGap.contributionLower)) largestGap = entry;
    });
    var objections = [];
    if (values.socialInsurance === 'shortfall') objections.push({ code: 'social_insurance_shortfall', message: '按你的输入，存在五险一金欠缴或不足额；与你的选购偏好不符。' });
    if (values.outsourcing === 'present') objections.push({ code: 'outsourcing_present', message: '按你的输入，有外包或派遣员工；按你的选购偏好不建议购买。' });
    if (values.recall === 'no_history') objections.push({ code: 'no_recall_history', message: '按你的输入，已确认没有正式召回历史；与你的选购偏好不符。' });
    if (values.recall === 'documented_failure') objections.push({ code: 'recall_failure', message: '按你的输入，有应召回却未履行的证据；购前应核查具体事实。' });
    if (values.globalization === 'china_only') objections.push({ code: 'china_only', message: '按你的输入，这是中国市场专属车型；不符合优先选择全球化车型的偏好。' });
    if (values.skuCount !== null && values.skuCount >= 9) objections.push({ code: 'many_skus', message: '按你的输入，在售基础版本达到 9 个；按本工具设定应关注版本数量与验证负担。' });
    return {
      version: '1.0.0', evidenceStatus: 'user_input_unverified', inputs: values,
      lower: lower, upper: upper, score: isExact ? lower : null, isExact: isExact,
      inputsComplete: unknowns.length === 0, knownWeight: knownWeight,
      dimensions: dimensions, unknowns: unknowns, objections: objections, largestGap: largestGap,
      comparisonWarning: '两辆车的区间重叠时，不能据此确定谁更接近速成车；相同总分也可能来自不同维度。结果是个人偏好关注指数，不是经统计校准的速成车概率。',
      notice: '所有数据来自你的输入，系统没有核实证据。指数越高，越需要关注相应特征；它不表示事故、质量缺陷或速成车的真实概率。'
    };
  }
  return Object.freeze({ calculateIndex: calculateIndex, WEIGHTS: WEIGHTS, INPUT_OPTIONS: INPUT_OPTIONS });
});
