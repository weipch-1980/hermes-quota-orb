import {
  Button,
  cn,
  compactNumber,
  haptic,
  host,
  Popover,
  PopoverContent,
  PopoverTrigger,
  StatusDot,
  Tip,
  usePluginI18n,
  useQuery,
  useValue
} from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'quota-orb'
let pluginContext = null

const emptySession = { calls: 0, input: 0, output: 0, total: 0 }
const emptySnapshot = {
  ok: false,
  day: '',
  today: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, total_tokens: 0, api_calls: 0, sessions: 0, by_model: [] },
  quota: { available: false, windows: [], details: [] }
}

function finite(value) {
  return typeof value === 'number' && Number.isFinite(value)
}

function lowestRemaining(snapshot) {
  const values = (snapshot?.quota?.windows || [])
    .map(window => window.remaining_percent)
    .filter(finite)
  return values.length ? Math.min(...values) : null
}

function toneFor(remaining) {
  if (!finite(remaining)) return 'muted'
  if (remaining <= 10) return 'bad'
  if (remaining <= 30) return 'warn'
  return 'good'
}

function formatReset(value) {
  if (!value) return '—'
  const target = new Date(value)
  if (Number.isNaN(target.getTime())) return '—'
  const diff = Math.max(0, target.getTime() - Date.now())
  const minutes = Math.floor(diff / 60000)
  const relative = minutes >= 1440
    ? `${Math.floor(minutes / 1440)}d ${Math.floor((minutes % 1440) / 60)}h`
    : minutes >= 60
      ? `${Math.floor(minutes / 60)}h ${minutes % 60}m`
      : `${minutes}m`
  return `${target.toLocaleString()} (${relative})`
}

function reportText(snapshot, t) {
  const today = snapshot?.today || emptySnapshot.today
  const windows = snapshot?.quota?.windows || []
  const quota = windows.length
    ? windows.map(window => `${window.label}: ${Math.round(window.remaining_percent ?? 0)}%`).join(' · ')
    : t('quotaUnavailable')
  return t('dailyReportBody', compactNumber(today.total_tokens || 0), today.api_calls || 0, quota)
}

function useQuotaData() {
  const sessionId = useValue(host.state.activeSessionId)
  const profile = useValue(host.state.profile)
  const model = useValue(host.state.model)

  const sessionQuery = useQuery({
    queryKey: [ID, profile, 'session', sessionId],
    queryFn: () => sessionId ? host.request('session.usage', { session_id: sessionId }) : Promise.resolve(emptySession),
    enabled: Boolean(sessionId),
    refetchInterval: 15000,
    staleTime: 5000,
    retry: 1
  })

  const snapshotQuery = useQuery({
    queryKey: [ID, profile, 'snapshot'],
    queryFn: () => pluginContext.ctx.rest('/snapshot', { timeoutMs: 20000 }),
    refetchInterval: 60000,
    staleTime: 30000,
    retry: 1
  })

  return {
    model,
    session: sessionQuery.data || emptySession,
    snapshot: snapshotQuery.data || emptySnapshot,
    isLoading: sessionQuery.isLoading || snapshotQuery.isLoading,
    error: sessionQuery.error || snapshotQuery.error,
    refresh: async () => Promise.all([sessionQuery.refetch(), snapshotQuery.refetch()])
  }
}

function WindowRow({ window }) {
  const t = usePluginI18n(ID)
  const remaining = finite(window.remaining_percent) ? Math.max(0, Math.min(100, window.remaining_percent)) : null
  return jsxs('div', {
    className: 'flex flex-col gap-1 border-b border-(--ui-stroke-secondary) py-2 last:border-b-0',
    children: [
      jsxs('div', {
        className: 'flex items-center justify-between gap-3',
        children: [
          jsxs('span', {
            className: 'inline-flex items-center gap-1.5 text-xs text-(--ui-text-secondary)',
            children: [jsx(StatusDot, { tone: toneFor(remaining) }), window.label || t('quota')]
          }),
          jsx('strong', {
            className: 'text-xs font-medium',
            children: remaining === null ? t('unknown') : `${Math.round(remaining)}%`
          })
        ]
      }),
      jsx('div', {
        className: 'h-1.5 overflow-hidden rounded-full bg-(--ui-stroke-secondary)',
        role: 'progressbar',
        'aria-label': `${window.label || t('quota')} ${remaining ?? 0}%`,
        'aria-valuemin': 0,
        'aria-valuemax': 100,
        'aria-valuenow': remaining ?? 0,
        children: jsx('div', {
          className: 'h-full rounded-full bg-(--ui-accent) transition-[width]',
          style: { width: `${remaining ?? 0}%` }
        })
      }),
      jsx('span', {
        className: 'text-[0.6875rem] text-(--ui-text-quaternary)',
        children: t('resets', formatReset(window.reset_at))
      })
    ]
  })
}

function DetailPanel({ data }) {
  const t = usePluginI18n(ID)
  const { model, session, snapshot, isLoading, error, refresh } = data
  const today = snapshot.today || emptySnapshot.today
  const quota = snapshot.quota || emptySnapshot.quota

  return jsxs('div', {
    className: 'flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-3 p-3 text-xs',
    children: [
      jsxs('div', {
        className: 'flex items-start justify-between gap-3',
        children: [
          jsxs('div', {
            children: [
              jsx('div', { className: 'text-sm font-medium', children: t('title') }),
              jsx('div', { className: 'mt-0.5 text-(--ui-text-quaternary)', children: model || t('unknownModel') })
            ]
          }),
          jsx(Button, {
            size: 'sm',
            variant: 'ghost',
            disabled: isLoading,
            onClick: () => void refresh(),
            children: isLoading ? t('refreshing') : t('refresh')
          })
        ]
      }),
      error ? jsx('div', {
        className: 'rounded-md border border-(--ui-stroke-secondary) p-2 text-(--ui-text-secondary)',
        children: t('restartHermes')
      }) : null,
      jsxs('div', {
        className: 'grid grid-cols-2 gap-2',
        children: [
          jsx(Metric, { label: t('todayTokens'), value: compactNumber(today.total_tokens || 0) }),
          jsx(Metric, { label: t('sessionTokens'), value: compactNumber(session.total || 0) }),
          jsx(Metric, { label: t('input'), value: compactNumber(today.input_tokens || 0) }),
          jsx(Metric, { label: t('output'), value: compactNumber(today.output_tokens || 0) }),
          jsx(Metric, { label: t('cacheRead'), value: compactNumber(today.cache_read_tokens || 0) }),
          jsx(Metric, { label: t('apiCalls'), value: compactNumber(today.api_calls || 0) })
        ]
      }),
      jsxs('div', {
        children: [
          jsxs('div', {
            className: 'flex items-center justify-between border-b border-(--ui-stroke-secondary) pb-1.5',
            children: [
              jsx('span', { className: 'font-medium', children: t('providerQuota') }),
              jsx('span', { className: 'text-(--ui-text-quaternary)', children: [quota.provider, quota.plan].filter(Boolean).join(' · ') || t('unknown') })
            ]
          }),
          quota.windows?.length
            ? quota.windows.map((window, index) => jsx(WindowRow, { window }, `${window.label}-${index}`))
            : jsx('div', { className: 'py-3 text-(--ui-text-tertiary)', children: t('quotaUnavailable') })
        ]
      }),
      jsx('div', {
        className: 'text-[0.6875rem] leading-relaxed text-(--ui-text-quaternary)',
        children: t('dataNote')
      })
    ]
  })
}

function Metric({ label, value }) {
  return jsxs('div', {
    className: 'rounded-md border border-(--ui-stroke-secondary) p-2',
    children: [
      jsx('div', { className: 'text-(--ui-text-quaternary)', children: label }),
      jsx('div', { className: 'mt-0.5 text-sm font-medium', children: value })
    ]
  })
}

function QuotaOrb() {
  const t = usePluginI18n(ID)
  const data = useQuotaData()
  const remaining = lowestRemaining(data.snapshot)
  const label = finite(remaining) ? `${Math.round(remaining)}%` : '—'
  const tone = toneFor(remaining)

  return jsx(Popover, {
    children: jsxs('div', {
      className: 'flex h-full w-full items-center justify-center',
      children: [
        jsx(PopoverTrigger, {
          asChild: true,
          children: jsxs('button', {
            type: 'button',
            'aria-label': t('openDetails'),
            onClick: () => haptic('tap'),
            className: cn(
              'relative flex size-20 flex-col items-center justify-center rounded-full border border-(--ui-stroke-secondary)',
              'bg-(--ui-bg-editor) text-foreground shadow-lg transition-transform hover:scale-105 focus:outline-none'
            ),
            style: {
              width: '80px',
              height: '80px',
              background: finite(remaining)
                ? `radial-gradient(circle at center, var(--ui-bg-editor) 57%, transparent 58%), conic-gradient(var(--ui-accent) ${remaining}%, var(--ui-stroke-secondary) 0)`
                : 'var(--ui-bg-editor)'
            },
            children: [
              jsx(StatusDot, { tone }),
              jsx('strong', { className: 'mt-1 text-sm font-semibold', children: label }),
              jsx('span', { className: 'text-[0.625rem] text-(--ui-text-quaternary)', children: t('remaining') })
            ]
          })
        }),
        jsx(PopoverContent, {
          align: 'end',
          side: 'left',
          className: 'w-auto p-0',
          children: jsx(DetailPanel, { data })
        })
      ]
    })
  })
}

function StatusChip() {
  const t = usePluginI18n(ID)
  const data = useQuotaData()
  const remaining = lowestRemaining(data.snapshot)
  const today = data.snapshot.today || emptySnapshot.today
  const text = finite(remaining)
    ? `${Math.round(remaining)}% · ${compactNumber(today.total_tokens || 0)} tok`
    : `${compactNumber(today.total_tokens || 0)} tok`

  return jsx(Tip, {
    label: t('chipTip'),
    children: jsxs('button', {
      type: 'button',
      className: cn(
        'inline-flex h-full items-center gap-1.5 px-1.5 text-[0.6875rem] transition-colors',
        'text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground'
      ),
      onClick: () => {
        haptic('tap')
        host.notify({ kind: 'info', title: t('title'), message: reportText(data.snapshot, t) })
      },
      children: [jsx(StatusDot, { tone: toneFor(remaining) }), jsx('span', { children: text })]
    })
  })
}

function scheduleDailyReports(ctx) {
  const check = async () => {
    const hour = Math.max(0, Math.min(23, Number(ctx.storage.get('reportHour', 18)) || 18))
    const now = new Date()
    const day = now.toLocaleDateString('en-CA')
    const lastReportDay = ctx.storage.get('lastReportDay', '')
    if (now.getHours() < hour || lastReportDay === day) return

    try {
      const snapshot = await ctx.rest('/snapshot', { timeoutMs: 20000 })
      const t = ctx.i18n.t
      const body = reportText(snapshot, t)
      host.notify({ kind: 'info', title: t('dailyReportTitle'), message: body })
      ctx.os.notify({ title: t('dailyReportTitle'), body })
      ctx.storage.set('lastReportDay', day)
    } catch (error) {
      host.notifyError(error, ctx.i18n.t('reportFailed'))
    }
  }

  const timer = window.setInterval(() => void check(), 60000)
  void check()
  ctx.onDispose(() => window.clearInterval(timer))
}

export default {
  id: ID,
  name: 'Quota Orb',
  description: 'Live token use, provider quota, reset times, and daily reports.',
  register(ctx) {
    pluginContext = { ctx }
    ctx.onDispose(() => { pluginContext = null })
    ctx.i18n.register({
      en: {
        title: 'Quota Orb',
        quota: 'Quota',
        remaining: 'left',
        unknown: 'Unknown',
        unknownModel: 'No active model',
        openDetails: 'Open quota details',
        todayTokens: 'Today tokens',
        sessionTokens: 'Session tokens',
        input: 'Input',
        output: 'Output',
        cacheRead: 'Cache read',
        apiCalls: 'API calls',
        providerQuota: 'Provider quota',
        quotaUnavailable: 'Provider quota is unavailable; local token totals still work.',
        resets: value => `Resets: ${value}`,
        refresh: 'Refresh',
        refreshing: 'Refreshing…',
        restartHermes: 'Restart Hermes Desktop once to activate the quota backend. Local session totals remain available.',
        partialData: 'Some data could not be refreshed. Showing the latest available values.',
        dataNote: 'Token totals come from local Hermes sessions. Quota percentages and reset times come from the provider when its account-usage API is available.',
        chipTip: 'Today tokens and the lowest remaining provider quota',
        dailyReportTitle: 'Hermes daily usage report',
        dailyReportBody: (tokens, calls, quota) => `Today: ${tokens} tokens across ${calls} API calls. Remaining quota: ${quota}.`,
        reportFailed: 'Could not build the daily quota report.'
      },
      'zh-Hans': {
        title: '配额悬浮球',
        quota: '配额',
        remaining: '剩余',
        unknown: '未知',
        unknownModel: '暂无活动模型',
        openDetails: '打开配额详情',
        todayTokens: '今日 Token',
        sessionTokens: '当前会话',
        input: '输入',
        output: '输出',
        cacheRead: '缓存读取',
        apiCalls: 'API 调用',
        providerQuota: '提供商配额',
        quotaUnavailable: '提供商配额暂不可用；本地 Token 统计仍然有效。',
        resets: value => `重置：${value}`,
        refresh: '刷新',
        refreshing: '刷新中…',
        restartHermes: '请重启一次 Hermes Desktop 以启用配额后端；当前会话 Token 仍可正常显示。',
        partialData: '部分数据刷新失败，正在显示最近一次可用值。',
        dataNote: 'Token 来自本地 Hermes 会话；配额百分比和重置时间仅在提供商提供账户用量接口时显示。',
        chipTip: '今日 Token 与最低剩余配额',
        dailyReportTitle: 'Hermes 今日用量报告',
        dailyReportBody: (tokens, calls, quota) => `今日消耗 ${tokens} Token，共 ${calls} 次 API 调用。剩余配额：${quota}。`,
        reportFailed: '无法生成今日配额报告。'
      }
    })

    ctx.register({
      id: 'orb',
      area: 'panes',
      title: 'Quota Orb',
      data: { placement: 'floating', anchor: 'top-right', width: '112px', height: '112px' },
      render: () => jsx(QuotaOrb, {})
    })

    ctx.register({
      id: 'chip',
      area: 'statusBar.right',
      order: 125,
      render: () => jsx(StatusChip, {})
    })

    scheduleDailyReports(ctx)
  }
}
