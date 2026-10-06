"""Production v12 integration: public examples cannot replace account workflows."""
from pathlib import Path
import re
import unittest
import jiejing_prepare_public_staging_bundle as bundle

ROOT = Path(__file__).resolve().parents[1]

class PublicDesignRelease(unittest.TestCase):
    def test_ai_ceo_name_is_consistent_across_merchant_surfaces(self):
        surfaces = [ROOT / name for name in ('index.html', 'app.html', 'app.js')]
        surfaces += [path for path in (ROOT / 'assets').rglob('*')
                     if path.is_file() and path.suffix in {'.html', '.js', '.css', '.svg'}]
        retired_name = re.compile(r'\bJV[\s_-]*AI\b', re.I)
        for path in surfaces:
            with self.subTest(surface=path.relative_to(ROOT).as_posix()):
                self.assertIsNone(retired_name.search(path.read_text(encoding='utf-8')),
                                  'Merchant surfaces must use AI CEO, not the retired name')
        for name in ('index.html', 'app.html', 'app.js',
                     'assets/workbench-demo/index.html', 'assets/workbench-demo/workbench.js'):
            self.assertTrue('AI CEO' in (ROOT / name).read_text(encoding='utf-8'), name)

    def test_real_entry_is_preserved(self):
        home = (ROOT / 'index.html').read_text(encoding='utf-8')
        for marker in ['id="nextStepModal"', 'id="entryLoginForm"', 'id="entryChallengeWidget"',
                       'function openWorkbenchOrAuth', 'function submitEntryAuth',
                       'function continueAfterLogin', 'function openAuthModalFromUrl']:
            self.assertIn(marker, home)
        self.assertNotIn('id="previewNotice"', home)
        visual = (ROOT / 'assets/homepage-finish.js').read_text(encoding='utf-8')
        self.assertNotIn('showNotice', visual)
        self.assertNotIn('fetch(', visual)
        self.assertNotIn('entryAuthPassword', visual)

    def test_demo_is_separate_and_inert(self):
        home = (ROOT / 'index.html').read_text(encoding='utf-8')
        app = (ROOT / 'app.html').read_text(encoding='utf-8')
        demo = ROOT / 'assets/workbench-demo'
        self.assertIn('./assets/workbench-demo/index.html', home)
        self.assertNotIn('workbench-demo', app)
        for name in ['workbench-state.js', 'workbench.js', 'media-data.js']:
            source = (demo / name).read_text(encoding='utf-8')
            for unsafe in ['fetch(', 'XMLHttpRequest', 'sendBeacon(', 'sessionStorage', 'localStorage']:
                self.assertNotIn(unsafe, source)
        html = (demo / 'index.html').read_text(encoding='utf-8')
        self.assertIn('noindex,nofollow', html)
        self.assertIn('不会', html)
        self.assertIn('disabled', html)
        self.assertNotIn('srcset="assets/', html)
        self.assertIn('href="../../"', html)
        self.assertIn('href="../../#workflow"', html)
        self.assertIn('href="../../#plans"', html)
        self.assertNotIn('href="./#', html)

    def test_every_whitelisted_file_passes_bundle_filter(self):
        whitelist = bundle._parse_apply_patch_file_list(
            (ROOT / 'deploy/apply-staging-patch.sh').read_text(encoding='utf-8'))
        actual = [path.relative_to(ROOT).as_posix()
                  for path in bundle._iter_bundle_files(whitelist)]
        self.assertEqual(actual, whitelist)
        self.assertIn('assets/workbench-demo/workbench-state.js', actual)
        html = (ROOT / 'assets/workbench-demo/index.html').read_text(encoding='utf-8')
        for name in re.findall(r'<script\s+src="\./([^"?]+)', html):
            self.assertIn(f'assets/workbench-demo/{name}', actual)
        self.assertTrue(bundle._is_excluded(ROOT / 'assets/demo-private-data.js'))
        self.assertTrue(bundle._is_excluded(ROOT / '.env'))
        self.assertTrue(bundle._is_excluded(ROOT / 'output/private.json'))

    def test_fonts_and_all_responsive_images_ship(self):
        whitelist = (ROOT / 'deploy/apply-staging-patch.sh').read_text(encoding='utf-8')
        files = ['jiejing-sans-20260928.woff2','jiejing-serif-20260928.woff2',
                 'noto-sans-sc-OFL.txt','noto-serif-sc-OFL.txt','travel-compression-source.webp']
        files += [f'packing-{scene}-v6-{size}.webp' for scene in ['collection','suitcase','packing','detail']
                  for size in [360,720,1080,1448]]
        for name in files:
            self.assertTrue((ROOT / 'assets' / name).is_file(), name)
            self.assertIn(f'"assets/{name}"', whitelist)
        css = (ROOT / 'assets/homepage-finish.css').read_text(encoding='utf-8')
        self.assertNotIn('url("./assets/', css)
        self.assertIn('font-display:swap', css)
        self.assertIn('"Microsoft YaHei"', css)

    def test_auth_state_has_no_underlying_homepage(self):
        css = (ROOT / 'assets/jiejing-home-entry.css').read_text(encoding='utf-8')
        self.assertIn('body.workflow-home.is-auth-mode > :not(#nextStepModal):not(#toast):not(script){display:none}', css)
        self.assertIn('.step-modal:not(.is-open){visibility:hidden}', css)
        self.assertIn('font-size:16px', css)

    def test_protocol_and_app_entry_stay_real(self):
        app = (ROOT / 'app.js').read_text(encoding='utf-8')
        self.assertIn('name="ai_ceo_prompt"', app)
        self.assertIn('jiejingTrustedTemplate("ai_ceo.cockpit")', app)
        self.assertIn('cockpit.dataset.title = "AI CEO"', app)
        self.assertNotIn('JiejingDemoState', app)
        self.assertNotIn('packing-collection-v6', app)

if __name__ == '__main__':
    unittest.main(verbosity=2)
