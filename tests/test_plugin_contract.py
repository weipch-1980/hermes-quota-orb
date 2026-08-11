from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


PLUGIN = Path(__file__).parents[1] / "desktop-plugin" / "plugin.js"


class DesktopPluginContractTests(unittest.TestCase):
    def setUp(self):
        self.source = PLUGIN.read_text(encoding="utf-8")

    def test_registers_status_chip_and_floating_orb(self):
        self.assertIn("id: ID", self.source)
        self.assertIn("area: 'statusBar.right'", self.source)
        self.assertIn("placement: 'floating'", self.source)
        self.assertIn("anchor: 'top-right'", self.source)
        self.assertIn("width: '116px'", self.source)
        self.assertIn("height: '116px'", self.source)

    def test_uses_supported_sdk_doors_for_live_and_daily_usage(self):
        self.assertIn("host.request('session.usage'", self.source)
        self.assertIn("ctx.rest('/snapshot'", self.source)
        self.assertIn("refetchInterval", self.source)

    def test_frontend_matches_snapshot_contract(self):
        self.assertIn("snapshot?.today", self.source)
        self.assertIn("quota?.windows", self.source)
        self.assertNotIn("snapshot?.daily", self.source)
        self.assertNotIn("quota?.short", self.source)
        self.assertNotIn("quota?.weekly", self.source)
        self.assertIn("ctx.storage", self.source)
        self.assertNotIn("host.restartGateway()", self.source)
        self.assertIn("restartHermes", self.source)

    def test_emits_end_of_day_in_app_and_native_reports(self):
        self.assertIn("lastReportDay", self.source)
        self.assertIn("host.notify", self.source)
        self.assertIn("ctx.os.notify", self.source)
        self.assertIn("function quotaTranslate", self.source)
        self.assertIn("host.state.profile.get()", self.source)
        self.assertIn("quotaTranslate(profile, key, ...args)", self.source)
        self.assertNotIn("const t = ctx.i18n.t", self.source)

    def test_daily_report_preserves_unknown_quota_semantics(self):
        helpers = re.search(
            r"function finite\(value\) \{.*?\n\}\n\nfunction lowestRemaining",
            self.source,
            re.DOTALL,
        )
        report = re.search(
            r"function reportText\(snapshot, t\) \{.*?\n\}\n\nfunction providerGroups",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(helpers)
        self.assertIsNotNone(report)
        script = f"""
const compactNumber = value => String(value)
const emptySnapshot = {{ today: {{ total_tokens: 0, api_calls: 0 }} }}
{helpers.group(0).removesuffix(chr(10) + chr(10) + 'function lowestRemaining')}
{report.group(0).removesuffix(chr(10) + chr(10) + 'function providerGroups')}
const messages = {{
  unknown: 'Unknown',
  quotaUnavailable: 'Unavailable',
  dailyReportBody: (tokens, calls, quota) => `${{tokens}}|${{calls}}|${{quota}}`
}}
const t = (key, ...args) => typeof messages[key] === 'function' ? messages[key](...args) : messages[key]
const output = reportText({{
  today: {{ total_tokens: 123, api_calls: 2 }},
  quota: {{ windows: [{{ label: 'Session', remaining_percent: null }}] }}
}}, t)
if (output !== '123|2|Session: Unknown') throw new Error(output)
"""
        result = subprocess.run(["node", "-e", script], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_daily_report_marker_is_profile_scoped(self):
        helpers = re.search(
            r"function profileLanguageKey\(profile\) \{.*?\n\}\n\nfunction reportDayKey\(profile\) \{.*?\n\}",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(helpers)
        script = f"""
{helpers.group(0)}
if (reportDayKey('alpha') === reportDayKey('beta')) throw new Error('shared key')
if (reportDayKey('alpha') !== 'lastReportDay:alpha') throw new Error(reportDayKey('alpha'))
"""
        result = subprocess.run(["node", "-e", script], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_plugin_uses_only_supported_imports_and_no_secrets(self):
        imports = re.findall(r"from\s+['\"]([^'\"]+)['\"]", self.source)
        self.assertTrue(imports)
        self.assertTrue(set(imports) <= {"@hermes/plugin-sdk", "react", "react/jsx-runtime"})
        for forbidden in ("Authorization", "access_token", "api_key", "auth.json"):
            self.assertNotIn(forbidden, self.source)

    def test_uses_theme_tokens_instead_of_hardcoded_colors(self):
        self.assertIn("--ui-", self.source)
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", self.source))
        self.assertNotIn("rgb(", self.source)

    def test_renders_accessible_crystal_orb_with_dynamic_water_level(self):
        self.assertIn("function CrystalQuotaOrb", self.source)
        self.assertRegex(self.source, r"jsx[s]?\('svg'")
        self.assertIn("radialGradient", self.source)
        self.assertIn("linearGradient", self.source)
        self.assertIn("clipPath", self.source)
        self.assertIn("quota-orb-wave-front", self.source)
        self.assertIn("quota-orb-wave-back", self.source)
        self.assertIn("@keyframes quota-orb-wave", self.source)
        self.assertIn("prefers-reduced-motion: reduce", self.source)
        self.assertIn("var(--ui-green, var(--ui-accent))", self.source)
        self.assertIn("function liquidGeometry", self.source)
        self.assertIn("surfaceY", self.source)
        self.assertIn("waveAmplitude", self.source)
        self.assertIn("quota-orb-fill-clip", self.source)
        self.assertIn("quota-orb-liquid-stack", self.source)
        self.assertIn("role: 'progressbar'", self.source)
        self.assertIn("'aria-valuenow': clamped === null ? undefined : clamped", self.source)
        self.assertIn("'aria-valuenow': remaining === null ? undefined : remaining", self.source)
        self.assertIn("remaining === null ? `${window.label || t('quota')}: ${t('unknown')}`", self.source)

    def test_floating_orb_removes_card_chrome_without_touching_other_panes(self):
        self.assertIn('[data-floating-pane="quota-orb:orb"]', self.source)
        self.assertIn('background: transparent !important', self.source)
        self.assertIn('box-shadow: none !important', self.source)
        self.assertIn('> header { display: none !important; }', self.source)
        self.assertIn('.quota-orb-shell:focus-visible', self.source)

    def test_crystal_orb_has_specular_fresnel_and_organic_liquid_cues(self):
        for cue in (
            "quota-orb-glass-specular",
            "feSpecularLighting",
            "fePointLight",
            "quota-orb-fresnel",
            "quota-orb-meniscus",
            "quota-orb-wave-glint",
            "quota-orb-bubble",
            "@keyframes quota-orb-bubble-rise",
            "transform-box: fill-box",
        ):
            self.assertIn(cue, self.source)

    def test_emerald_magic_orb_has_layered_glass_and_volumetric_liquid(self):
        for cue in (
            "quota-orb-contact-shadow",
            "quota-orb-glass-inner-shell",
            "quota-orb-refraction-band",
            "quota-orb-liquid-body",
            "quota-orb-inner-caustic",
            "quota-orb-emerald-swirl-back",
            "quota-orb-emerald-swirl-front",
            "quota-orb-bubble-highlight",
            "quota-orb-magic-mote",
            "@keyframes quota-orb-mote-drift",
        ):
            self.assertIn(cue, self.source)
        reduced_motion = re.search(
            r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n          \}",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(reduced_motion)
        self.assertIn(".quota-orb-magic-mote", reduced_motion.group(1))
        self.assertIn(".quota-orb-emerald-swirl-front", reduced_motion.group(1))

    def test_detail_panel_uses_premium_glass_hierarchy(self):
        for cue in (
            "quota-orb-detail-panel",
            "quota-orb-panel-hero",
            "quota-orb-section",
            "blur(28px) saturate(145%)",
            "fontVariantNumeric: 'tabular-nums'",
            "quota-orb-panel-sheen",
        ):
            self.assertIn(cue, self.source)

    def test_liquid_surface_stays_crisp_and_reduced_motion_disables_hover_tilt(self):
        self.assertNotIn("@keyframes quota-orb-slosh", self.source)
        self.assertNotIn(".quota-orb-slosh", self.source)
        self.assertIn("className: 'quota-orb-water-glow'", self.source)
        self.assertIn(".quota-orb-shell:hover { transform: none !important; }", self.source)

    def test_liquid_geometry_keeps_zero_empty_and_scales_low_levels(self):
        helpers = []
        for name in ("finite", "clampPercent", "liquidGeometry"):
            match = re.search(rf"function {name}\([^)]*\) \{{.*?\n\}}", self.source, re.DOTALL)
            self.assertIsNotNone(match, name)
            helpers.append(match.group(0))
        script = "\n".join(helpers) + r"""
const zero = liquidGeometry(0)
if (zero.surfaceY !== 84 || zero.fillDepth !== 0 || zero.waveAmplitude !== 0 || zero.hasLiquid) throw new Error(JSON.stringify(zero))
const low = liquidGeometry(5)
if (!low.hasLiquid || low.fillDepth <= 0 || low.waveAmplitude > low.fillDepth || low.waveAmplitude >= 8) throw new Error(JSON.stringify(low))
const unknown = liquidGeometry(null)
if (unknown.clamped !== null || unknown.hasLiquid || unknown.fillDepth !== 0) throw new Error(JSON.stringify(unknown))
"""
        result = subprocess.run(["node", "-e", script], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_quota_uses_unavailable_progress_pattern(self):
        self.assertIn("quota-orb-quota-unavailable", self.source)
        self.assertNotIn("width: `${remaining ?? 0}%`", self.source)
        self.assertIn("width: `${remaining}%`", self.source)

    def test_details_group_local_usage_by_provider_and_model(self):
        self.assertIn("today.by_provider", self.source)
        self.assertIn("group.models", self.source)
        self.assertIn("profile", self.source)
        self.assertIn("modelUsage", self.source)
        self.assertIn("quotaSource", self.source)

    def test_uses_desktop_supported_simplified_chinese_locale(self):
        self.assertIn("zh: {", self.source)
        self.assertNotIn("'zh-Hans':", self.source)

    def test_supports_profile_persisted_tri_state_language_selector(self):
        for cue in (
            "const $languagePreferences = atom({})",
            "function useQuotaI18n",
            "function LanguageSwitcher",
            "language:${profileKey}",
            "id: 'auto'",
            "id: 'zh'",
            "id: 'en'",
            "role: 'group'",
            "'aria-pressed': languageMode === option.id",
            "quota-orb-language-switch",
            "quota-orb-language-section",
        ):
            self.assertIn(cue, self.source)
        self.assertNotIn("SegmentedControl", self.source)

    def test_manual_language_reuses_registered_locale_bundles(self):
        self.assertIn("let localeBundles = null", self.source)
        self.assertIn("localeBundles = {", self.source)
        self.assertIn("ctx.i18n.register(localeBundles)", self.source)
        self.assertIn("function translateBundle", self.source)
        self.assertEqual(self.source.count("usePluginI18n(ID)"), 1)
        self.assertIn("remainingShort", self.source)


if __name__ == "__main__":
    unittest.main()
