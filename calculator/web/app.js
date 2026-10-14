'use strict';
(function () {
  const api = window.QuickCarScoring;
  const form = document.getElementById('calculator');
  const fields = Object.fromEntries(Array.from(form.elements).filter(e => e.name).map(e => [e.name, e]));
  const byId = id => document.getElementById(id);
  const storageKey = 'quickcar-calculator-draft-v1';
  let current = null;
  let hasCalculated = false;
  let toastTimer;
  const fmt = n => Number.isInteger(n) ? String(n) : n.toFixed(1);
  const boundsText = (low, high) => low === high ? fmt(low) : fmt(low) + '–' + fmt(high);
  function toast(text) {
    clearTimeout(toastTimer); byId('toast').textContent = text; byId('toast').hidden = false;
    toastTimer = setTimeout(() => { byId('toast').hidden = true; }, 3500);
  }
  function readNumber(name, integer) {
    const control = fields[name];
    const raw = control.value.trim();
    if (control.validity.badInput) throw new Error(integer ? '配置数量请填写正整数，或留空表示不知道。' : '开发时间请填写大于0的月份数，或留空。');
    if (raw === '') return null;
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0 || (integer && !Number.isInteger(value))) {
      throw new Error(integer ? '配置数量请填写正整数，不能填写0、小数或负数。' : '开发时间必须是大于0的有效月份数。');
    }
    return value;
  }
  function readInputs() {
    return { developmentMonths: readNumber('developmentMonths', false), globalization: fields.globalization.value,
      recall: fields.recall.value, socialInsurance: fields.socialInsurance.value,
      outsourcing: fields.outsourcing.value, skuCount: readNumber('skuCount', true) };
  }
  function selectedText(name) { return fields[name].options[fields[name].selectedIndex].textContent; }
  function render(result) {
    byId('result-car').textContent = fields.carName.value.trim() || '未填写车型 · 仅按本次输入计算';
    byId('score-value').textContent = boundsText(result.lower, result.upper);
    byId('result-badge').textContent = result.knownWeight === 0 ? '资料不足' : result.isExact ? '计分已确定' : '存在待核项';
    byId('score-caption').textContent = result.isExact ? '分值已确定；输入的真实性仍需核验。' : '最低 ' + fmt(result.lower) + ' · 最高 ' + fmt(result.upper) + '，没有默认中点。';
    byId('range-fill').style.left = result.lower + '%'; byId('range-fill').style.width = (result.upper - result.lower) + '%';
    ['low', 'high'].forEach((key) => { const dot = byId('range-' + key); dot.style.left = (key === 'low' ? result.lower : result.upper) + '%'; dot.style.display = 'block'; });
    byId('interpretation').textContent = result.knownWeight === 0 ? '当前全部计分维度未知，0–100几乎没有判断信息。先补一项有出处的资料；0分下界不表示更安全。' : '分数越高，越符合本指南的关注特征。区间来自缺失资料，不是“速成概率”或事故风险。与其他车型的区间重叠时，不能确定谁最终分数更高。';
    byId('coverage-value').textContent = fmt(result.knownWeight) + '%'; byId('coverage-fill').style.width = result.knownWeight + '%';
    const breakdown = byId('breakdown'); breakdown.replaceChildren();
    result.dimensions.forEach(d => {
      const row = document.createElement('div'); row.className = 'dimension';
      const name = document.createElement('div'); name.className = 'dimension-name'; name.textContent = d.label;
      const weight = document.createElement('span'); weight.textContent = d.weight + '%'; name.append(weight);
      const value = document.createElement('div'); value.className = 'dimension-value'; value.textContent = boundsText(d.contributionLower, d.contributionUpper) + '分';
      const state = document.createElement('small'); state.textContent = d.known ? '已计入' : '待补证'; value.append(state); row.append(name, value); breakdown.append(row);
    });
    const gaps = result.dimensions.filter(d => !d.known).slice().sort((a, b) => (b.contributionUpper - b.contributionLower) - (a.contributionUpper - a.contributionLower));
    const rawMissing = result.unknowns.length ? ' 仍待核的输入：' + result.unknowns.map(x => x.label).join('、') + '。' : '';
    byId('next-evidence').textContent = (gaps.length ? gaps.map(d => d.label + '（最多缩小' + fmt(d.contributionUpper - d.contributionLower) + '分）').join('、') + '。从前往后补充可信资料，更容易缩小区间。' : '各计分维度已确定。下一步核对原始出处、年款、生产主体及时间范围；计分完整不代表资料真实。') + rawMissing;
    const notices = [];
    if (fields.outsourcing.value === 'present') notices.push('按你的购车偏好：有外包/派遣员工，不建议购买。');
    if (fields.socialInsurance.value === 'shortfall') notices.push('按你的购车偏好：存在未整改的欠缴，不建议购买。');
    if (fields.recall.value === 'no_history') notices.push('按你的购车偏好：没有正式召回历史，不建议购买。');
    if (fields.recall.value === 'documented_failure') notices.push('召回整改问题需要单独核查。');
    if (fields.globalization.value === 'china_only') notices.push('中国专属车型不满足全球化优先偏好。');
    if (current.inputs.skuCount !== null && current.inputs.skuCount >= 9) notices.push('SKU已达本指南“较多”的阈值。');
    byId('objections').replaceChildren(); byId('objections').hidden = notices.length === 0;
    if (notices.length) { const heading = document.createElement('strong'); heading.textContent = '这些条件不能被低总分抵消'; byId('objections').append(heading); notices.forEach(text => { const p = document.createElement('p'); p.textContent = text; byId('objections').append(p); }); }
    byId('result-details').hidden = false;
  }
  function calculate(scroll) {
    byId('form-error').hidden = true;
    try {
      if (!api) throw new Error('计算模块未加载，请刷新页面后再试。');
      const inputs = readInputs(); const result = api.calculateIndex(inputs);
      current = { inputs, result }; render(result); hasCalculated = true;
      if (scroll && window.innerWidth <= 760) byId('result-panel').scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    } catch (error) {
      current = null; byId('form-error').textContent = error.message; byId('form-error').hidden = false;
      byId('result-details').hidden = true; byId('score-value').textContent = '—'; byId('score-caption').textContent = '输入需修正，当前没有有效结果。'; byId('result-badge').textContent = '检查输入';
    }
  }
  form.addEventListener('submit', e => { e.preventDefault(); calculate(true); });
  form.addEventListener('input', () => { if (hasCalculated) calculate(false); });
  form.addEventListener('change', () => { if (hasCalculated) calculate(false); });
  byId('reset').addEventListener('click', () => {
    HTMLFormElement.prototype.reset.call(form); hasCalculated = false; current = null; byId('form-error').hidden = true;
    byId('result-details').hidden = true; byId('score-value').textContent = '—'; byId('score-caption').textContent = '填你知道的，不知道的留空。'; byId('result-badge').textContent = '等你填写';
    byId('result-car').textContent = '每一个分数，都有来由。'; byId('range-fill').style.width = '0'; ['low', 'high'].forEach(k => { byId('range-' + k).style.display = 'none'; });
    byId('interpretation').textContent = '这个指数将你的购车偏好变成计分。它不是“成为速成车的概率”，也不是安全测评。'; toast('已清空本次输入；保存的草稿可单独删除。');
  });
  byId('example').addEventListener('click', () => {
    HTMLFormElement.prototype.reset.call(form); fields.carName.value = '虚拟示例车 · 非真实车型'; fields.developmentMonths.value = '24'; fields.globalization.value = 'international_family'; fields.recall.value = 'history'; fields.skuCount.value = '4';
    fields.evidenceNotes.value = '这是演示公式的虚拟输入，不对应任何真实车企或车型。'; calculate(true); toast('已载入虚拟示例，用工两项仍未知。');
  });
  byId('save-draft').addEventListener('click', () => { try { readInputs(); const draft = Object.fromEntries(Object.entries(fields).map(([name, field]) => [name, field.value])); localStorage.setItem(storageKey, JSON.stringify({ version: 1, fields: draft })); toast('草稿已保存在本机浏览器。'); } catch (e) { toast('未保存：' + e.message); } });
  byId('restore-draft').addEventListener('click', () => { try { const value = localStorage.getItem(storageKey); if (!value) { toast('本机还没有保存的草稿。'); return; } const draft = JSON.parse(value); if (draft.version !== 1 || !draft.fields || typeof draft.fields !== 'object') throw new Error('草稿格式不支持'); HTMLFormElement.prototype.reset.call(form); Object.entries(fields).forEach(([name, field]) => { if (typeof draft.fields[name] === 'string') field.value = draft.fields[name].slice(0, field.maxLength > 0 ? field.maxLength : 4000); }); calculate(false); toast('已读取本机草稿。'); } catch (e) { toast('无法读取草稿，请删除后重新保存。'); } });
  byId('delete-draft').addEventListener('click', () => { try { localStorage.removeItem(storageKey); toast('保存的草稿已删除。'); } catch (e) { toast('当前浏览器不允许管理本机存储。'); } });
  function summaryText() {
    const r = current.result;
    return ['速成车关注指数 · 用户输入，未经核验', fields.carName.value.trim() || '未填写车型', '指数：' + boundsText(r.lower, r.upper) + ' / 100；已确定计分权重：' + r.knownWeight + '%',
      '开发：' + (current.inputs.developmentMonths === null ? '未知' : current.inputs.developmentMonths + '个月'), '全球化：' + selectedText('globalization'), '召回：' + selectedText('recall'), '五险一金：' + selectedText('socialInsurance'), '外包/派遣：' + selectedText('outsourcing'), '基本配置：' + (current.inputs.skuCount === null ? '未知' : current.inputs.skuCount + '款'), '高分表示更多关注特征，不是事故或速成概率；区间重叠无法确定高低。', '规则：https://github.com/ElonX90/QuickCarBuyingGuide/blob/main/docs/INDEX_FAQ.md'].join('\n');
  }
  byId('copy-result').addEventListener('click', async () => { if (!current) return; const text = summaryText(); try { if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); } else { const temp = document.createElement('textarea'); temp.value = text; temp.style.position = 'fixed'; temp.style.opacity = '0'; document.body.append(temp); temp.select(); const copied = document.execCommand('copy'); temp.remove(); if (!copied) throw new Error('复制失败'); } toast('结果已复制，来源笔记未包含在摘要中。'); } catch (e) { toast('浏览器阻止复制，可以使用“下载记录”。'); } });
  byId('export-result').addEventListener('click', () => { if (!current) return; const record = { calculatorVersion: '0.1.0', evidenceStatus: 'user_reported_unreviewed', exportedAt: new Date().toISOString(), car: fields.carName.value.trim(), inputs: current.inputs, result: current.result, evidenceNotes: fields.evidenceNotes.value, interpretation: '关注指数，不是概率。权重为编辑偏好。' }; const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: 'application/json;charset=utf-8' })); const link = document.createElement('a'); link.href = url; link.download = 'quickcar-calculation.json'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); toast('记录包含来源笔记，请按需保管和分享。'); });
})();
