const select = (id) => document.getElementById(id)
const modes = {
  supervisor: { name: 'Supervisor', description: '技术支持、销售和账单由 Supervisor 分流。' },
  manual: { name: '手写 ReAct', description: 'StateGraph 在模型决策与工具执行之间循环。' },
  prebuilt: { name: '预置 Agent', description: 'create_agent 使用相同工具，接管推理循环。' }
}
const quoteQuestion = '专业版 3 个席位买 2 个月，多少钱？'
const examples = {
  supervisor: [
    ['分析 429', '连续报错 429 怎么办？'],
    ['比较报价', quoteQuestion],
    ['查询发票', '上个月扣款后，我怎么开电子发票？'],
    ['申请退款', '我要申请退款'],
  ],
  manual: [
    ['比较报价', quoteQuestion],
    ['算术表达式', '计算 round(99 / 3.4, 2)'],
    ['验证拒绝边界', '计算 open("demo.txt")'],
  ],
  prebuilt: [
    ['比较报价', quoteQuestion],
    ['查询发票', '上个月扣款后，我怎么开电子发票？'],
    ['验证拒绝边界', '计算 open("demo.txt")'],
  ],
}
let mode = 'supervisor'
let sessionId = null
let running = false

function textNode(tag, value, className) {
  const node = document.createElement(tag)
  node.textContent = value
  if (className) node.className = className
  return node
}

function renderActions(container, actions) {
  container.replaceChildren(...actions.map(([label, value]) => {
    const button = textNode('button', label, 'chip')
    button.type = 'button'
    button.disabled = running
    button.addEventListener('click', () => run(value))
    return button
  }))
}

function clearConversation() {
  sessionId = null
  select('question').value = ''
  select('messages').replaceChildren(textNode('p', '选一个示例，或输入你的问题。', 'empty'))
  select('steps').replaceChildren(textNode('li', '运行后显示本轮调用顺序。', 'empty'))
  select('duration').textContent = ''
  select('quick-actions').hidden = true
  select('quick-actions').replaceChildren()
}

function displayTrace(result) {
  select('duration').textContent = `${result.elapsed_ms} ms`
  select('steps').replaceChildren(...result.trace.map((event) => {
    const step = textNode('li', '', `step ${event.status}`)
    const content = document.createElement('div')
    content.append(textNode('strong', event.node), textNode('p', event.detail))
    step.append(content)
    return step
  }))
}

function updateBusy(busy) {
  running = busy
  document.querySelectorAll('[data-mode], #reset, #send, .chip').forEach((button) => {
    button.disabled = busy
  })
}

async function fetchJson(path, options) {
  const response = await fetch(path, options)
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '请求失败，请稍后重试。')
  return body
}

async function run(message) {
  const text = message.trim()
  if (!text || running) return
  const log = select('messages')
  log.querySelector('.empty')?.remove()
  log.append(textNode('p', text, 'turn user'))
  select('question').value = ''
  updateBusy(true)
  try {
    const result = await fetchJson('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, message: text, session_id: sessionId })
    })
    sessionId = result.session_id
    log.append(textNode('p', result.reply, 'turn reply'))
    displayTrace(result)
    const quick = select('quick-actions')
    const actions = result.pending_order
      ? [['确认退款', '确认退款'], ['取消退款', '取消退款']]
      : (mode === 'supervisor' && result.route === 'refund' && result.reply.includes('请提供')
          ? [['演示订单 ORD-1001', 'ORD-1001'], ['需复核 ORD-1002', 'ORD-1002']] : [])
    renderActions(quick, actions)
    quick.hidden = !actions.length
  } catch (error) {
    log.append(textNode('p', error.message || '连接失败，请确认服务已启动。', 'turn error'))
  } finally {
    updateBusy(false)
    log.scrollTop = log.scrollHeight
  }
}

function showComparison(rows) {
  const wrapper = textNode('div', '', 'table-wrap')
  const table = document.createElement('table')
  const header = table.createTHead().insertRow()
  for (const label of ['架构', ...rows[0].cases.map(({ task }) => task), '通过', '中位耗时']) {
    const cell = textNode('th', label)
    cell.scope = 'col'
    header.append(cell)
  }
  const body = table.createTBody()
  for (const row of rows) {
    const line = body.insertRow()
    for (const value of [
      modes[row.mode].name, ...row.cases.map(({ passed }) => passed ? '通过' : '失败'),
      `${row.passed}/${row.cases.length}`, `${row.median_ms} ms`
    ]) line.append(textNode('td', value))
  }
  wrapper.append(table)
  select('comparison-results').replaceChildren(wrapper)
}

document.querySelectorAll('[data-mode]').forEach((button) => {
  button.addEventListener('click', () => {
    if (running || mode === button.dataset.mode) return
    mode = button.dataset.mode
    document.querySelectorAll('[data-mode]').forEach((item) => {
      item.setAttribute('aria-pressed', String(item.dataset.mode === mode))
    })
    select('mode-description').textContent = modes[mode].description
    clearConversation()
    renderActions(select('examples'), examples[mode])
  })
})

select('question-form').addEventListener('submit', (event) => {
  event.preventDefault()
  run(select('question').value)
})
select('reset').addEventListener('click', clearConversation)
select('compare').addEventListener('click', async (event) => {
  event.currentTarget.disabled = true
  try {
    showComparison(await fetchJson('/api/compare'))
  } catch (error) {
    select('comparison-results').replaceChildren(textNode('p', error.message, 'turn error'))
  } finally {
    select('compare').disabled = false
  }
})
renderActions(select('examples'), examples[mode])
fetchJson('/api/health').then(({ mode: current }) => {
  select('connection').textContent = current === 'demo' ? '本地演示 · 模拟业务数据' : '百炼 · 模拟业务数据'
}).catch(() => {
  select('connection').textContent = '连接失败'
})
