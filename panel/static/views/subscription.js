import { html, fmt, Card } from '../lib.js';

export default function Subscription({ config }) {
  const subscription = config && config.subscription;
  const included = subscription ? subscription.included : [];
  const price = subscription && subscription.price_brl !== null
    ? fmt.brl(subscription.price_brl)
    : 'Consulte sua proposta';

  return html`<div class="subscription-grid">
    <section class="card subscription-summary dark">
      <span class="eyebrow">Plano atual</span>
      <h2>${subscription ? subscription.name : 'Plano Therapify'}</h2>
      <strong>${price}</strong>
      <span>${subscription ? subscription.billing : 'mensal'}</span>
      <p>A mensalidade reúne os recursos contratados para acompanhar e operar o atendimento.</p>
    </section>
    <${Card} title="O que está incluído" sub="Recursos contemplados nesta instalação">
      <div class="subscription-included">
        ${included.map((item) => html`<div class="included-item" key=${item}><span aria-hidden="true">✓</span><b>${item}</b></div>`)}
      </div>
    </${Card}>
  </div>`;
}
