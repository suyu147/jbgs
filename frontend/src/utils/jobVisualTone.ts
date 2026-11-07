export type JobVisualTone = 'mint' | 'blue' | 'violet' | 'coral'

// Keep a role's accent stable across search, recommendations and favorites.
export function jobVisualTone(field = '', name = ''): JobVisualTone {
  for (const subject of [field, name]) {
    if (/人工智能|机器学习|深度学习|大模型|算法|AIGC/i.test(subject)) return 'violet'
    if (/设计|创意|产品|运营|营销|教育|培训/.test(subject)) return 'coral'
    if (/数据|分析|云计算|云原生|网络|安全|软件|开发/.test(subject)) return 'blue'
    if (/制造|自动化|机器人/.test(subject)) return 'mint'
  }
  return 'mint'
}
