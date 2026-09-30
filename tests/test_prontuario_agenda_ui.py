from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "panel/static/views/prontuario-agenda.js"


@unittest.skipUnless(shutil.which("node"), "Node is required to render the agenda component")
class ProntuarioAgendaViewTests(unittest.TestCase):
    def test_identity_pending_row_interpolates_label_as_text_without_controls(self):
        source_path = json.dumps(str(VIEW))
        script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(SOURCE_PATH, 'utf8')
  .replace(/^import .*;\s*$/gm, '')
  .replace('function AppointmentList(', 'globalThis.AppointmentList = function AppointmentList(')
  .replace('export default function ProntuarioAgenda(', 'function ProntuarioAgenda(');
const escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
})[char]);
const render = value => {
  if (value == null || value === false || value === true) return '';
  if (Array.isArray(value)) return value.map(render).join('');
  if (value && Array.isArray(value.strings) && Array.isArray(value.values)) {
    return value.strings.map((chunk, index) => chunk +
      (index < value.values.length ? render(value.values[index]) : '')).join('');
  }
  return escapeHtml(value);
};
const html = (strings, ...values) => ({strings: Array.from(strings), values});
const context = {html, Intl, Date, Array, Map, Set};
vm.runInNewContext(source, context, {filename: 'prontuario-agenda.js'});
const unsafePatientLabel = '<img src=x onerror=alert(1)>';
const unsafeProfessionalLabel = '<svg onload=alert(1)>';
const markup = render(context.AppointmentList({
  selectedDay: '2026-09-30',
  events: [{id: '902', identity_pending: true, status: 'agendado',
    start: '2026-09-30T16:00:00-03:00', end: '2026-09-30T16:30:00-03:00',
    patient_name: unsafePatientLabel, professional_name: unsafeProfessionalLabel}]
}));
process.stdout.write(markup);
""".replace("SOURCE_PATH", source_path)
        result = subprocess.run(
            [shutil.which("node"), "-e", script], capture_output=True, text=True,
            check=True, timeout=10,
        )
        rendered = result.stdout
        self.assertIn('aria-label="Agendamentos sem vínculo"', rendered)
        self.assertIn("Identidade pendente", rendered)
        self.assertIn("Sem vínculo cadastral. Confirme no Prontuário Verde antes de agir.", rendered)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", rendered)
        self.assertIn("&lt;svg onload=alert(1)&gt;", rendered)
        self.assertNotIn("<img", rendered)
        self.assertNotIn("<svg", rendered)
        self.assertNotRegex(rendered, r"<(?:a|button)\b")


if __name__ == "__main__":
    unittest.main()
