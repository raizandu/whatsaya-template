import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import whatsapp_manager as wm


class CodexMediaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.image = Path(temporary.name) / "fixture.png"
        self.image.write_bytes(b"image-fixture")
        self.event = SimpleNamespace(media_type="image", media_urls=[str(self.image)],
                                     text="", raw_message={})
        self.client = Mock()
        self.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Uma imagem de teste."))])
        self.aux = SimpleNamespace(resolve_provider_client=Mock(return_value=(self.client, "gpt-6-luna")))
        module = patch.dict(sys.modules, {"agent": SimpleNamespace(), "agent.auxiliary_client": self.aux})
        module.start()
        self.addCleanup(module.stop)
        env = patch.dict(wm.os.environ, {
            "WHATSAPP_CLIENT_PROVIDER": "openai-codex", "WHATSAPP_CLIENT_MODEL": "gpt-6-luna",
            "GOOGLE_API_KEY": "", "OPENAI_API_KEY": "", "OPENROUTER_API_KEY": "broken-router-key",
        })
        env.start()
        self.addCleanup(env.stop)

    def test_image_uses_configured_codex_instead_of_external_key_chain(self):
        with patch.object(wm.urllib.request, "urlopen") as external:
            self.assertEqual(wm._process_media_message(self.event), "Uma imagem de teste.")
        external.assert_not_called()
        self.aux.resolve_provider_client.assert_called_once_with(
            "openai-codex", model="gpt-6-luna", is_vision=True)
        request = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "gpt-6-luna")
        self.assertEqual(request["messages"][0]["content"][0]["type"], "image_url")
        self.assertTrue(self.image.exists())
        self.client.close.assert_called_once()

    def test_codex_failure_does_not_silently_switch_provider(self):
        self.aux.resolve_provider_client.side_effect = RuntimeError("not available")
        with patch.object(wm.urllib.request, "urlopen") as external:
            self.assertIsNone(wm._process_media_message(self.event))
        external.assert_not_called()

    def test_receipt_extractor_uses_same_codex_route(self):
        self.client.chat.completions.create.return_value.choices[0].message.content = '{"is_payment_receipt": false}'
        with patch.object(wm.urllib.request, "urlopen") as external:
            result = wm._detect_and_extract_sale_from_image([str(self.image)])
            self.assertFalse(result["is_payment_receipt"])
            self.assertIsNone(result["amount"])
        external.assert_not_called()

    def test_codex_does_not_require_an_api_key(self):
        with patch.dict(wm.os.environ, {"OPENROUTER_API_KEY": ""}):
            self.assertEqual(wm._process_media_message(self.event), "Uma imagem de teste.")

    def test_contact_classification_also_honors_codex(self):
        self.client.chat.completions.create.return_value.choices[0].message.content = '{}'
        with patch.object(wm.urllib.request, "urlopen") as external:
            result = wm._classify_contact_via_llm("Fixture", "Contato: quero avaliação", "Two messages")
        external.assert_not_called()
        self.assertIsInstance(result, dict)
        self.aux.resolve_provider_client.assert_called_once_with(
            "openai-codex", model="gpt-6-luna", is_vision=False)
