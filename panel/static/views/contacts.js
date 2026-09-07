import { useState } from 'preact/hooks';
import { html, useApi, post, fmt, Card, ErrorBox, Empty } from '../lib.js';

export default function Contacts({ setToast }) {
  const data = useApi('/api/blocked', { every: 30000 });
  const [query, setQuery] = useState('');
  const d = data.data;

  const block = async (target) => {
    try {
      await post('/api/actions/block', target);
      setToast(`Bloqueado: ${target.name || target.query}`);
      setQuery('');
      data.reload();
    } catch (err) {
      setToast(`Não bloqueei: ${err.message}`);
    }
  };
  const unblock = async (c) => {
    try {
      await post('/api/actions/unblock', { chat_id: c.chat_id });
      setToast(`${c.name} liberado. A conversa anterior da IA será arquivada.`);
      data.reload();
    } catch (err) {
      setToast(`Não desbloqueei: ${err.message}`);
    }
  };

  return html`
    <${ErrorBox} error=${data.error}/>
    <div class="grid start" style="grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr)">
      <${Card} title="Contatos bloqueados" sub=${html`A ponte descarta a mensagem na entrada: sem visto, sem "digitando", sem IA. Equivale ao comando <span class="code">bloquear</span> no chat do dono.`}>
        <form class="form-row" onSubmit=${(e) => { e.preventDefault(); if (query.trim()) block({ query: query.trim() }); }}>
          <input class="input" value=${query} onInput=${(e) => setQuery(e.target.value)} placeholder="Número ou nome do contato"/>
          <button class="btn lg primary" type="submit">Bloquear</button>
        </form>
        ${d && d.blocked.length === 0 ? html`<${Empty}>Nenhum contato bloqueado. A AYA responde todo mundo.</${Empty}>` : null}
        <div class="row-list">${d ? d.blocked.map((c) => html`<div class="item" key=${c.chat_id}>
          <span class="avatar">${fmt.initials(c.name)}</span>
          <div class="grow"><span class="name">${c.name}</span><span class="meta">${c.phone} · ${c.reason}</span></div>
          <button class="btn" onClick=${() => unblock(c)}>Desbloquear</button>
        </div>`) : null}</div>
      </${Card}>
      <${Card} title="Conversas recentes" sub="Quem falou com a AYA nas últimas 24 h">
        ${d && d.recent.length === 0 ? html`<${Empty}>Nenhuma conversa nas últimas 24 h.</${Empty}>` : null}
        <div class="row-list">${d ? d.recent.map((c) => html`<div class="item" key=${c.chat_id} style="padding:11px 0">
          <span class="avatar mint">${fmt.initials(c.name)}</span>
          <div class="grow"><span class="name">${c.name}</span><span class="meta">${c.phone} · ${c.inbound} mensagem(ns)</span></div>
          <button class="btn sm" style="height:36px" onClick=${() => block({ chat_id: c.chat_id, name: c.name })}>Bloquear</button>
        </div>`) : null}</div>
      </${Card}>
    </div>`;
}
