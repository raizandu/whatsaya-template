"""Read clinical evidence from a verified PV chart without changing it.

The lists on the Evolution tab are summaries. They prove only the facts they
actually display; in particular a planned item is not a completed procedure or
an instruction to book its next step.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import re
from zoneinfo import ZoneInfo


_PATIENT_ID = re.compile(r"[1-9][0-9]{0,30}")
_EXECUTED = re.compile(r"^Executado em (\d{2}/\d{2}/\d{4})(?:\s|$)", re.IGNORECASE)
_LISTS = ("regTimeline_jqm_list_view", "tratamentosPlanejados_jqm_list_view",
          "tratamentosParticulares_jqm_list_view")
_LOCAL_ZONE = ZoneInfo('America/Sao_Paulo')


class ClinicalReadError(Exception):
    """Fixed error codes only; chart contents never enter logs or tool errors."""


def _page_row(browser, patient_id, clinic_name):
    from sync_prontuario_verde import PAGE_SCRIPT, NEXT_SCRIPT

    page = browser.evaluate(PAGE_SCRIPT)
    for _ in range(1000):
        if not isinstance(page, dict) or not isinstance(page.get("rows"), list):
            raise ClinicalReadError("chart_list_unavailable")
        header = [" ".join(line.upper().split()) for line in str(page.get("header", "")).splitlines()]
        if " ".join(clinic_name.upper().split()) not in header or page.get("active_filters") != []:
            raise ClinicalReadError("chart_list_scope_changed")
        found = [row for row in page["rows"] if isinstance(row, dict) and row.get("id") == patient_id]
        if len(found) > 1:
            raise ClinicalReadError("chart_identity_ambiguous")
        if found:
            return found[0]
        if page.get("has_next") is False:
            break
        if page.get("has_next") is not True:
            raise ClinicalReadError("chart_list_unavailable")
        page = browser.evaluate(NEXT_SCRIPT)
    raise ClinicalReadError("chart_patient_missing")


_OPEN_ROW = r"""(() => {
  const id = __ID__;
  const rows = [...document.querySelectorAll('#report_table_resultadoPesquisaPaciente tr')];
  const matches = rows.filter(row => {
    const href = row.querySelector('td[headers=MENU_OPCOES] a')?.getAttribute('href') || '';
    return href.match(/\bpac_id['"]?\s*:\s*['"]?(\d+)/)?.[1] === id;
  });
  if (matches.length !== 1) throw Error('chart_row_ambiguous');
  matches[0].querySelector('td[headers=MENU_OPCOES] a').click();
  return true;
})()"""

_OPEN_CHART = r"""(async () => {
  const end = Date.now() + 10000;
  while (Date.now() < end) {
    const links = [...document.querySelectorAll('a')].filter(a =>
      a.textContent.trim() === 'Prontuário do Paciente' && a.getClientRects().length);
    if (links.length === 1) { links[0].click(); return true; }
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw Error('chart_link_missing');
})()"""

_WAIT_CHART = r"""(async () => {
  const end = Date.now() + 25000;
  while (Date.now() < end) {
    const id = document.querySelector('#P4_PAC_ID')?.value;
    if (id) return {id, origin: location.origin};
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  return null;
})()"""

_READ_LISTS = r"""(async () => {
  const tab = document.querySelector('#TAB_EVOLUCAO');
  if (!tab) throw Error('evolution_tab_missing');
  tab.click();
  const ids = __LISTS__;
  const end = Date.now() + 20000;
  while (Date.now() < end) {
    const active = tab.classList.contains('apex-rds-element-selected');
    const lists = ids.map(id => document.getElementById(id));
    if (active && lists.every(ul => ul && ul.children.length > 0)) {
      await new Promise(resolve => setTimeout(resolve, 700));
      if (lists.every(ul => ul.isConnected && ul.children.length > 0)) {
        return {
          activeFilter: document.querySelector('#P4_EXIBIR_APENAS_EVOLUCOES_ATIVAS')?.value,
          lists: lists.map(ul => {
            const children = [...ul.children];
            const empty = children.some(li => li.classList.contains('apex-no-data-found'));
            if (empty && children.length !== 1) throw Error('mixed_empty_state');
            return {empty, items: empty ? [] : children.map(li => {
              if (li.tagName !== 'LI') throw Error('list_item_changed');
              const body = li.querySelector(':scope > a') || li;
              const title = [...body.childNodes].filter(node => node.nodeType === Node.TEXT_NODE)
                .map(node => node.textContent.trim()).find(Boolean) || '';
              return {title, aside: li.querySelector('.ui-li-aside')?.textContent.trim() || '',
                      status: li.querySelector('.cssTag')?.textContent.trim() || '',
                      text: li.innerText.trim()};
            })};
          })
        };
      }
    }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  return null;
})()""".replace("__LISTS__", json.dumps(_LISTS))


def read_chart(browser, config, patient_id):
    """Navigate by native list/menu, verify chart identity, and read active lists."""
    from register_prontuario_verde_patient import RegistrationBrowser
    from sync_prontuario_verde import SyncError

    if not isinstance(patient_id, str) or not _PATIENT_ID.fullmatch(patient_id):
        raise ClinicalReadError("chart_identity_unverified")
    expected_hash = config.get("source_clinic_hash")
    expected_name = config.get("expected_clinic_name")
    if not isinstance(expected_hash, str) or not isinstance(expected_name, str) or not expected_name:
        raise ClinicalReadError("chart_scope_unavailable")
    adapter = RegistrationBrowser(browser, config, "/opt/data/patient_directory.json")
    adapter._patients_url = getattr(browser, "_clinical_patients_url", None)
    adapter.open_patients()
    browser._clinical_patients_url = adapter._patients_url
    row = _page_row(browser, patient_id, expected_name)
    browser.evaluate(_OPEN_ROW.replace("__ID__", json.dumps(patient_id)))
    browser.evaluate(_OPEN_CHART)
    identity = browser.evaluate(_WAIT_CHART)
    if (not isinstance(identity, dict) or identity.get("id") != patient_id
            or identity.get("origin") != "https://app.prontuarioverde.com.br"):
        raise ClinicalReadError("chart_identity_unverified")
    browser.read_clinic_identity()
    if browser.source_clinic_hash != expected_hash:
        raise ClinicalReadError("chart_scope_changed")
    try:
        raw = browser.evaluate(_READ_LISTS)
    except SyncError as exc:
        if str(exc) != 'browser_eval_failed':
            raise
        # APEX can replace the list nodes just after selecting the tab. The
        # first evaluation is read-only; one delayed retry is safe.
        browser.command('wait', ['1000'])
        raw = browser.evaluate(_READ_LISTS)
    if (not isinstance(raw, dict) or raw.get("activeFilter") != "S"
            or not isinstance(raw.get("lists"), list) or len(raw["lists"]) != 3):
        raise ClinicalReadError("chart_load_incomplete")
    names = ("evolutions", "planned", "performed")
    facts = {"patient_id": patient_id, "record_number": row.get("record_number"),
             "source_clinic_hash": expected_hash,
             "read_at": datetime.now(timezone.utc).isoformat(), "active_only": True}
    for name, source, block in zip(names, _LISTS, raw["lists"]):
        if (not isinstance(block, dict) or not isinstance(block.get("empty"), bool)
                or not isinstance(block.get("items"), list)
                or (block["empty"] and block["items"])):
            raise ClinicalReadError("chart_load_incomplete")
        items = []
        for index, item in enumerate(block["items"]):
            if not isinstance(item, dict) or not all(isinstance(item.get(key), str)
                                                     for key in ("title", "aside", "status", "text")):
                raise ClinicalReadError("chart_item_changed")
            fact = {"source": source, "index": index, "title": item["title"],
                    "aside": item["aside"], "status": item["status"]}
            if name == "evolutions":
                fact["text"] = item["text"]
            if name == "performed":
                match = _EXECUTED.match(item["aside"])
                if match:
                    try:
                        occurred = datetime.strptime(match[1], "%d/%m/%Y").date()
                    except ValueError:
                        occurred = None
                    if occurred and occurred <= datetime.now(_LOCAL_ZONE).date():
                        fact["executed_on"] = occurred.isoformat()
            items.append(fact)
        facts[name] = items
    return facts


def policy_context(facts):
    """Only a dated executed item proves prior care from these summary lists."""
    performed = facts.get("performed", []) if isinstance(facts, dict) else []
    def prior_care(item):
        if (not isinstance(item, dict) or item.get('source') != _LISTS[2]
                or not isinstance(item.get('title'), str) or not item['title'].strip()):
            return False
        try:
            executed = date.fromisoformat(item['executed_on'])
        except (KeyError, TypeError, ValueError):
            return False
        return executed <= datetime.now(_LOCAL_ZONE).date()
    return {
        "established_patient": any(prior_care(item) for item in performed),
        "in_treatment": False,
        "no_added_procedure": False,
        "chart_verified": False,
    }
