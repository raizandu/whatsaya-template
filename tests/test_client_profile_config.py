import ast
from pathlib import Path
import textwrap
import unittest


def client_profile(toolsets):
    source = (Path(__file__).resolve().parents[1] / 'deploy/docker-compose.yml').read_text()
    block = source.split("python3 - <<'PYCFG'", 1)[1].split('\n        PYCFG', 1)[0]
    tree = ast.parse(textwrap.dedent(block))
    profiles = [node.args[0] for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'dump' and node.args and isinstance(node.args[0], ast.Dict)
                and any(isinstance(key, ast.Constant) and key.value == 'toolsets' for key in node.args[0].keys)]
    assert len(profiles) == 1
    disabled = next(node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'disabled' for target in node.targets))
    values = dict(client_model='fixture', client_provider='fixture', client_reasoning_effort='medium',
                  fallback_chain=[], client_toolsets=toolsets, disabled=ast.literal_eval(disabled))
    return eval(compile(ast.Expression(profiles[0]), '<client-profile>', 'eval'), {'__builtins__': {}}, values)


class ClientProfileConfigTests(unittest.TestCase):
    def test_clinical_instructions_are_not_replaced_by_an_unreadable_spill_file(self):
        profile = client_profile(['whatsaya_pv_calendar'])
        self.assertFalse(profile['hooks']['output_spill']['enabled'])
        self.assertEqual(profile['tools']['tool_search']['enabled'], 'off')
        self.assertEqual(profile['terminal']['backend'], 'disabled')

    def test_gateway_receives_explicit_toolsets_and_current_suppression_keys(self):
        for allowed in ([], ['whatsaya_calendar', 'whatsaya_pv_calendar']):
            with self.subTest(allowed=allowed):
                profile = client_profile(allowed)
                self.assertEqual(profile['platform_toolsets']['whatsapp'], allowed)
                self.assertIn('browser', profile['agent']['disabled_toolsets'])
                self.assertIn('terminal', profile['agent']['disabled_toolsets'])
                self.assertNotIn('whatsaya_pv_calendar', profile['agent']['disabled_toolsets'])


if __name__ == '__main__':
    unittest.main()
