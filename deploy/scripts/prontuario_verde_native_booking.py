"""Fail-closed Hermes browser port for the native PV appointment form.

The write path is deliberately opt-in (`enabled` and
`appointment_write_enabled` must both be exactly true). No code here logs in,
reads credentials, or submits unless an explicitly enabled writer calls
`submit_once`. A successful HTTP/APEX response is never treated as proof; the
caller must force a fresh read and reconcile exact appointment identity.

Documented form controls include P41_UNIDADE, P41_PROFISSIONAL_AGENDAR,
P41_DATA_AGENDAR, P41_HORARIO_AGENDAR/P41_HORARIO_LIVRE, P41_DURACAO,
P41_TIPO_AGENDAMENTO, P41_NOME_PACIENTE, P41_ID_PACIENTE, and
botaoAgendarPaciente. Dates use dd/mm/yyyy; 40-minute appointments use
the native Other-duration popup. Patient selection uses a real suggestion
and verifies ID/phone, but its clinic-bound identity lookup and the complete
persisted identity reader are not wired by default. Missing providers raise
stable errors instead of guessing.
The displayed time select is not itself availability proof: it can retain a
stale hour after changing dates. A separate complete Abertura snapshot and a
verified duplicate query are required before a prepared result is accepted.
The documented form does not identify a verified opaque request-marker field;
an exact unique post-save match can establish current appointment state but
cannot prove this worker, rather than a concurrent human action, created it.
This adapter therefore remains disabled until identity and attribution gaps
are closed.

Manual workflow evidence: client-private
`docs/prontuario-verde-integracao.md` (23/09/2026). Do not log raw DOM,
appointment titles, names, phone numbers, tokens, APEX payloads, or errors.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import time
from typing import Any, Callable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from prontuario_verde_appointment_writer import AppointmentWriteError
from prontuario_verde_availability import AvailabilityError, available_starts


SAO_PAULO = ZoneInfo("America/Sao_Paulo")
_ID = re.compile(r"[1-9][0-9]*\Z")
_FORM_FIELDS = (
    "P41_UNIDADE", "P41_PROFISSIONAL_AGENDAR", "P41_DATA_AGENDAR",
    "P41_HORARIO_AGENDAR", "P41_HORARIO_LIVRE", "P41_DURACAO",
    "P41_DURACAO_LIVRE", "P41_TIPO_AGENDAMENTO", "P41_ID_PACIENTE",
)


class NativeBookingError(AppointmentWriteError):
    """Sanitized stable failure; never includes page text or patient values."""


class ProntuarioVerdeHermesPort:
    """HermesBrowser port for the appointment writer.

    `opening_provider(request)` must return an Abertura `OpeningSnapshot` for
    the exact clinic/professional/unit/day. `target_reader(request)` must
    return a complete normalized set of existing exact-identity matches; an
    empty list is accepted only after the reader asserts completeness. They
    are injected because the native form's stale select and event feed cannot
    independently prove a free interval or duplicate absence.

    `patient_selector` is an injected UI operation returning the selected ID.
    A caller with clinic-verified search text and phone can bind `select_patient`
    to this callback. Without an identity provider, creation fails closed.
    The callback must never return or log the patient's display name or phone.
    """

    def __init__(
        self,
        browser: Any,
        config: dict[str, Any],
        *,
        opening_provider: Callable[[dict[str, Any]], Any] | None = None,
        target_reader: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        old_appointment_reader: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        patient_selector: Callable[[Any, str], str] | None = None,
        timeout_seconds: float = 20,
    ):
        self.browser = browser
        self.config = config if isinstance(config, dict) else {}
        self.opening_provider = opening_provider
        self.target_reader = target_reader
        self.old_appointment_reader = old_appointment_reader
        self.patient_selector = patient_selector
        self.timeout_seconds = min(max(float(timeout_seconds), 1), 60)
        self._prepared: dict[str, Any] | None = None
        self._submitted = False

    def prepare(self, request: dict[str, Any]) -> dict[str, Any]:
        if self._submitted:
            raise NativeBookingError("submit_already_attempted")
        # A failed new preflight must invalidate any earlier prepared form.
        self._prepared = None
        self._require_enabled()
        self._check_scope(request)
        if not callable(self.opening_provider):
            raise NativeBookingError("opening_source_unavailable")
        if not callable(self.target_reader):
            raise NativeBookingError("duplicate_reader_unavailable")
        if request.get("procedure_id") is not None:
            raise NativeBookingError("procedure_form_contract_unknown")
        if request["operation"] == "reschedule" and not callable(self.old_appointment_reader):
            raise NativeBookingError("old_appointment_state_unavailable")
        if not callable(self.patient_selector):
            raise NativeBookingError("patient_autocomplete_unverified")
        if request.get("duration_min") not in (30, 40, 60, 90, 120):
            raise NativeBookingError("duration_form_contract_unknown")

        self._require_authenticated_agenda(request)
        self._open_native_form(request)
        # Capture the validated original before editing its time fields.
        original = self._read_original(request) if request["operation"] == "reschedule" else None
        self._fill_known_fields(request)
        selected_patient = self.patient_selector(self.browser, str(request["patient_id"]))
        if str(selected_patient) != str(request["patient_id"]):
            raise NativeBookingError("patient_selection_mismatch")

        form = self._read_form()
        self._validate_form(form, request)
        self._verify_live_target(request)

        checked_at = datetime.now(timezone.utc).isoformat()
        prepared = {
            "clinic_id": request["clinic_id"],
            "source_clinic_hash": request["source_clinic_hash"],
            "patient_id": str(form["patient_id"]),
            "professional_id": str(form["professional_id"]),
            "unit_id": str(form["unit_id"]),
            "type_id": str(form["type_id"]),
            "duration_min": int(form["duration_min"]),
            "start": form["start"], "end": form["end"],
            "availability": {
                "status": "available",
                "professional_id": str(request["professional_id"]),
                "unit_id": str(request["unit_id"]),
                "source_clinic_hash": request["source_clinic_hash"],
                "start": request["requested_start"],
                "end": request["requested_end"],
                "checked_at": checked_at,
            },
            "target_matches": [],
        }
        if request.get("procedure_id") is not None:
            prepared["procedure_id"] = str(form["procedure_id"])
        if request["operation"] == "reschedule":
            prepared["original_appointment"] = original
        self._prepared = dict(request)
        self._submitted = False
        return prepared

    def _verify_live_target(self, request: dict[str, Any]) -> None:
        opening = self.opening_provider(request)
        try:
            starts = available_starts(
                opening,
                source_clinic_hash=request["source_clinic_hash"],
                professional_id=str(request["professional_id"]),
                unit_id=str(request["unit_id"]),
                day=datetime.fromisoformat(request["requested_start"]).astimezone(SAO_PAULO).date(),
                duration_minutes=request["duration_min"],
                now=datetime.now(timezone.utc),
            )
        except (AvailabilityError, TypeError, ValueError):
            raise NativeBookingError("slot_not_verified_available") from None
        start = _instant(request["requested_start"])
        if start not in starts:
            raise NativeBookingError("slot_not_verified_available")

        matches = self._complete_rows(self.target_reader(request), request)
        self._validate_target_rows(matches, request)
        if matches:
            raise NativeBookingError("target_already_present")

    def submit_once(self, request: dict[str, Any]) -> None:
        self._require_enabled()
        if self._submitted:
            raise NativeBookingError("submit_already_attempted")
        if not self._same_request(request, self._prepared):
            raise NativeBookingError("preflight_not_current")
        self._check_scope(request)
        self._verify_live_target(request)
        self._validate_form(self._read_form(), request)
        self._verify_native_opening(request)
        # Mark before crossing the boundary: browser timeout can follow a PV save.
        self._submitted = True
        try:
            result = self._eval("(()=>{const b=document.querySelector('#botaoAgendarPaciente');if(!b||b.disabled)throw Error('submit_control_unavailable');b.click();return true})()")
            if result is not True:
                raise NativeBookingError("submit_outcome_uncertain")
            # APEX saves through asynchronous dynamic actions. Reloading before
            # they finish can abort the request; wait for the native form to
            # close and its requests to settle before reconciling on a new page.
            self._wait("typeof jQuery!=='undefined' && jQuery.active===0 && !!document.querySelector('#agendar') && !document.querySelector('#agendar').getClientRects().length")
        except Exception:
            # Caller must reconcile. Do not retry this click.
            raise NativeBookingError("submit_outcome_uncertain") from None

    def _verify_native_opening(self, request: dict[str, Any]) -> None:
        # Invoke only the observed read-only validation action, never the
        # button's full action chain (which contains the actual save).
        result = self._eval("""(async()=>{
          const flags=['P41_ENCAIXE','P41_TUDO_LIVRE','P41_LIBERA_AGENDA'];
          if(flags.some(id=>!document.getElementById(id)||String(apex.item(id).getValue())==='S'))return null;
          const events=apex.da.gEventList.filter(e=>e.triggeringButtonId==='botaoAgendarPaciente'&&e.bindEventType==='click');
          const checks=events.flatMap(e=>e.actionList).filter(a=>a.action==='NATIVE_EXECUTE_PLSQL_CODE'&&a.attribute02==='#P41_MSG_FORA_AGENDA');
          if(checks.length!==1)return null;
          const check=checks[0];
          const required=['#P41_DATA_AGENDAR','#P41_PROFISSIONAL_AGENDAR','#P41_DURACAO','#P41_ID_AGENDA'];
          if(required.some(id=>!check.attribute01.split(',').includes(id)))return null;
          const r=await apex.server.plugin(check.ajaxIdentifier,{pageItems:check.attribute01},{dataType:'json'});
          if(!Array.isArray(r.item)||r.item.length!==1||r.item[0].id!=='P41_MSG_FORA_AGENDA')return null;
          return {within_opening:r.item[0].value==='',duration_max:String(apex.item('P41_DURACAO_MAXIMA').getValue())};
        })()""")
        if not isinstance(result, dict) or result.get("within_opening") is not True:
            raise NativeBookingError("native_opening_unverified")
        maximum = result.get("duration_max")
        if not isinstance(maximum, str) or not maximum.isdecimal() or int(maximum) < request["duration_min"]:
            raise NativeBookingError("native_duration_unavailable")
        self._validate_form(self._read_form(), request)

    def reconcile_after_save(self, request: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        if not self._same_request(request, self._prepared) or not self._submitted:
            raise NativeBookingError("post_save_read_not_authorized")
        try:
            self._eval("location.reload();true")
            self._wait("typeof window.calendar!=='undefined' && !!document.querySelector('#P41_PROFISSIONAL')")
            rows = self._read_reconciliation_matches(request)
            if request["operation"] == "reschedule":
                original = self._read_old_after_reload(request)
            else:
                original = None
        except Exception:
            raise NativeBookingError("post_save_read_failed") from None
        result: dict[str, Any] = {
            "clinic_id": request["clinic_id"],
            "source_clinic_hash": request["source_clinic_hash"],
            "matches": rows,
        }
        if original is not None:
            result.update(original)
        return result

    def _require_enabled(self) -> None:
        if not (self.config.get("enabled") is True
                and self.config.get("appointment_write_enabled") is True):
            raise NativeBookingError("appointment_writes_disabled")

    def _check_scope(self, request: dict[str, Any]) -> None:
        if (getattr(self.browser, "source_clinic_hash", None) != request.get("source_clinic_hash")
                or self.config.get("clinic_id") != request.get("clinic_id")
                or self.config.get("source_clinic_hash") != request.get("source_clinic_hash")):
            raise NativeBookingError("clinic_mismatch")

    def _require_authenticated_agenda(self, request: dict[str, Any]) -> None:
        try:
            if not self.browser.refresh_authenticated():
                raise NativeBookingError("session_not_fresh")
            current = self._eval("location.href")
            parsed = urlsplit(current or "")
            if parsed.scheme != "https" or parsed.hostname != "app.prontuarioverde.com.br":
                raise NativeBookingError("invalid_login_origin")
            if getattr(self.browser, "source_clinic_hash", None) != request["source_clinic_hash"]:
                raise NativeBookingError("clinic_mismatch")
        except NativeBookingError:
            raise
        except Exception:
            raise NativeBookingError("session_not_fresh") from None

    def _open_native_form(self, request: dict[str, Any]) -> None:
        self._eval("Array.from(document.querySelectorAll('a[role=treeitem]')).find(e=>e.textContent.trim()==='Agenda')?.click();true")
        self._wait("typeof window.calendar!=='undefined' && !!document.querySelector('#P41_PROFISSIONAL')")
        if request["operation"] == "reschedule":
            self._open_original_for_edit(request)
        else:
            self._eval("document.querySelector('#BT_NOVO')?.click();true")
            self._wait("!!document.querySelector('#B11744479737920542')")
            self._eval("document.querySelector('#B11744479737920542')?.click();true")
        self._wait("!!document.querySelector('#P41_ID_PACIENTE') && !!document.querySelector('#botaoAgendarPaciente')")

    def _open_original_for_edit(self, request: dict[str, Any]) -> None:
        start = datetime.fromisoformat(request["expected_start"]).astimezone(SAO_PAULO).date().isoformat()
        professional = _js(str(request["professional_id"]))
        appointment = _js(str(request["appointment_id"]))
        self._eval(f"apex.item('P41_PROFISSIONAL').setValue({professional});calendar.gotoDate({_js(start)});calendar.refetchEvents();true")
        event = self._wait(
            "(()=>{const e=calendar.getEvents().find(x=>String(x.id)===" + appointment + ");"
            "return e?{id:String(e.id),start:e.startStr,end:e.endStr,professional_id:String(e.getResources()[0]?.id||'')}:null})()"
        )
        if (not isinstance(event, dict) or event.get("id") != str(request["appointment_id"])
                or event.get("professional_id") != str(request["professional_id"])
                or not _same_time(event.get("start"), request["expected_start"])
                or not _same_time(event.get("end"), request["expected_end"])):
            raise NativeBookingError("original_appointment_changed")
        self._eval(f"calendar.getOption('eventClick')({{event:calendar.getEvents().find(x=>String(x.id)==={appointment})}});true")
        self._wait("!!document.querySelector('#LINK_EDITAR_AGENDAMENTO')")
        self._eval("document.querySelector('#LINK_EDITAR_AGENDAMENTO').click();true")
        self._wait("!!document.querySelector('#P41_ID_AGENDA') && !!document.querySelector('#botaoAgendarPaciente')")
        original = self._read_form()
        self._validate_original_form(original, request)

    def _fill_known_fields(self, request: dict[str, Any]) -> None:
        # Select controls and the documented APEX date item are checked again
        # after each change. Any changed form contract fails before submit.
        fields = {"P41_UNIDADE": request["unit_id"],
                  "P41_PROFISSIONAL_AGENDAR": request["professional_id"],
                  "P41_TIPO_AGENDAMENTO": request["type_id"]}
        for item, value in fields.items():
            self._set_select(item, str(value))
            self._wait("typeof jQuery!=='undefined' && jQuery.active===0")
        target_date = datetime.fromisoformat(request["requested_start"]).astimezone(SAO_PAULO).strftime("%d/%m/%Y")
        self._set_apex_item("P41_DATA_AGENDAR", target_date)
        self._wait("typeof jQuery!=='undefined' && jQuery.active===0")
        # Time selects may be stale; they reflect the selected target only.
        # Abertura remains the availability proof.
        clock = datetime.fromisoformat(request["requested_start"]).astimezone(SAO_PAULO).strftime("%H:%M")
        mode = self._eval("(()=>{const e=document.querySelector('#P41_DURACAO_LIVRE');return e?String(apex.item('P41_DURACAO_LIVRE').getValue()):null})()")
        if mode == "S":
            self._set_apex_item("P41_HORARIO_LIVRE", clock)
            self._eval("(()=>{const e=document.querySelector('#P41_HORARIO_LIVRE');if(!e)throw Error('time_control_unavailable');e.dispatchEvent(new Event('blur',{bubbles:true}));return true})()")
        elif mode in ("N", "", "0"):
            self._wait("(()=>{const e=document.querySelector('#P41_HORARIO_AGENDAR');return !!e&&Array.from(e.options).some(o=>o.value===" + _js(clock) + ")})()")
            self._set_select("P41_HORARIO_AGENDAR", clock)
        else:
            raise NativeBookingError("time_mode_unverified")
        duration = str(request["duration_min"])
        option = "9999999999" if duration == "40" else duration
        self._wait("(()=>{const e=document.querySelector('#P41_DURACAO');return !!e&&Array.from(e.options).some(o=>o.value===" + _js(option) + ")})()")
        self._set_select("P41_DURACAO", option)
        if duration == "40":
            # Native Other popup validates and adds minutes to the real select.
            # This only proves form acceptance, never a released opening:
            # PV can allow booking closed agendas for privileged accounts.
            self._wait("!!document.querySelector('#P41_NOVA_DURACAO')?.getClientRects().length")
            self._set_apex_item("P41_NOVA_DURACAO", duration)
            accepted = self._eval("(()=>{const b=document.querySelector('#BT_INFORMADO_OK');if(!b||b.disabled)return false;b.click();return true})()")
            if accepted is not True:
                raise NativeBookingError("duration_form_contract_unknown")
            self._wait("String(apex.item('P41_DURACAO').getValue())==='40' && !document.querySelector('#P41_NOVA_DURACAO')?.getClientRects().length")
        # Selecting a registered patient requires the real autocomplete option;
        # this is delegated to patient_selector, whose result is checked below.

    def select_patient(self, patient_id: str, search_text: str, expected_phone: str) -> str:
        """Choose a real suggestion and await its exact ID/phone binding.

        The caller supplies a search label for an already verified identity.
        The label only locates suggestions; it never establishes identity.
        This method neither assigns hidden patient IDs nor saves the form.
        """
        from patient_directory import normalize_phone

        phone = normalize_phone(expected_phone)
        if (not isinstance(patient_id, str) or not _ID.fullmatch(patient_id)
                or phone is None or not isinstance(search_text, str)
                or not 3 <= len(search_text.strip()) <= 200
                or any(ord(c) < 32 or c in '<>"' for c in search_text)):
            raise NativeBookingError("patient_search_invalid")
        search_text = search_text.strip()
        try:
            # Focus through the browser: hidden autocomplete suggestions are
            # not evidence that the native control actually selected a record.
            self.browser.command("fill", ["#P41_NOME_PACIENTE", search_text])
            self._eval("$('#P41_NOME_PACIENTE').trigger($.Event('keyup',{which:65}));true")
            self._wait(
                "Array.from(document.querySelectorAll('.autocomplete-suggestion')).filter(e=>"
                "e.getClientRects().length && e.dataset.val===" + _js(search_text)
                + " && e.dataset.value?.split('|')[0]===" + _js(patient_id) + ").length===1"
            )
            self.browser.command("click", [
                '.autocomplete-suggestion[data-value^="' + patient_id + '|"]',
            ])
            self._wait(
                "(()=>{const id=String(apex.item('P41_ID_PACIENTE').getValue());"
                "const phone=String(apex.item('P41_TELEFONE_CELULAR').getValue()).replace(/\\D/g,'');"
                "return jQuery.active===0 && id===" + _js(patient_id)
                + " && (phone===" + _js(phone) + " || '55'+phone===" + _js(phone) + ")})()"
            )
        except Exception:
            raise NativeBookingError("patient_selection_unverified") from None
        return patient_id

    def _set_select(self, item: str, value: str) -> None:
        result = self._eval(
            f"(()=>{{const e=document.querySelector('#{item}');if(!e||e.tagName!=='SELECT'||"
            f"!Array.from(e.options).some(o=>o.value==={_js(value)}))return false;"
            f"apex.item('{item}').setValue({_js(value)});return apex.item('{item}').getValue()==={_js(value)}}})()"
        )
        if result is not True:
            raise NativeBookingError("form_option_unavailable")

    def _set_apex_item(self, item: str, value: str) -> None:
        result = self._eval(
            f"(()=>{{if(!document.querySelector('#{item}')||!apex.item('{item}'))return false;"
            f"apex.item('{item}').setValue({_js(value)});return String(apex.item('{item}').getValue())==={_js(value)}}})()"
        )
        if result is not True:
            raise NativeBookingError("form_value_unverified")

    def _read_form(self) -> dict[str, Any]:
        script = "(()=>{const ids=" + json.dumps(list(_FORM_FIELDS)) + ";"
        script += "if(ids.some(id=>!document.querySelector('#'+id)))return null;"
        script += "const v=id=>String(apex.item(id).getValue()||'');"
        script += "const date=v('P41_DATA_AGENDAR'),mode=v('P41_DURACAO_LIVRE');"
        script += "const time=mode==='S'?v('P41_HORARIO_LIVRE'):v('P41_HORARIO_AGENDAR');"
        script += "return {unit_id:v('P41_UNIDADE'),professional_id:v('P41_PROFISSIONAL_AGENDAR'),"
        script += "date,time,"
        script += "duration_min:v('P41_DURACAO'),type_id:v('P41_TIPO_AGENDAMENTO'),"
        script += "patient_id:v('P41_ID_PACIENTE'),agenda_id:document.querySelector('#P41_ID_AGENDA')?.value||''}})()"
        value = self._eval(script)
        if not isinstance(value, dict):
            raise NativeBookingError("appointment_form_changed")
        try:
            begin = datetime.strptime(f"{value['date']} {value['time']}", "%d/%m/%Y %H:%M").replace(tzinfo=SAO_PAULO)
            finish = begin + timedelta(minutes=int(value['duration_min']))
        except (ValueError, TypeError, KeyError):
            raise NativeBookingError("form_values_unverified") from None
        value["start"], value["end"] = begin.isoformat(), finish.isoformat()
        return value

    def _validate_form(self, form: dict[str, Any], request: dict[str, Any]) -> None:
        for key in ("unit_id", "professional_id", "type_id", "patient_id"):
            if str(form.get(key)) != str(request[key]):
                raise NativeBookingError("form_values_unverified")
        try:
            if int(form.get("duration_min")) != int(request["duration_min"]):
                raise NativeBookingError("form_values_unverified")
            start = datetime.fromisoformat(request["requested_start"]).astimezone(SAO_PAULO)
            end = datetime.fromisoformat(request["requested_end"]).astimezone(SAO_PAULO)
            form_start = datetime.strptime(f"{form['date']} {form['time']}", "%d/%m/%Y %H:%M").replace(tzinfo=SAO_PAULO)
        except (ValueError, TypeError, KeyError):
            raise NativeBookingError("form_values_unverified") from None
        form_end = form_start.replace() + (end - start)
        if form_start != start or form_end != end:
            raise NativeBookingError("form_values_unverified")

    def _validate_original_form(self, form: dict[str, Any], request: dict[str, Any]) -> None:
        if str(form.get("agenda_id")) != str(request["appointment_id"]):
            raise NativeBookingError("original_appointment_changed")
        for key in ("patient_id", "professional_id", "unit_id", "type_id"):
            request_key = "professional_id" if key == "professional_id" else key
            if str(form.get(key)) != str(request.get(request_key)):
                raise NativeBookingError("original_appointment_changed")
        if str(form.get("duration_min")) != str(request["duration_min"]):
            raise NativeBookingError("original_appointment_changed")
        if (not _same_time(form.get("start"), request["expected_start"])
                or not _same_time(form.get("end"), request["expected_end"])):
            raise NativeBookingError("original_appointment_changed")

    def _read_original(self, request: dict[str, Any]) -> dict[str, Any]:
        form = self._read_form()
        self._validate_original_form(form, request)
        return {
            "appointment_id": str(form["agenda_id"]),
            "patient_id": str(form["patient_id"]),
            "professional_id": str(form["professional_id"]),
            "unit_id": str(form["unit_id"]), "type_id": str(form["type_id"]),
            "procedure_id": str(request["procedure_id"]) if request.get("procedure_id") is not None else None,
            "duration_min": int(form["duration_min"]),
            "start": request["expected_start"], "end": request["expected_end"],
        }

    def _validate_target_rows(self, rows: list[dict[str, Any]], request: dict[str, Any]) -> None:
        for row in rows:
            if not isinstance(row, dict):
                raise NativeBookingError("duplicate_read_unverified")
            required = ("appointment_id", "patient_id", "professional_id", "unit_id", "type_id", "duration_min", "start", "end")
            if any(key not in row for key in required):
                raise NativeBookingError("duplicate_read_unverified")

    def _complete_rows(self, result: Any, request: dict[str, Any]) -> list[dict[str, Any]]:
        if (not isinstance(result, dict) or result.get("complete") is not True
                or result.get("clinic_id") != request["clinic_id"]
                or result.get("source_clinic_hash") != request["source_clinic_hash"]
                or not isinstance(result.get("rows"), list)):
            raise NativeBookingError("duplicate_read_unverified")
        rows = result["rows"]
        self._validate_target_rows(rows, request)
        return rows

    def _read_reconciliation_matches(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        # The adapter cannot safely interpret FullCalendar labels, which may
        # contain patient names and arbitrary HTML. A caller-provided reader
        # must click/open candidate events and return exact normalized rows.
        if not callable(self.target_reader):
            raise NativeBookingError("post_save_identity_unavailable")
        return self._complete_rows(self.target_reader(request), request)

    def _read_old_after_reload(self, request: dict[str, Any]) -> dict[str, Any]:
        # For reschedule, a fresh read must prove original identity/window and
        # explicitly that the original is inactive. The calendar feed does not
        # expose that contract reliably, so require a verified provider.
        reader = self.old_appointment_reader
        if not callable(reader):
            raise NativeBookingError("old_appointment_state_unavailable")
        row = reader(request)
        if not isinstance(row, dict):
            raise NativeBookingError("old_appointment_state_unavailable")
        required = {
            "old_appointment_id": str(request["appointment_id"]),
            "old_patient_id": str(request["patient_id"]),
            "old_professional_id": str(request["professional_id"]),
            "old_unit_id": str(request["unit_id"]),
            "old_type_id": str(request["type_id"]),
            "old_duration_min": int(request["duration_min"]),
            "old_start": request["expected_start"],
            "old_end": request["expected_end"],
            "old_appointment_active": False,
        }
        if request.get("procedure_id") is not None:
            required["old_procedure_id"] = str(request["procedure_id"])
        if any(row.get(key) != expected for key, expected in required.items()):
            raise NativeBookingError("old_appointment_state_unverified")
        return row

    def _eval(self, script: str) -> Any:
        try:
            return self.browser.evaluate(script)
        except Exception:
            raise NativeBookingError("browser_operation_failed") from None

    def _wait(self, script: str) -> Any:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            value = self._eval(script)
            if value:
                return value
            try:
                self.browser.command("wait", ["250"])
            except Exception:
                time.sleep(0.05)
        raise NativeBookingError("page_not_ready")

    @staticmethod
    def _same_request(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
        return isinstance(left, dict) and isinstance(right, dict) and left == right


def _js(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NativeBookingError("invalid_timestamp")
    return parsed.astimezone(SAO_PAULO)


def _same_time(left: Any, right: Any) -> bool:
    try:
        return _instant(str(left)) == _instant(str(right))
    except (ValueError, TypeError, NativeBookingError):
        return False
