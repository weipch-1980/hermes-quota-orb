import {
  atom,
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
let localeBundles = null
const $languagePreferences = atom({})
const languageModes = new Set(['auto', 'zh', 'en'])

function profileLanguageKey(profile) {
  return profile || 'default'
}

function reportDayKey(profile) {
  return `lastReportDay:${profileLanguageKey(profile)}`
}

function languageModeFor(profile, preferences) {
  const profileKey = profileLanguageKey(profile)
  if (Object.prototype.hasOwnProperty.call(preferences, profileKey)) return preferences[profileKey]
  const stored = pluginContext?.ctx.storage.get(`language:${profileKey}`, 'auto')
  return languageModes.has(stored) ? stored : 'auto'
}

function persistLanguageMode(profile, mode) {
  const profileKey = profileLanguageKey(profile)
  const next = languageModes.has(mode) ? mode : 'auto'
  pluginContext?.ctx.storage.set(`language:${profileKey}`, next)
  $languagePreferences.set({ ...$languagePreferences.get(), [profileKey]: next })
}

function translateBundle(locale, key, args) {
  const message = localeBundles?.[locale]?.[key] ?? localeBundles?.en?.[key]
  if (typeof message === 'function') return message(...args)
  return message ?? key
}

function quotaTranslate(profile, key, ...args) {
  const mode = languageModeFor(profile, $languagePreferences.get())
  return mode === 'auto'
    ? pluginContext?.ctx.i18n.t(key, ...args) ?? key
    : translateBundle(mode, key, args)
}

function useQuotaI18n(profile) {
  const appT = usePluginI18n(ID)
  const preferences = useValue($languagePreferences)
  const languageMode = languageModeFor(profile, preferences)
  const t = languageMode === 'auto'
    ? appT
    : (key, ...args) => translateBundle(languageMode, key, args)
  return {
    t,
    languageMode,
    setLanguageMode: mode => persistLanguageMode(profile, mode)
  }
}

const emptySession = { calls: 0, input: 0, output: 0, total: 0 }
const emptySnapshot = {
  ok: false,
  day: '',
  today: {
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    total_tokens: 0,
    api_calls: 0,
    sessions: 0,
    by_model: [],
    by_provider: []
  },
  quota: { available: false, windows: [], details: [] }
}

function finite(value) {
  return typeof value === 'number' && Number.isFinite(value)
}

function clampPercent(value) {
  return finite(value) ? Math.max(0, Math.min(100, value)) : null
}

function liquidGeometry(remaining) {
  const clamped = clampPercent(remaining)
  const surfaceY = clamped === null ? 84 : 84 - (clamped * 0.76)
  const fillDepth = clamped === null ? 0 : Math.max(0, 84 - surfaceY)
  const waveAmplitude = fillDepth === 0 ? 0 : Math.min(8, fillDepth * 0.35)
  const hasLiquid = fillDepth > 0
  return { clamped, surfaceY, fillDepth, waveAmplitude, hasLiquid }
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
    ? windows.map(window => {
        const remaining = clampPercent(window.remaining_percent)
        const value = remaining === null ? t('unknown') : `${Math.round(remaining)}%`
        return `${window.label || t('quota')}: ${value}`
      }).join(' · ')
    : t('quotaUnavailable')
  return t('dailyReportBody', compactNumber(today.total_tokens || 0), today.api_calls || 0, quota)
}

function providerGroups(today) {
  if (Array.isArray(today.by_provider) && today.by_provider.length) return today.by_provider
  const groups = new Map()
  for (const item of today.by_model || []) {
    const provider = item.provider || 'unknown'
    const group = groups.get(provider) || {
      provider,
      total_tokens: 0,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      api_calls: 0,
      sessions: 0,
      models: []
    }
    for (const key of ['total_tokens', 'input_tokens', 'output_tokens', 'cache_read_tokens', 'api_calls', 'sessions']) {
      group[key] += Number(item[key] || 0)
    }
    group.models.push(item)
    groups.set(provider, group)
  }
  return [...groups.values()].sort((a, b) => b.total_tokens - a.total_tokens)
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
    profile,
    model,
    session: sessionQuery.data || emptySession,
    snapshot: snapshotQuery.data || emptySnapshot,
    isLoading: sessionQuery.isLoading || snapshotQuery.isLoading,
    error: sessionQuery.error || snapshotQuery.error,
    refresh: async () => Promise.all([sessionQuery.refetch(), snapshotQuery.refetch()])
  }
}

function CrystalQuotaOrb({ remaining, label, ariaLabel, subLabel }) {
  const { clamped, surfaceY, fillDepth, waveAmplitude, hasLiquid } = liquidGeometry(remaining)
  const backSurface = `M -82 ${surfaceY + waveAmplitude * 0.12} C -70 ${surfaceY - waveAmplitude} -57 ${surfaceY - waveAmplitude * 0.72} -46 ${surfaceY + waveAmplitude * 0.12} C -34 ${surfaceY + waveAmplitude * 0.72} -21 ${surfaceY + waveAmplitude * 0.56} -10 ${surfaceY - waveAmplitude * 0.12} C 2 ${surfaceY - waveAmplitude} 15 ${surfaceY - waveAmplitude * 0.72} 26 ${surfaceY + waveAmplitude * 0.12} C 38 ${surfaceY + waveAmplitude * 0.72} 51 ${surfaceY + waveAmplitude * 0.56} 62 ${surfaceY - waveAmplitude * 0.12} C 74 ${surfaceY - waveAmplitude} 87 ${surfaceY - waveAmplitude * 0.72} 98 ${surfaceY + waveAmplitude * 0.12} C 110 ${surfaceY + waveAmplitude * 0.72} 123 ${surfaceY + waveAmplitude * 0.56} 134 ${surfaceY - waveAmplitude * 0.12} C 146 ${surfaceY - waveAmplitude} 159 ${surfaceY - waveAmplitude * 0.72} 170 ${surfaceY + waveAmplitude * 0.12}`
  const backWave = `${backSurface} V 96 H -82 Z`
  const frontSurface = `M -82 ${surfaceY + waveAmplitude * 0.24} C -67 ${surfaceY + waveAmplitude * 0.86} -55 ${surfaceY + waveAmplitude * 0.58} -43 ${surfaceY - waveAmplitude * 0.24} C -31 ${surfaceY - waveAmplitude} -17 ${surfaceY - waveAmplitude * 0.5} -6 ${surfaceY + waveAmplitude * 0.36} C 7 ${surfaceY + waveAmplitude} 19 ${surfaceY + waveAmplitude * 0.62} 31 ${surfaceY - waveAmplitude * 0.36} C 43 ${surfaceY - waveAmplitude} 57 ${surfaceY - waveAmplitude * 0.5} 66 ${surfaceY + waveAmplitude * 0.36} C 79 ${surfaceY + waveAmplitude} 91 ${surfaceY + waveAmplitude * 0.62} 103 ${surfaceY - waveAmplitude * 0.36} C 115 ${surfaceY - waveAmplitude} 129 ${surfaceY - waveAmplitude * 0.5} 138 ${surfaceY + waveAmplitude * 0.36} C 151 ${surfaceY + waveAmplitude} 163 ${surfaceY + waveAmplitude * 0.62} 175 ${surfaceY - waveAmplitude * 0.36}`
  const frontWave = `${frontSurface} V 96 H -82 Z`
  const surfaceLine = backSurface
  const glintWave = `M -82 ${surfaceY - waveAmplitude * 0.06} C -70 ${surfaceY - waveAmplitude * 0.72} -57 ${surfaceY - waveAmplitude * 0.58} -46 ${surfaceY} C -34 ${surfaceY + waveAmplitude * 0.58} -21 ${surfaceY + waveAmplitude * 0.46} -10 ${surfaceY - waveAmplitude * 0.06} C 2 ${surfaceY - waveAmplitude * 0.82} 15 ${surfaceY - waveAmplitude * 0.58} 26 ${surfaceY} C 38 ${surfaceY + waveAmplitude * 0.58} 51 ${surfaceY + waveAmplitude * 0.46} 62 ${surfaceY - waveAmplitude * 0.06} C 74 ${surfaceY - waveAmplitude * 0.82} 87 ${surfaceY - waveAmplitude * 0.58} 98 ${surfaceY}`
  const emeraldSwirlBack = `M 15 ${surfaceY + waveAmplitude * 0.7} C 27 ${surfaceY - waveAmplitude * 0.28} 35 ${surfaceY + waveAmplitude * 0.98} 48 ${surfaceY + waveAmplitude * 0.7} C 61 ${surfaceY - waveAmplitude * 0.28} 70 ${surfaceY + waveAmplitude * 0.98} 82 ${surfaceY + waveAmplitude * 0.7}`
  const emeraldSwirlFront = `M 12 ${surfaceY + waveAmplitude * 0.2} C 25 ${surfaceY + waveAmplitude * 0.82} 36 ${surfaceY - waveAmplitude * 0.62} 49 ${surfaceY + waveAmplitude * 0.2} C 62 ${surfaceY + waveAmplitude * 0.82} 71 ${surfaceY - waveAmplitude * 0.52} 84 ${surfaceY + waveAmplitude * 0.28}`

  return jsxs('div', {
    className: 'relative flex items-center justify-center',
    role: 'progressbar',
    'aria-label': ariaLabel,
    'aria-valuemin': 0,
    'aria-valuemax': 100,
    'aria-valuenow': clamped === null ? undefined : clamped,
    style: { width: '106px', height: '106px' },
    children: [
      jsx('style', {
        children: `
          [data-floating-pane="quota-orb:orb"] {
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
            overflow: visible !important;
          }
          [data-floating-pane="quota-orb:orb"] > header { display: none !important; }
          [data-floating-pane="quota-orb:orb"] > div { overflow: visible !important; }
          @keyframes quota-orb-wave-a { to { transform: translateX(-72px); } }
          @keyframes quota-orb-wave-b { to { transform: translateX(72px); } }
          @keyframes quota-orb-bubble-rise { 0% { transform: translateY(11px) scale(0.72); opacity: 0; } 18% { opacity: 0.5; } 78% { opacity: 0.28; } 100% { transform: translateY(-25px) scale(1.08); opacity: 0; } }
          @keyframes quota-orb-mote-drift { 0%, 100% { transform: translate(0, 0); opacity: 0.22; } 45% { transform: translate(1px, -2px); opacity: 0.56; } 78% { transform: translate(-1px, -3px); opacity: 0.3; } }
          @keyframes quota-orb-swirl-back { 0%, 100% { transform: translateX(-1px) rotate(-0.8deg); } 50% { transform: translateX(1px) rotate(0.8deg); } }
          @keyframes quota-orb-swirl-front { 0%, 100% { transform: translateX(1px) rotate(0.7deg); } 50% { transform: translateX(-1px) rotate(-0.7deg); } }
          .quota-orb-wave-back, .quota-orb-wave-front, .quota-orb-surface-line, .quota-orb-wave-glint { transform-box: fill-box; transform-origin: center; }
          .quota-orb-wave-back { animation: quota-orb-wave-a 7.4s linear infinite; }
          .quota-orb-wave-front, .quota-orb-surface-line, .quota-orb-wave-glint { animation: quota-orb-wave-b 4.9s linear infinite; }
          .quota-orb-emerald-swirl-back, .quota-orb-emerald-swirl-front, .quota-orb-magic-mote { transform-box: fill-box; transform-origin: center; }
          .quota-orb-emerald-swirl-back { animation: quota-orb-swirl-back 8.4s ease-in-out infinite; }
          .quota-orb-emerald-swirl-front { animation: quota-orb-swirl-front 6.6s ease-in-out infinite; }
          .quota-orb-magic-mote { animation: quota-orb-mote-drift 5.8s ease-in-out infinite; }
          .quota-orb-bubble { animation: quota-orb-bubble-rise 4.8s ease-in infinite; transform-box: fill-box; transform-origin: center; }
          .quota-orb-bubble:nth-of-type(2) { animation-delay: -1.7s; animation-duration: 5.6s; }
          .quota-orb-bubble:nth-of-type(3) { animation-delay: -3.2s; animation-duration: 4.3s; }
          .quota-orb-shell { transition: transform 220ms ease, filter 220ms ease; transform-style: preserve-3d; }
          .quota-orb-shell:hover { transform: perspective(420px) rotateX(-7deg) rotateY(9deg) scale(1.055); }
          .quota-orb-shell:focus-visible { outline: 2px solid var(--ui-green, var(--ui-accent)); outline-offset: 3px; }
          .quota-orb-language-option:focus-visible { outline: 2px solid var(--ui-green, var(--ui-accent)); outline-offset: 2px; }
          .quota-orb-panel-sheen { transform: rotate(18deg); opacity: 0.28; }
          .quota-orb-detail-panel { scrollbar-color: var(--ui-stroke-primary) transparent; scrollbar-width: thin; }
          .quota-orb-section { position: relative; padding: 11px 1px 2px; border-top: 1px solid color-mix(in srgb, var(--ui-stroke-secondary) 72%, transparent); }
          @media (prefers-reduced-motion: reduce) {
            .quota-orb-wave-back, .quota-orb-wave-front, .quota-orb-surface-line, .quota-orb-wave-glint, .quota-orb-bubble { animation: none !important; }
            .quota-orb-emerald-swirl-back { animation: none !important; }
            .quota-orb-emerald-swirl-front { animation: none !important; }
            .quota-orb-magic-mote { animation: none !important; }
            .quota-orb-shell { transition: none !important; }
            .quota-orb-shell:hover { transform: none !important; }
          }
        `
      }),
      jsxs('svg', {
        className: 'quota-orb-crystal absolute inset-0 size-full overflow-visible',
        viewBox: '0 0 92 92',
        'aria-hidden': true,
        children: [
          jsxs('defs', {
            children: [
              jsx('clipPath', { id: 'quota-orb-liquid-clip', children: jsx('circle', { cx: 46, cy: 46, r: 38 }) }),
              jsx('clipPath', { id: 'quota-orb-fill-clip', children: jsx('rect', { x: 8, y: surfaceY, width: 76, height: fillDepth }) }),
              jsxs('radialGradient', {
                id: 'quota-orb-cavity',
                cx: '38%',
                cy: '30%',
                r: '78%',
                children: [
                  jsx('stop', { offset: '0%', stopColor: 'var(--ui-bg-editor)', stopOpacity: 0.34 }),
                  jsx('stop', { offset: '58%', stopColor: 'var(--ui-bg-editor)', stopOpacity: 0.88 }),
                  jsx('stop', { offset: '100%', stopColor: 'var(--ui-text-quaternary)', stopOpacity: 0.52 })
                ]
              }),
              jsxs('radialGradient', {
                id: 'quota-orb-glass',
                cx: '27%',
                cy: '19%',
                r: '82%',
                children: [
                  jsx('stop', { offset: '0%', stopColor: 'var(--ui-text-primary)', stopOpacity: 0.3 }),
                  jsx('stop', { offset: '28%', stopColor: 'var(--ui-text-secondary)', stopOpacity: 0.09 }),
                  jsx('stop', { offset: '67%', stopColor: 'var(--ui-bg-editor)', stopOpacity: 0.12 }),
                  jsx('stop', { offset: '88%', stopColor: 'var(--ui-green, var(--ui-accent))', stopOpacity: clamped === null ? 0.08 : 0.34 }),
                  jsx('stop', { offset: '100%', stopColor: 'var(--ui-text-primary)', stopOpacity: 0.6 })
                ]
              }),
              jsxs('radialGradient', {
                id: 'quota-orb-fresnel',
                cx: '44%',
                cy: '40%',
                r: '62%',
                children: [
                  jsx('stop', { offset: '0%', stopColor: 'var(--ui-text-primary)', stopOpacity: 0 }),
                  jsx('stop', { offset: '68%', stopColor: 'var(--ui-text-primary)', stopOpacity: 0.02 }),
                  jsx('stop', { offset: '88%', stopColor: 'var(--ui-green, var(--ui-accent))', stopOpacity: clamped === null ? 0.05 : 0.24 }),
                  jsx('stop', { offset: '100%', stopColor: 'var(--ui-text-primary)', stopOpacity: 0.72 })
                ]
              }),
              jsxs('linearGradient', {
                id: 'quota-orb-rim',
                x1: '15%',
                y1: '5%',
                x2: '88%',
                y2: '94%',
                children: [
                  jsx('stop', { offset: '0%', stopColor: 'var(--ui-text-primary)', stopOpacity: 0.92 }),
                  jsx('stop', { offset: '35%', stopColor: 'var(--ui-text-secondary)', stopOpacity: 0.22 }),
                  jsx('stop', { offset: '72%', stopColor: 'var(--ui-green, var(--ui-accent))', stopOpacity: clamped === null ? 0.14 : 0.86 }),
                  jsx('stop', { offset: '100%', stopColor: 'var(--ui-text-primary)', stopOpacity: 0.72 })
                ]
              }),
              jsxs('linearGradient', {
                id: 'quota-orb-crystal-band',
                x1: '8%',
                y1: '12%',
                x2: '92%',
                y2: '88%',
                children: [
                  jsx('stop', { offset: '0%', stopColor: 'var(--ui-bg-editor)', stopOpacity: 0.9 }),
                  jsx('stop', { offset: '36%', stopColor: 'var(--ui-green, var(--ui-accent))', stopOpacity: 0.52 }),
                  jsx('stop', { offset: '68%', stopColor: 'var(--ui-text-primary)', stopOpacity: 0.26 }),
                  jsx('stop', { offset: '100%', stopColor: 'var(--ui-bg-editor)', stopOpacity: 0.76 })
                ]
              }),
              jsxs('linearGradient', {
                id: 'quota-orb-liquid',
                x1: '0%',
                y1: '0%',
                x2: '0%',
                y2: '100%',
                children: [
                  jsx('stop', { offset: '0%', stopColor: 'var(--ui-green, var(--ui-accent))', stopOpacity: 0.98 }),
                  jsx('stop', { offset: '42%', stopColor: 'var(--ui-green, var(--ui-accent))', stopOpacity: 0.82 }),
                  jsx('stop', { offset: '100%', stopColor: 'var(--ui-green, var(--ui-accent))', stopOpacity: 0.42 })
                ]
              }),
              jsxs('radialGradient', {
                id: 'quota-orb-liquid-volume',
                cx: '28%',
                cy: '16%',
                r: '88%',
                children: [
                  jsx('stop', { offset: '0%', stopColor: 'var(--ui-bg-editor)', stopOpacity: 0.42 }),
                  jsx('stop', { offset: '38%', stopColor: 'var(--ui-green, var(--ui-accent))', stopOpacity: 0.12 }),
                  jsx('stop', { offset: '100%', stopColor: 'var(--ui-text-quaternary)', stopOpacity: 0.2 })
                ]
              }),
              jsxs('linearGradient', {
                id: 'quota-orb-water-film',
                x1: '0%',
                y1: '0%',
                x2: '100%',
                y2: '0%',
                children: [
                  jsx('stop', { offset: '0%', stopColor: 'var(--ui-text-primary)', stopOpacity: 0.08 }),
                  jsx('stop', { offset: '38%', stopColor: 'var(--ui-text-primary)', stopOpacity: 0.82 }),
                  jsx('stop', { offset: '62%', stopColor: 'var(--ui-green, var(--ui-accent))', stopOpacity: 0.42 }),
                  jsx('stop', { offset: '100%', stopColor: 'var(--ui-text-primary)', stopOpacity: 0.04 })
                ]
              }),
              jsxs('radialGradient', {
                id: 'quota-orb-caustic',
                cx: '50%',
                cy: '100%',
                r: '70%',
                children: [
                  jsx('stop', { offset: '0%', stopColor: 'var(--ui-green, var(--ui-accent))', stopOpacity: 0.68 }),
                  jsx('stop', { offset: '100%', stopColor: 'var(--ui-green, var(--ui-accent))', stopOpacity: 0 })
                ]
              }),
              jsxs('filter', {
                id: 'quota-orb-soft-glow',
                x: '-30%',
                y: '-30%',
                width: '160%',
                height: '160%',
                children: [
                  jsx('feGaussianBlur', { stdDeviation: 2.4, result: 'blurred' }),
                  jsxs('feMerge', {
                    children: [jsx('feMergeNode', { in: 'blurred' }), jsx('feMergeNode', { in: 'SourceGraphic' })]
                  })
                ]
              }),
              jsxs('filter', {
                id: 'quota-orb-glass-specular',
                x: '-20%',
                y: '-20%',
                width: '140%',
                height: '140%',
                children: [
                  jsx('feGaussianBlur', { in: 'SourceAlpha', stdDeviation: 1.1, result: 'softAlpha' }),
                  jsx('feSpecularLighting', {
                    in: 'softAlpha',
                    surfaceScale: 4.5,
                    specularConstant: 0.72,
                    specularExponent: 24,
                    lightingColor: 'var(--ui-text-primary)',
                    result: 'specular',
                    children: jsx('fePointLight', { x: 22, y: 14, z: 54 })
                  }),
                  jsx('feComposite', { in: 'specular', in2: 'SourceAlpha', operator: 'in', result: 'specularClip' }),
                  jsxs('feMerge', {
                    children: [jsx('feMergeNode', { in: 'SourceGraphic' }), jsx('feMergeNode', { in: 'specularClip' })]
                  })
                ]
              })
            ]
          }),
          jsx('ellipse', {
            className: 'quota-orb-contact-shadow',
            cx: 46,
            cy: 89,
            rx: 31,
            ry: 4.5,
            fill: 'var(--ui-text-quaternary)',
            opacity: 0.34,
            filter: 'blur(2px)'
          }),
          jsx('circle', {
            className: 'quota-orb-glass-outer-shell',
            cx: 46,
            cy: 46,
            r: 41,
            fill: 'url(#quota-orb-cavity)',
            fillOpacity: 0.76,
            stroke: 'url(#quota-orb-rim)',
            strokeWidth: 1.55
          }),
          clamped === null
            ? jsx('circle', {
                cx: 46,
                cy: 46,
                r: 35,
                fill: 'none',
                stroke: 'var(--ui-text-quaternary)',
                strokeWidth: 1,
                strokeDasharray: '2.5 4.5',
                opacity: 0.58
              })
            : hasLiquid
              ? jsxs('g', {
                  className: 'quota-orb-liquid-stack',
                  clipPath: 'url(#quota-orb-liquid-clip)',
                  children: [
                    jsxs('g', {
                      className: 'quota-orb-liquid-fill',
                      clipPath: 'url(#quota-orb-fill-clip)',
                      children: [
                        jsx('rect', { className: 'quota-orb-liquid-body', x: 8, y: surfaceY, width: 76, height: fillDepth, fill: 'url(#quota-orb-liquid)' }),
                        jsx('ellipse', { className: 'quota-orb-liquid-volume', cx: 46, cy: Math.min(78, surfaceY + fillDepth * 0.5), rx: 35, ry: Math.min(24, fillDepth * 0.48), fill: 'url(#quota-orb-liquid-volume)', opacity: 0.72 }),
                        jsx('ellipse', { className: 'quota-orb-water-glow', cx: 46, cy: Math.min(80, surfaceY + fillDepth * 0.58), rx: 29, ry: Math.min(16, fillDepth * 0.38), fill: 'var(--ui-green, var(--ui-accent))', opacity: 0.2 }),
                        jsx('path', { className: 'quota-orb-emerald-swirl-back', d: emeraldSwirlBack, fill: 'none', stroke: 'url(#quota-orb-water-film)', strokeWidth: 1.15, strokeLinecap: 'round', opacity: 0.44 }),
                        jsx('path', { className: 'quota-orb-emerald-swirl-front', d: emeraldSwirlFront, fill: 'none', stroke: 'url(#quota-orb-water-film)', strokeWidth: 1.55, strokeLinecap: 'round', opacity: 0.82 }),
                        jsx('ellipse', { className: 'quota-orb-inner-caustic', cx: 46, cy: 80, rx: 31, ry: 18, fill: 'url(#quota-orb-caustic)', opacity: 0.72 }),
                        jsx('circle', { className: 'quota-orb-bubble quota-orb-bubble-highlight', cx: 31, cy: Math.min(78, surfaceY + fillDepth * 0.45), r: 1.25, fill: 'none', stroke: 'url(#quota-orb-water-film)', strokeWidth: 0.7, opacity: 0.7 }),
                        jsx('circle', { className: 'quota-orb-bubble quota-orb-bubble-highlight', cx: 56, cy: Math.min(79, surfaceY + fillDepth * 0.68), r: 0.85, fill: 'var(--ui-bg-editor)', opacity: 0.5 }),
                        jsx('circle', { className: 'quota-orb-bubble quota-orb-bubble-highlight', cx: 67, cy: Math.min(77, surfaceY + fillDepth * 0.28), r: 1.05, fill: 'none', stroke: 'url(#quota-orb-water-film)', strokeWidth: 0.65, opacity: 0.62 }),
                        jsx('circle', { className: 'quota-orb-magic-mote', cx: 26, cy: Math.min(75, surfaceY + fillDepth * 0.25), r: 0.55, fill: 'var(--ui-bg-editor)', opacity: 0.7, style: { animationDelay: '-1.4s' } }),
                        jsx('circle', { className: 'quota-orb-magic-mote', cx: 49, cy: Math.min(77, surfaceY + fillDepth * 0.55), r: 0.38, fill: 'var(--ui-text-primary)', opacity: 0.52, style: { animationDelay: '-3.1s' } }),
                        jsx('circle', { className: 'quota-orb-magic-mote', cx: 71, cy: Math.min(73, surfaceY + fillDepth * 0.38), r: 0.7, fill: 'var(--ui-bg-editor)', opacity: 0.62, style: { animationDelay: '-4.2s' } })
                      ]
                    }),
                    jsx('ellipse', { className: 'quota-orb-liquid-lens', cx: 46, cy: surfaceY + 1, rx: 33, ry: 4.6, fill: 'url(#quota-orb-water-film)', opacity: 0.3 }),
                    jsx('path', { className: 'quota-orb-wave-back', d: backWave, fill: 'var(--ui-green, var(--ui-accent))', opacity: 0.52 }),
                    jsx('path', { className: 'quota-orb-wave-front', d: frontWave, fill: 'url(#quota-orb-liquid)', opacity: 0.92 }),
                    jsx('ellipse', { className: 'quota-orb-meniscus', cx: 46, cy: surfaceY + 1, rx: 34, ry: 3.4, fill: 'none', stroke: 'var(--ui-green, var(--ui-accent))', strokeWidth: 0.7, opacity: 0.5 }),
                    jsx('path', { className: 'quota-orb-surface-line', d: surfaceLine, fill: 'none', stroke: 'var(--ui-text-primary)', strokeWidth: 0.8, opacity: 0.64 }),
                    jsx('path', { className: 'quota-orb-wave-glint', d: glintWave, fill: 'none', stroke: 'url(#quota-orb-water-film)', strokeWidth: 1.35, strokeLinecap: 'round', opacity: 0.76 })
                  ]
                })
              : null,
          jsx('circle', {
            className: 'quota-orb-glass-inner-shell',
            cx: 46,
            cy: 46,
            r: 38,
            fill: 'url(#quota-orb-glass)',
            stroke: 'url(#quota-orb-rim)',
            strokeWidth: 0.75,
            opacity: 0.46,
            filter: 'url(#quota-orb-glass-specular)'
          }),
          jsx('circle', {
            className: 'quota-orb-glass-bright-rim',
            cx: 46,
            cy: 46,
            r: 39.8,
            fill: 'none',
            stroke: 'url(#quota-orb-crystal-band)',
            strokeWidth: 1.05,
            opacity: 0.72
          }),
          jsx('path', {
            className: 'quota-orb-refraction-band',
            d: 'M 73 25 C 82 37 82 54 74 66 C 67 76 57 81 45 83',
            fill: 'none',
            stroke: 'url(#quota-orb-crystal-band)',
            strokeWidth: 2.85,
            strokeLinecap: 'round',
            opacity: 0.62
          }),
          jsx('path', {
            className: 'quota-orb-inner-refraction-band',
            d: 'M 70 27 C 77 39 77 53 70 63 C 64 72 56 77 47 79',
            fill: 'none',
            stroke: 'var(--ui-bg-editor)',
            strokeWidth: 0.85,
            strokeLinecap: 'round',
            opacity: 0.7
          }),
          jsx('ellipse', {
            className: 'quota-orb-refraction-lens',
            cx: 31,
            cy: 31,
            rx: 13,
            ry: 22,
            fill: 'none',
            stroke: 'url(#quota-orb-crystal-band)',
            strokeWidth: 1.05,
            opacity: 0.34,
            transform: 'rotate(41 31 31)'
          }),
          jsx('path', {
            className: 'quota-orb-refraction-caustic',
            d: 'M 18 59 C 28 73 45 81 63 76 C 69 74 74 70 78 65',
            fill: 'none',
            stroke: 'url(#quota-orb-crystal-band)',
            strokeWidth: 1.45,
            strokeLinecap: 'round',
            opacity: 0.42
          }),
          jsx('circle', {
            cx: 46,
            cy: 46,
            r: 39,
            fill: 'url(#quota-orb-fresnel)',
            opacity: 0.76
          }),
          jsx('path', {
            className: 'quota-orb-glass-highlight-core',
            d: 'M 20 34 C 23 20 34 12 50 13',
            fill: 'none',
            stroke: 'var(--ui-bg-editor)',
            strokeWidth: 1.35,
            strokeLinecap: 'round',
            opacity: 0.76
          }),
          jsx('path', {
            className: 'quota-orb-glass-highlight-shadow',
            d: 'M 21 34 C 24 20, 35 13, 49 13',
            fill: 'none',
            stroke: 'var(--ui-text-secondary)',
            strokeWidth: 1.9,
            strokeLinecap: 'round',
            opacity: 0.28
          }),
          jsx('ellipse', {
            cx: 30,
            cy: 27,
            rx: 5.5,
            ry: 9,
            fill: 'var(--ui-text-secondary)',
            opacity: 0.2,
            transform: 'rotate(42 30 27)'
          }),
          jsx('path', {
            d: 'M 66 66 C 61 74, 53 79, 44 80',
            fill: 'none',
            stroke: 'var(--ui-text-quaternary)',
            strokeWidth: 1.4,
            strokeLinecap: 'round',
            opacity: 0.34
          }),
          jsx('path', {
            d: 'M 58 19 C 68 24, 75 34, 77 45',
            fill: 'none',
            stroke: 'var(--ui-green, var(--ui-accent))',
            strokeWidth: 1.2,
            strokeLinecap: 'round',
            opacity: clamped === null ? 0.1 : 0.5
          }),
          jsx('path', {
            d: 'M 22 59 C 34 66, 54 68, 70 57',
            fill: 'none',
            stroke: 'var(--ui-text-primary)',
            strokeWidth: 1.1,
            strokeLinecap: 'round',
            opacity: 0.13
          })
        ]
      }),
      jsxs('span', {
        className: 'pointer-events-none relative z-10 flex flex-col items-center text-center',
        style: { textShadow: '0 1px 8px var(--ui-bg-editor)' },
        children: [
          jsx('strong', {
            className: 'font-medium tabular-nums text-foreground',
            style: { fontSize: '17px', letterSpacing: '-0.04em', lineHeight: 1 },
            children: label
          }),
          clamped === null ? null : jsx('span', {
            className: 'mt-1 uppercase text-(--ui-text-secondary)',
            style: { fontSize: '7px', letterSpacing: '0.18em', lineHeight: 1 },
            children: subLabel
          })
        ]
      })
    ]
  })
}

function TechnicalLabel({ children }) {
  return jsx('span', {
    className: 'uppercase text-(--ui-text-quaternary)',
    style: {
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
      fontSize: '9px',
      letterSpacing: '0.14em'
    },
    children
  })
}

function LanguageSwitcher({ t, languageMode, setLanguageMode }) {
  const options = [
    { id: 'auto', label: t('languageAuto') },
    { id: 'zh', label: t('languageZh') },
    { id: 'en', label: t('languageEn') }
  ]
  return jsxs('div', {
    className: 'quota-orb-language-switch flex items-center justify-between gap-3',
    children: [
      jsx(TechnicalLabel, { children: t('language') }),
      jsx('div', {
        className: 'inline-flex rounded-lg border border-(--ui-stroke-secondary) p-0.5',
        role: 'group',
        'aria-label': t('language'),
        children: options.map(option => jsx('button', {
          type: 'button',
          'aria-pressed': languageMode === option.id,
          onClick: () => setLanguageMode(option.id),
          className: cn(
            'quota-orb-language-option rounded-md px-2 py-1 transition-colors',
            languageMode === option.id
              ? 'bg-(--ui-green) text-(--ui-bg-editor)'
              : 'text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground'
          ),
          style: { fontSize: '10px', lineHeight: 1.2 },
          children: option.label
        }, option.id))
      })
    ]
  })
}

function Metric({ label, value, featured = false }) {
  return jsxs('div', {
    className: cn(
      'relative overflow-hidden rounded-lg border border-(--ui-stroke-secondary) p-2.5',
      featured ? 'col-span-2' : ''
    ),
    style: {
      background: featured
        ? 'linear-gradient(125deg, color-mix(in srgb, var(--ui-green) 12%, transparent), var(--ui-bg-editor))'
        : 'color-mix(in srgb, var(--ui-bg-editor) 88%, transparent)'
    },
    children: [
      jsx(TechnicalLabel, { children: label }),
      jsx('div', {
        className: 'mt-1 font-medium tabular-nums text-foreground',
        style: { fontSize: featured ? '24px' : '15px', letterSpacing: '-0.035em', lineHeight: 1.1 },
        children: value
      })
    ]
  })
}

function WindowRow({ window, t }) {
  const remaining = clampPercent(window.remaining_percent)
  return jsxs('div', {
    className: 'flex flex-col gap-1.5 border-b border-(--ui-stroke-secondary) py-2.5 last:border-b-0',
    children: [
      jsxs('div', {
        className: 'flex items-center justify-between gap-3',
        children: [
          jsxs('span', {
            className: 'inline-flex items-center gap-1.5 text-xs text-(--ui-text-secondary)',
            children: [jsx(StatusDot, { tone: toneFor(remaining) }), window.label || t('quota')]
          }),
          jsx('strong', {
            className: 'font-medium tabular-nums',
            style: { fontSize: '13px', letterSpacing: '-0.03em' },
            children: remaining === null ? t('unknown') : `${Math.round(remaining)}%`
          })
        ]
      }),
      jsx('div', {
        className: cn(
          'h-1.5 overflow-hidden rounded-full bg-(--ui-stroke-secondary)',
          remaining === null ? 'quota-orb-quota-unavailable' : ''
        ),
        role: 'progressbar',
        'aria-label': remaining === null ? `${window.label || t('quota')}: ${t('unknown')}` : `${window.label || t('quota')} ${remaining}%`,
        'aria-valuemin': 0,
        'aria-valuemax': 100,
        'aria-valuenow': remaining === null ? undefined : remaining,
        children: remaining === null
          ? jsx('div', {
              className: 'h-full w-full',
              style: { background: 'repeating-linear-gradient(135deg, var(--ui-stroke-secondary) 0 2px, var(--ui-bg-editor) 2px 4px)' },
              'aria-hidden': true
            })
          : jsx('div', {
              className: 'h-full rounded-full transition-[width]',
              style: {
                width: `${remaining}%`,
                background: 'linear-gradient(90deg, color-mix(in srgb, var(--ui-green) 55%, transparent), var(--ui-green))'
              }
            })
      }),
      jsx('span', {
        className: 'text-(--ui-text-quaternary)',
        style: { fontSize: '10px' },
        children: t('resets', formatReset(window.reset_at))
      })
    ]
  })
}

function ProviderModels({ today, t }) {
  const groups = providerGroups(today)
  if (!groups.length) {
    return jsx('div', { className: 'py-3 text-xs text-(--ui-text-tertiary)', children: t('noModelUsage') })
  }
  return jsx('div', {
    className: 'flex flex-col gap-2',
    children: groups.map(group => jsxs('div', {
      className: 'overflow-hidden rounded-lg border border-(--ui-stroke-secondary)',
      style: { background: 'color-mix(in srgb, var(--ui-bg-editor) 84%, transparent)' },
      children: [
        jsxs('div', {
          className: 'flex items-center justify-between border-b border-(--ui-stroke-secondary) px-2.5 py-2',
          children: [
            jsxs('div', {
              className: 'min-w-0',
              children: [
                jsx('div', { className: 'truncate text-xs font-medium text-foreground', children: group.provider || t('unknown') }),
                jsx(TechnicalLabel, { children: t('localTokenSource') })
              ]
            }),
            jsx('span', {
              className: 'shrink-0 font-medium tabular-nums text-(--ui-green)',
              style: { fontSize: '13px' },
              children: compactNumber(group.total_tokens || 0)
            })
          ]
        }),
        jsx('div', {
          children: (group.models || []).map((model, index) => jsxs('div', {
            className: 'flex items-center justify-between gap-3 border-b border-(--ui-stroke-secondary) px-2.5 py-2 last:border-b-0',
            children: [
              jsxs('div', {
                className: 'min-w-0',
                children: [
                  jsx('div', { className: 'truncate text-xs text-(--ui-text-secondary)', children: model.model || t('unknownModel') }),
                  jsx('div', {
                    className: 'mt-0.5 text-(--ui-text-quaternary)',
                    style: { fontSize: '9px' },
                    children: t('modelTokenParts', compactNumber(model.input_tokens || 0), compactNumber(model.output_tokens || 0), compactNumber(model.cache_read_tokens || 0))
                  })
                ]
              }),
              jsx('span', {
                className: 'shrink-0 tabular-nums text-(--ui-text-secondary)',
                style: { fontSize: '11px' },
                children: compactNumber(model.total_tokens || 0)
              })
            ]
          }, `${group.provider}-${model.model}-${index}`))
        })
      ]
    }, group.provider))
  })
}

function SectionHeader({ title, meta }) {
  return jsxs('div', {
    className: 'mb-1.5 flex items-center justify-between gap-3',
    children: [jsx(TechnicalLabel, { children: title }), meta ? jsx('span', { className: 'truncate text-(--ui-text-quaternary)', style: { fontSize: '10px' }, children: meta }) : null]
  })
}

function DetailPanel({ data }) {
  const { profile, model, session, snapshot, isLoading, error, refresh } = data
  const { t, languageMode, setLanguageMode } = useQuotaI18n(profile)
  const today = snapshot.today || emptySnapshot.today
  const quota = snapshot.quota || emptySnapshot.quota
  const remaining = clampPercent(lowestRemaining(snapshot))
  const providerMeta = [quota.provider, quota.plan].filter(Boolean).join(' · ') || t('unknown')

  return jsxs('div', {
    className: 'quota-orb-detail-panel flex max-w-[calc(100vw-2rem)] flex-col gap-3 p-3 text-xs',
    style: {
      width: '372px',
      maxHeight: 'min(680px, calc(100vh - 3rem))',
      overflowY: 'auto',
      background: 'linear-gradient(155deg, color-mix(in srgb, var(--ui-green) 9%, var(--ui-bg-editor)) 0%, color-mix(in srgb, var(--ui-text-primary) 2%, var(--ui-bg-editor)) 44%, var(--ui-bg-editor) 100%)',
      fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
      fontVariantNumeric: 'tabular-nums',
      boxShadow: 'inset 0 1px 0 color-mix(in srgb, var(--ui-text-primary) 7%, transparent)'
    },
    children: [
      jsxs('div', {
        className: 'quota-orb-panel-hero relative overflow-hidden rounded-xl border border-(--ui-stroke-secondary) p-3',
        style: {
          background: 'radial-gradient(circle at 12% 8%, color-mix(in srgb, var(--ui-text-primary) 12%, transparent), transparent 28%), linear-gradient(125deg, color-mix(in srgb, var(--ui-green) 18%, transparent), color-mix(in srgb, var(--ui-bg-editor) 92%, transparent))',
          boxShadow: 'inset 0 1px 0 color-mix(in srgb, var(--ui-text-primary) 10%, transparent), 0 12px 36px color-mix(in srgb, var(--ui-green) 7%, transparent)'
        },
        children: [
          jsx('span', {
            className: 'quota-orb-panel-sheen pointer-events-none absolute inset-y-[-30%] left-[-18%] w-10',
            style: { background: 'linear-gradient(90deg, transparent, color-mix(in srgb, var(--ui-text-primary) 16%, transparent), transparent)', filter: 'blur(2px)' },
            'aria-hidden': true
          }),
          jsxs('div', {
            className: 'flex items-start justify-between gap-3',
            children: [
              jsxs('div', {
                className: 'min-w-0',
                children: [
                  jsx(TechnicalLabel, { children: t('liveQuota') }),
                  jsx('div', { className: 'mt-1 text-base font-medium tracking-tight text-foreground', children: t('title') }),
                  jsx('div', { className: 'mt-0.5 truncate text-(--ui-text-tertiary)', children: model || t('unknownModel') })
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
          jsxs('div', {
            className: 'mt-3 flex items-end justify-between gap-3',
            children: [
              jsxs('div', {
                children: [
                  jsx('div', {
                    className: 'font-medium tabular-nums text-(--ui-green)',
                    style: { fontSize: '34px', letterSpacing: '-0.035em', lineHeight: 1 },
                    children: remaining === null ? '—' : `${Math.round(remaining)}%`
                  }),
                  jsx('div', { className: 'mt-1 text-(--ui-text-tertiary)', style: { fontSize: '10px' }, children: t('minimumWindow') })
                ]
              }),
              jsxs('div', {
                className: 'flex max-w-[62%] flex-wrap justify-end gap-1.5',
                children: [
                  jsx('span', { className: 'rounded-full border border-(--ui-stroke-secondary) px-2 py-1 text-(--ui-text-secondary)', children: profile || t('defaultProfile') }),
                  jsx('span', { className: 'rounded-full border border-(--ui-stroke-secondary) px-2 py-1 text-(--ui-text-secondary)', children: quota.provider || today.provider || t('unknown') })
                ]
              })
            ]
          })
        ]
      }),
      jsx('div', {
        className: 'quota-orb-language-section quota-orb-section',
        children: jsx(LanguageSwitcher, { t, languageMode, setLanguageMode })
      }),
      error ? jsx('div', {
        className: 'rounded-lg border border-(--ui-stroke-secondary) p-2.5 text-(--ui-text-secondary)',
        children: t('restartHermes')
      }) : null,
      jsxs('div', {
        className: 'quota-orb-section',
        children: [
          jsx(SectionHeader, { title: t('usageOverview'), meta: snapshot.day || '' }),
          jsxs('div', {
            className: 'grid grid-cols-2 gap-2',
            children: [
              jsx(Metric, { label: t('todayTokens'), value: compactNumber(today.total_tokens || 0), featured: true }),
              jsx(Metric, { label: t('sessionTokens'), value: compactNumber(session.total || 0) }),
              jsx(Metric, { label: t('apiCalls'), value: compactNumber(today.api_calls || 0) }),
              jsx(Metric, { label: t('input'), value: compactNumber(today.input_tokens || 0) }),
              jsx(Metric, { label: t('output'), value: compactNumber(today.output_tokens || 0) }),
              jsx(Metric, { label: t('cacheRead'), value: compactNumber(today.cache_read_tokens || 0) }),
              jsx(Metric, { label: t('sessions'), value: compactNumber(today.sessions || 0) })
            ]
          })
        ]
      }),
      jsxs('div', {
        className: 'quota-orb-section',
        children: [
          jsx(SectionHeader, { title: t('providerQuota'), meta: providerMeta }),
          jsx('div', {
            className: 'rounded-lg border border-(--ui-stroke-secondary) px-2.5',
            style: { background: 'color-mix(in srgb, var(--ui-bg-editor) 84%, transparent)' },
            children: quota.windows?.length
              ? quota.windows.map((window, index) => jsx(WindowRow, { window, t }, `${window.label}-${index}`))
              : jsx('div', { className: 'py-3 text-(--ui-text-tertiary)', children: t('quotaUnavailable') })
          }),
          jsx('div', {
            className: 'mt-1.5 text-(--ui-text-quaternary)',
            style: { fontSize: '9px' },
            children: quota.source ? t('quotaSource', quota.source) : t('quotaSourceUnavailable')
          })
        ]
      }),
      jsxs('div', {
        className: 'quota-orb-section',
        children: [
          jsx(SectionHeader, { title: t('modelUsage'), meta: t('providerModelAssociation') }),
          jsx(ProviderModels, { today, t })
        ]
      }),
      jsx('div', {
        className: 'border-t border-(--ui-stroke-secondary) pt-2 text-(--ui-text-quaternary)',
        style: { fontSize: '9px', lineHeight: 1.55 },
        children: t('dataNote')
      })
    ]
  })
}

function QuotaOrb() {
  const data = useQuotaData()
  const { t } = useQuotaI18n(data.profile)
  const remaining = lowestRemaining(data.snapshot)
  const label = finite(remaining) ? `${Math.round(remaining)}%` : '—'

  return jsx(Popover, {
    children: jsxs('div', {
      className: 'flex h-full w-full items-center justify-center',
      children: [
        jsx(PopoverTrigger, {
          asChild: true,
          children: jsx('button', {
            type: 'button',
            'aria-label': t('openDetails'),
            onClick: () => haptic('tap'),
            className: cn('quota-orb-shell relative flex items-center justify-center rounded-full bg-transparent text-foreground'),
            style: { width: '106px', height: '106px', border: 'none', padding: 0 },
            children: jsx(CrystalQuotaOrb, {
              remaining,
              label,
              ariaLabel: finite(remaining) ? t('orbLevel', Math.round(remaining)) : t('quotaUnavailableShort'),
              subLabel: t('remainingShort')
            })
          })
        }),
        jsx(PopoverContent, {
          align: 'end',
          side: 'left',
          className: 'w-auto overflow-hidden border border-(--ui-stroke-secondary) p-0',
          style: {
            background: 'color-mix(in srgb, var(--ui-bg-editor) 91%, transparent)',
            backdropFilter: 'blur(28px) saturate(145%)',
            boxShadow: '0 28px 90px color-mix(in srgb, var(--ui-text-quaternary) 22%, transparent), inset 0 1px 0 color-mix(in srgb, var(--ui-text-primary) 8%, transparent)'
          },
          children: jsx(DetailPanel, { data })
        })
      ]
    })
  })
}

function StatusChip() {
  const data = useQuotaData()
  const { t } = useQuotaI18n(data.profile)
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
      children: [jsx(StatusDot, { tone: toneFor(remaining) }), jsx('span', { className: 'tabular-nums', children: text })]
    })
  })
}

function scheduleDailyReports(ctx) {
  const check = async () => {
    const hour = Math.max(0, Math.min(23, Number(ctx.storage.get('reportHour', 18)) || 18))
    const now = new Date()
    const day = now.toLocaleDateString('en-CA')
    const profile = host.state.profile.get()
    const lastReportKey = reportDayKey(profile)
    const lastReportDay = ctx.storage.get(lastReportKey, '')
    if (now.getHours() < hour || lastReportDay === day) return

    const t = (key, ...args) => quotaTranslate(profile, key, ...args)
    try {
      const snapshot = await ctx.rest('/snapshot', { timeoutMs: 20000 })
      const body = reportText(snapshot, t)
      host.notify({ kind: 'info', title: t('dailyReportTitle'), message: body })
      ctx.os.notify({ title: t('dailyReportTitle'), body })
      ctx.storage.set(lastReportKey, day)
    } catch (error) {
      host.notifyError(error, t('reportFailed'))
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
    localeBundles = {
      en: {
        title: 'Quota Orb',
        quota: 'Quota',
        remaining: 'left',
        remainingShort: 'REMAIN',
        language: 'Language',
        languageAuto: 'Auto',
        languageZh: '中文',
        languageEn: 'English',
        unknown: 'Unknown',
        unknownModel: 'No active model',
        openDetails: 'Open quota details',
        todayTokens: 'Today tokens',
        sessionTokens: 'Session tokens',
        input: 'Input',
        output: 'Output',
        cacheRead: 'Cache read',
        apiCalls: 'API calls',
        sessions: 'Sessions',
        providerQuota: 'Provider quota',
        usageOverview: 'Usage overview',
        liveQuota: 'Live account signal',
        minimumWindow: 'lowest remaining provider window',
        defaultProfile: 'default profile',
        modelUsage: 'Provider · model usage',
        providerModelAssociation: 'local today',
        localTokenSource: 'Hermes local totals',
        noModelUsage: 'No model usage has been recorded today.',
        modelTokenParts: (input, output, cache) => `in ${input} · out ${output} · cache ${cache}`,
        quotaUnavailable: 'Provider quota is unavailable; local token totals still work.',
        quotaUnavailableShort: 'Provider quota unavailable',
        quotaSource: source => `Provider-reported source: ${source}`,
        quotaSourceUnavailable: 'No official quota source is available for this provider.',
        orbLevel: value => `Lowest provider quota remaining: ${value}%`,
        resets: value => `Resets: ${value}`,
        refresh: 'Refresh',
        refreshing: 'Refreshing…',
        restartHermes: 'Restart Hermes Desktop once to activate the quota backend. Local session totals remain available.',
        partialData: 'Some data could not be refreshed. Showing the latest available values.',
        dataNote: 'Token totals are grouped locally by the active Hermes profile, provider, and model. The orb water level uses only provider-reported quota; unavailable providers never receive an estimated fill level.',
        chipTip: 'Today tokens and the lowest remaining provider quota',
        dailyReportTitle: 'Hermes daily usage report',
        dailyReportBody: (tokens, calls, quota) => `Today: ${tokens} tokens across ${calls} API calls. Remaining quota: ${quota}.`,
        reportFailed: 'Could not build the daily quota report.'
      },
      zh: {
        title: '配额水晶球',
        quota: '配额',
        remaining: '剩余',
        remainingShort: '剩余',
        language: '界面语言',
        languageAuto: '自动',
        languageZh: '中文',
        languageEn: 'English',
        unknown: '未知',
        unknownModel: '暂无活动模型',
        openDetails: '打开配额详情',
        todayTokens: '今日 Token',
        sessionTokens: '当前会话',
        input: '输入',
        output: '输出',
        cacheRead: '缓存读取',
        apiCalls: 'API 调用',
        sessions: '会话数',
        providerQuota: '提供商配额',
        usageOverview: '用量概览',
        liveQuota: '实时账户信号',
        minimumWindow: '提供商最低剩余窗口',
        defaultProfile: '默认客户配置',
        modelUsage: '提供商 · 模型用量',
        providerModelAssociation: '今日本地关联',
        localTokenSource: 'Hermes 本地汇总',
        noModelUsage: '今日尚无模型用量记录。',
        modelTokenParts: (input, output, cache) => `输入 ${input} · 输出 ${output} · 缓存 ${cache}`,
        quotaUnavailable: '提供商配额暂不可用；本地 Token 统计仍然有效。',
        quotaUnavailableShort: '提供商配额不可用',
        quotaSource: source => `提供商真实数据源：${source}`,
        quotaSourceUnavailable: '该提供商没有可用的官方配额数据源。',
        orbLevel: value => `提供商最低剩余配额：${value}%`,
        resets: value => `重置：${value}`,
        refresh: '刷新',
        refreshing: '刷新中…',
        restartHermes: '请重启一次 Hermes Desktop 以启用配额后端；当前会话 Token 仍可正常显示。',
        partialData: '部分数据刷新失败，正在显示最近一次可用值。',
        dataNote: 'Token 按当前 Hermes 客户配置、提供商和模型在本机分组；悬浮球水位只采用提供商真实配额，无官方配额时不显示估算液位。',
        chipTip: '今日 Token 与最低剩余配额',
        dailyReportTitle: 'Hermes 今日用量报告',
        dailyReportBody: (tokens, calls, quota) => `今日消耗 ${tokens} Token，共 ${calls} 次 API 调用。剩余配额：${quota}。`,
        reportFailed: '无法生成今日配额报告。'
      }
    }
    ctx.i18n.register(localeBundles)

    ctx.register({
      id: 'orb',
      area: 'panes',
      title: 'Quota Orb',
      data: { placement: 'floating', anchor: 'top-right', width: '116px', height: '116px' },
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
