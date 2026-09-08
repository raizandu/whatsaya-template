# Licenciamento e distribuição

Este documento descreve a política técnica do produto. Não substitui a revisão
de um advogado nem o contrato comercial entre as partes.

## Propriedade e contrato

- O titular indicado em `LICENSE` é Anthony Fleuri (Raizandu).
- O WhatsAYA é proprietário e não é open source.
- A licença do repositório proíbe uso e exploração sem autorização escrita.
- Sociedade, participação de 50%, divisão de receita ou lucro e atuação
  comercial devem constar em contrato assinado. A licença não cria sociedade.
- Contribuições externas só devem ser incorporadas depois de cessão ou licença
  escrita de propriedade intelectual.

## Dois repositórios, várias instalações

Clientes não precisam de conta nem de repositório GitHub. A fonte interna fica
no repositório privado `raizandu/whatsaya`. A distribuição sanitizada fica no
repositório público `raizandu/whatsaya-template`, com histórico independente e
licença proprietária. Cada cliente recebe apenas uma instalação administrada na
sua VPS.

Separe as mudanças assim:

| Tipo de mudança | Fonte da verdade |
|---|---|
| Fonte interna e operação própria da WhatsAYA | repositório privado `raizandu/whatsaya` |
| Código genérico distribuível | repositório público `raizandu/whatsaya-template` |
| Opção específica de um cliente | configuração ou feature flag versionada no produto |
| Persona, catálogo, credenciais e dados do cliente | volume persistente da VPS, fora do repositório de código |

Evite branches permanentes por cliente e não edite código diretamente na VPS.
O bootstrap atual atualiza o clone e pode executar `reset --hard`; um patch local
pode desaparecer no próximo restart. Se uma necessidade for específica, modele
uma configuração ou um módulo opcional no repositório e ative-o somente naquela
instalação.

## Distribuição pública proprietária

O bootstrap das VPSs clona e atualiza `whatsaya-template` por HTTPS, sem token,
chave SSH ou conta do cliente. O repositório privado nunca é clonado numa VPS de
cliente. Cada publicação pública deve ser um snapshot sanitizado, sem herdar o
histórico da fonte privada.

“Público” descreve quem consegue ler o código; não significa “open source”. A
licença proprietária não autoriza executar, implantar, modificar, redistribuir ou
explorar comercialmente o produto. Ainda assim, a exposição pública permite que
terceiros vejam e façam fork dentro do GitHub, e a licença é uma proteção jurídica,
não uma barreira técnica contra cópias indevidas.

Se confidencialidade do código distribuído se tornar requisito no futuro, será
necessário migrar o bootstrap para um pipeline central. Até lá, manter somente o
snapshot genérico público evita distribuir credenciais do GitHub entre as VPSs.
