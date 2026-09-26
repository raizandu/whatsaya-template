import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/scripts"))
from register_prontuario_verde_patient import RegistrationBrowser
from sync_prontuario_verde import PAGE_SCRIPT, SyncError

CONFIG = {"source_clinic_hash": "a"*64}
URL = "https://app.prontuarioverde.com.br/ords/f?p=100:13:123"

class RegistrationBrowserTests(unittest.TestCase):
    def browser(self):
        browser=Mock(source_clinic_hash=CONFIG["source_clinic_hash"])
        browser.tools.browser_navigate.return_value='{"success":true}'
        return browser

    def test_post_save_detail_without_sidebar_returns_to_observed_patient_list(self):
        browser=self.browser()
        browser.evaluate.side_effect=[URL,None]
        adapter=RegistrationBrowser(browser,CONFIG,"unused")
        adapter.open_patients()
        adapter.open_patients()
        self.assertEqual([call.args for call in browser.command.call_args_list if call.args[0]=="open"],
                         [("open",[URL]),("open",[URL])])

    def test_missing_unobserved_list_link_and_foreign_origin_fail_closed(self):
        for link in (None, "https://example.test/ords/f?p=100:13:123"):
            browser=self.browser();browser.evaluate.return_value=link
            with self.assertRaisesRegex(SyncError,"patient_navigation_changed"):
                RegistrationBrowser(browser,CONFIG,"unused").open_patients()

    def test_phone_only_lookup_skips_names_on_pages_without_matching_phone(self):
        browser=self.browser()
        page={"rows":[{"id":"1","phone_text":"(11) 99999-8888"}]}
        browser.evaluate.return_value=page
        adapter=RegistrationBrowser(browser,CONFIG,"unused")
        adapter.phone="5511999997777";adapter.name=""
        self.assertEqual(adapter.evaluate(PAGE_SCRIPT),page)
        self.assertEqual(browser.evaluate.call_count,1)

    def test_registration_still_checks_name_candidates_on_every_page(self):
        browser=self.browser()
        page={"rows":[{"id":"1","phone_text":"(11) 99999-8888"}]}
        browser.evaluate.side_effect=[page,{"names":{},"candidates":["1"]}]
        adapter=RegistrationBrowser(browser,CONFIG,"unused")
        adapter.phone="5511999997777";adapter.name="Pessoa Exemplo"
        adapter.evaluate(PAGE_SCRIPT)
        self.assertEqual(adapter.name_candidates,{"1"})
        self.assertEqual(browser.evaluate.call_count,2)
