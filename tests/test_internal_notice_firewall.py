"""Core Hermes status notices stay inside the delivery firewall."""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from test_humanization import CHAT, _FakeResponse, wm


CORE_EMPTY_REPLY_NOTICE = (
    "⚠️ No reply: the model returned empty content after retries and any fallback "
    "providers. Try `continue`, switch model/provider, or inspect the tool output above."
)


class InternalNoticeFirewallTest(unittest.TestCase):
    def test_new_core_notice_is_internal_and_normal_text_stays_allowed(self):
        self.assertTrue(wm.isSystemError(CORE_EMPTY_REPLY_NOTICE))
        self.assertTrue(wm.isSystemError("No reply: the model returned empty content after retries."))
        self.assertFalse(wm.isSystemError("Tudo bem. Como você vem lidando com isso?"))

    def test_human_send_drops_core_notice_before_calling_bridge(self):
        with mock.patch.object(wm.urllib.request, "urlopen") as urlopen:
            result = wm._human_send(CHAT, CORE_EMPTY_REPLY_NOTICE)

        self.assertIsNone(result)
        urlopen.assert_not_called()

    def test_human_send_still_delivers_legitimate_text_through_bridge(self):
        with mock.patch.dict(os.environ, {"WHATSAPP_HUMAN_TEST_MODE": "1"}), mock.patch.object(
            wm.urllib.request,
            "urlopen",
            return_value=_FakeResponse(json.dumps({"messageId": "wamid.safe"}).encode()),
        ) as urlopen:
            result = wm._human_send(CHAT, "Tudo bem. Como você vem lidando com isso?")

        self.assertEqual(result, "wamid.safe")
        self.assertEqual(urlopen.call_count, 1)
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/send"))
        self.assertEqual(json.loads(request.data)["message"], "Tudo bem. Como você vem lidando com isso?")


if __name__ == "__main__":
    unittest.main()
