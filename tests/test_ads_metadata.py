from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = REPO_ROOT / "panel"
for _p in (str(REPO_ROOT), str(PANEL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import data as panel_data
import whatsapp_manager as wm


class TestAdsMetadataExtraction(unittest.TestCase):
    def test_extracts_meta_ads_fields(self):
        raw_meta = {
            "origin": "FB_Ads",
            "campaign": "Campanha Conversão",
            "ad_id": "2385123456789",
            "ad_title": "Superação de Dependência Emocional",
            "ad_source_app": "instagram",
            "ad_source_type": "ad",
            "ad_url": "https://fb.me/test",
            "ctwa_clid": "clid_1234567890abcdef",
            "conversion_delay_seconds": 15,
            "ad_media_type": "image",
            "utm_source": "meta_ads",
            "utm_medium": "cpc",
        }
        extracted = wm._extract_external_commercial_metadata({"commercial_metadata": raw_meta})
        self.assertEqual(extracted.get("origin"), "FB_Ads")
        self.assertEqual(extracted.get("campaign"), "Campanha Conversão")
        self.assertEqual(extracted.get("ad_id"), "2385123456789")
        self.assertEqual(extracted.get("ad_title"), "Superação de Dependência Emocional")
        self.assertEqual(extracted.get("ad_source_app"), "instagram")
        self.assertEqual(extracted.get("ctwa_clid"), "clid_1234567890abcdef")
        self.assertEqual(str(extracted.get("conversion_delay_seconds")), "15")

    def test_persist_external_commercial_metadata_with_ad_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            contacts_file = Path(tmp_dir) / "personal_contacts.json"
            contacts_file.write_text("{}", encoding="utf-8")
            with mock.patch.object(wm, "_PERSONAL_CONTACTS_PATH", contacts_file):
                metadata = {
                    "origin": "FB_Ads",
                    "campaign": "Dependência Emocional",
                    "ad_id": "999888777",
                    "ad_title": "Anúncio Vídeo 01",
                    "ad_source_app": "instagram",
                }
                persisted = wm._persist_external_commercial_metadata(
                    "5511999998888@s.whatsapp.net",
                    "5511999998888@s.whatsapp.net",
                    metadata,
                )
                self.assertEqual(persisted.get("origin"), "FB_Ads")
                self.assertEqual(persisted.get("ad_id"), "999888777")
                self.assertEqual(persisted.get("ad_title"), "Anúncio Vídeo 01")

                # Verify file contents
                with open(contacts_file, encoding="utf-8") as f:
                    saved = json.load(f)
                contact = saved.get("5511999998888") or saved.get("5511999998888@s.whatsapp.net")
                self.assertIsNotNone(contact)
                self.assertEqual(contact.get("ad_id"), "999888777")


class TestPanelAdsReport(unittest.TestCase):
    def test_ads_report_aggregation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            contacts_file = tmp_path / "personal_contacts.json"
            bookings_file = tmp_path / "calendar_bookings.db"
            missing = tmp_path / "missing"
            missing.mkdir()

            # Create mock bookings DB
            conn = sqlite3.connect(bookings_file)
            conn.execute(
                """
                CREATE TABLE current_bookings (
                    chat_key TEXT PRIMARY KEY,
                    event_id TEXT,
                    start TEXT,
                    end TEXT,
                    timezone TEXT,
                    meet_link TEXT,
                    html_link TEXT,
                    status TEXT,
                    created_at REAL,
                    updated_at REAL
                )
                """
            )
            import calendar_booking
            booked_key = calendar_booking._booking_chat_key("5511988887777@s.whatsapp.net")
            conn.execute(
                "INSERT INTO current_bookings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (booked_key, "evt_1", "2026-09-15T15:00:00Z", "2026-09-15T16:00:00Z", "America/Sao_Paulo", "https://meet.google.com/xyz", "", "active", 1789010000.0, 1789010000.0),
            )
            conn.commit()
            conn.close()

            # Contacts data
            contacts_data = {
                "5511988887777@s.whatsapp.net": {
                    "name": "Cliente Que Agendou",
                    "origin": "FB_Ads",
                    "campaign": "Campanha Teste",
                    "ad_id": "ad_101",
                    "ad_title": "Criativo Dep Emocional",
                    "ad_source_app": "instagram",
                    "first_live_inbound_at": 1789010000.0,
                    "commercial_stage": "SCHEDULED",
                },
                "5511977776666@s.whatsapp.net": {
                    "name": "Cliente Curioso",
                    "origin": "FB_Ads",
                    "campaign": "Campanha Teste",
                    "ad_id": "ad_102",
                    "ad_title": "Criativo Superação",
                    "ad_source_app": "facebook",
                    "first_live_inbound_at": 1789010500.0,
                    "commercial_stage": "IN_PROGRESS",
                },
            }
            contacts_file.write_text(json.dumps(contacts_data), encoding="utf-8")

            paths = panel_data.Paths(
                contacts_json=contacts_file,
                messages_db=missing / "messages.db",
                followups_db=missing / "followups.db",
                state_db=missing / "state.db",
                plugin_log=missing / "plugin.log",
                gateway_log=missing / "gateway.log",
                pricing_json=missing / "pricing.json",
                bookings_db=bookings_file,
            )

            report = panel_data.ads_report(paths)
            summary = report["summary"]
            self.assertEqual(summary["total_ad_leads"], 2)
            self.assertEqual(summary["total_booked"], 1)
            self.assertEqual(summary["conversion_rate_pct"], 50.0)
            self.assertEqual(summary["total_revenue_brl"], 247.0)

            # Check by_ad breakdown
            self.assertEqual(len(report["by_ad"]), 2)
            dep_emocional = next(a for a in report["by_ad"] if a["ad_id"] == "ad_101")
            self.assertEqual(dep_emocional["booked_count"], 1)
            self.assertEqual(dep_emocional["conversion_rate_pct"], 100.0)
            self.assertEqual(dep_emocional["revenue_brl"], 247.0)

            superacao = next(a for a in report["by_ad"] if a["ad_id"] == "ad_102")
            self.assertEqual(superacao["booked_count"], 0)
            self.assertEqual(superacao["conversion_rate_pct"], 0.0)

            # Check by_channel
            self.assertEqual(len(report["by_channel"]), 2)
            insta = next(c for c in report["by_channel"] if "Instagram" in c["channel"])
            self.assertEqual(insta["booked_count"], 1)

            # Check lead detail includes origin_metadata
            detail = panel_data.lead_detail(paths, "5511988887777@s.whatsapp.net")
            self.assertIn("origin_metadata", detail)
            self.assertEqual(detail["origin_metadata"]["ad_id"], "ad_101")
            self.assertEqual(detail["origin_metadata"]["ad_title"], "Criativo Dep Emocional")
            self.assertEqual(detail["origin_metadata"]["ad_source_app"], "instagram")


if __name__ == "__main__":
    unittest.main()
