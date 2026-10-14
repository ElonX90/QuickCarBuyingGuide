const scoring = require('../../utils/scoring.js');
const HISTORY_KEY = 'quickcar-calculator-history-v1';
const OPTIONS = {
  globalization: [
    { value: 'unknown', label: '尚不了解 / 证据不足' },
    { value: 'international_family', label: '同代车型已在多个市场实际销售' },
    { value: 'derived_family', label: '海外衍生车型 / 对应配置尚未匹配' },
    { value: 'global_design', label: '宣称全球设计，尚未核实海外销售' },
    { value: 'china_only', label: '已核实仅在中国市场销售' },
    { value: 'planned', label: '仅有海外上市计划' }
  ],
  recall: [
    { value: 'unknown', label: '尚不了解 / 尚未查到记录' },
    { value: 'history', label: '有该车企的正式召回记录' },
    { value: 'no_history', label: '已有依据确认没有正式召回历史' },
    { value: 'documented_failure', label: '有证据证明应召回而未召回' }
  ],
  socialInsurance: [
    { value: 'unknown', label: '尚不了解 / 证据不足' },
    { value: 'full', label: '有全范围资料证明足额缴纳' },
    { value: 'shortfall', label: '有证据证明存在未解决的欠缴' }
  ],
  outsourcing: [
    { value: 'unknown', label: '尚不了解 / 证据不足' },
    { value: 'absent', label: '有全范围资料证明无外包 / 派遣' },
    { value: 'present', label: '有证据证明存在外包 / 派遣员工' }
  ]
};

function emptyFields() {
  return { developmentMonths: '', skuCount: '', globalizationIndex: 0,
    recallIndex: 0, socialInsuranceIndex: 0, outsourcingIndex: 0 };
}
function formatNumber(value) {
  return Number(Number(value).toFixed(1)).toString();
}
function formatScore(result) {
  return result.isExact ? formatNumber(result.lower) : formatNumber(result.lower) + '–' + formatNumber(result.upper);
}
function dateLabel(timestamp) {
  const date = new Date(timestamp);
  const pad = value => String(value).padStart(2, '0');
  return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + ' ' + pad(date.getHours()) + ':' + pad(date.getMinutes());
}
function parseNumeric(raw, isInteger, label) {
  const text = String(raw).trim();
  if (!text) return null;
  if (!(isInteger ? /^\d+$/ : /^(?:\d+(?:\.\d*)?|\.\d+)$/).test(text)) {
    throw new Error(label + (isInteger ? '请填写正整数，或留空表示未知。' : '请填写正数，或留空表示未知。'));
  }
  const value = Number(text);
  if (!Number.isFinite(value) || value <= 0) throw new Error(label + '必须大于 0，或留空表示未知。');
  return value;
}
function fieldsForInputs(inputs) {
  const result = { developmentMonths: inputs.developmentMonths == null ? '' : String(inputs.developmentMonths), skuCount: inputs.skuCount == null ? '' : String(inputs.skuCount) };
  Object.keys(OPTIONS).forEach(field => {
    const index = OPTIONS[field].findIndex(option => option.value === inputs[field]);
    result[field + 'Index'] = index < 0 ? 0 : index;
  });
  return result;
}
function toHistoryView(record) {
  const result = scoring.calculateIndex(record.inputs);
  return { id: record.id, inputs: record.inputs, timestamp: record.timestamp,
    isExample: !!record.isExample, dateLabel: dateLabel(record.timestamp), scoreDisplay: formatScore(result) };
}

Page({
  data: Object.assign(emptyFields(), {
    globalizationOptions: OPTIONS.globalization, recallOptions: OPTIONS.recall,
    socialInsuranceOptions: OPTIONS.socialInsurance, outsourcingOptions: OPTIONS.outsourcing,
    result: null, dimensionRows: [], scoreDisplay: '', largestGapText: '',
    error: '', isExample: false, history: []
  }),

  onLoad() {
    try {
      const stored = wx.getStorageSync(HISTORY_KEY);
      const history = (Array.isArray(stored) ? stored : []).slice(0, 5).filter(record => {
        try {
          if (!record || typeof record.id !== 'string' || !Number.isFinite(record.timestamp) || !record.inputs) return false;
          scoring.calculateIndex(record.inputs);
          return true;
        } catch (_) { return false; }
      }).map(toHistoryView);
      this.setData({ history });
    } catch (_) {
      this.setData({ history: [] });
    }
  },

  onNumberInput(event) {
    const field = event.currentTarget.dataset.field;
    if (field !== 'developmentMonths' && field !== 'skuCount') return;
    const patch = { result: null, error: '' };
    patch[field] = event.detail.value;
    this.setData(patch);
  },
  onPickerChange(event) {
    const field = event.currentTarget.dataset.field;
    const index = Number(event.detail.value);
    if (!OPTIONS[field] || !Number.isInteger(index) || !OPTIONS[field][index]) return;
    const patch = { result: null, error: '' };
    patch[field + 'Index'] = index;
    this.setData(patch);
  },
  getInputs() {
    const inputs = {
      developmentMonths: parseNumeric(this.data.developmentMonths, false, '研发月数'),
      skuCount: parseNumeric(this.data.skuCount, true, 'SKU 数量')
    };
    Object.keys(OPTIONS).forEach(field => { inputs[field] = OPTIONS[field][this.data[field + 'Index']].value; });
    return inputs;
  },
  displayResult(inputs, scroll) {
    const result = scoring.calculateIndex(inputs);
    const gap = result.largestGap;
    const width = gap ? gap.contributionUpper - gap.contributionLower : 0;
    this.setData({ result, error: '', scoreDisplay: formatScore(result),
      dimensionRows: result.dimensions.map(item => Object.assign({}, item, {
        display: item.contributionLower === item.contributionUpper ? formatNumber(item.contributionLower) : formatNumber(item.contributionLower) + '–' + formatNumber(item.contributionUpper)
      })),
      largestGapText: gap && width > 0 ? gap.label + '：可缩小约 ' + formatNumber(width) + ' 分的未知范围。' : ''
    }, () => {
      if (scroll) wx.pageScrollTo({ selector: '#result', duration: 300 });
    });
  },
  onCalculate() {
    try {
      this.displayResult(this.getInputs(), true);
    } catch (error) {
      this.setData({ result: null, error: error.message || '输入有误，请检查后再试。' });
    }
  },
  onClear() {
    this.setData(Object.assign(emptyFields(), { result: null, dimensionRows: [], scoreDisplay: '', largestGapText: '', error: '', isExample: false }));
  },
  onExample() {
    const inputs = { developmentMonths: 24, globalization: 'international_family', recall: 'history', socialInsurance: 'unknown', outsourcing: 'unknown', skuCount: 4 };
    this.setData(Object.assign(fieldsForInputs(inputs), { isExample: true, error: '', result: null }), () => {
      this.displayResult(inputs, true);
    });
  },
  onSaveHistory() {
    if (!this.data.result) return;
    try {
      const inputs = this.getInputs();
      scoring.calculateIndex(inputs);
      const key = JSON.stringify(inputs);
      const history = [{ id: String(Date.now()) + '-' + Math.random().toString(36).slice(2, 8), inputs, timestamp: Date.now(), isExample: this.data.isExample }]
        .concat(this.data.history.filter(item => JSON.stringify(item.inputs) !== key)).slice(0, 5);
      wx.setStorageSync(HISTORY_KEY, history.map(item => ({ id: item.id, inputs: item.inputs, timestamp: item.timestamp, isExample: item.isExample })));
      this.setData({ history: history.map(toHistoryView) });
      wx.showToast({ title: '已保存到本机', icon: 'success' });
    } catch (_) {
      wx.showToast({ title: '本机保存失败', icon: 'none' });
    }
  },
  onLoadHistory(event) {
    const record = this.data.history.find(item => item.id === event.currentTarget.dataset.id);
    if (!record) return;
    this.setData(Object.assign(fieldsForInputs(record.inputs), { isExample: record.isExample, error: '', result: null }), () => {
      try { this.displayResult(record.inputs, true); }
      catch (_) { this.setData({ error: '这条本机记录无法计算，请重新填写。', result: null }); }
    });
  },
  onClearHistory() {
    wx.showModal({ title: '删除本机记录', content: '仅删除这台设备保存的计算记录。当前输入会保留。', confirmText: '删除', confirmColor: '#25644c', success: response => {
      if (!response.confirm) return;
      try {
        wx.removeStorageSync(HISTORY_KEY);
        this.setData({ history: [] });
      } catch (_) { wx.showToast({ title: '删除失败，请重试', icon: 'none' }); }
    } });
  },
  onShareAppMessage() {
    return { title: '速成车关注指数计算器｜输入事实，查看关注项', path: '/pages/index/index' };
  }
});
