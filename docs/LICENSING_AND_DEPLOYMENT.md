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

## Um repositório, várias instalações

Clientes não precisam de conta nem de repositório GitHub. O código do produto
fica em um único repositório público controlado pela Raizandu, mas continua
proprietário sob os termos de `LICENSE`. Cada cliente recebe apenas uma
instalação administrada na sua VPS.

Separe as mudanças assim:

| Tipo de mudança | Fonte da verdade |
|---|---|
| Código reutilizável do produto | branch `template` |
| Operação e gestão próprias da WhatsAYA | branch `main` |
| Opção específica de um cliente | configuração ou feature flag versionada no produto |
| Persona, catálogo, credenciais e dados do cliente | volume persistente da VPS, fora do repositório de código |

Evite branches permanentes por cliente e não edite código diretamente na VPS.
O bootstrap atual atualiza o clone e pode executar `reset --hard`; um patch local
pode desaparecer no próximo restart. Se uma necessidade for específica, modele
uma configuração ou um módulo opcional no repositório e ative-o somente naquela
instalação.

## Repositório público proprietário

O bootstrap das VPSs clona e atualiza o repositório público por HTTPS, sem token,
chave SSH ou conta do cliente. Esse é o fluxo oficial enquanto a visibilidade
permanecer pública.

“Público” descreve quem consegue ler o código; não significa “open source”. A
licença proprietária não autoriza executar, implantar, modificar, redistribuir ou
explorar comercialmente o produto. Ainda assim, a exposição pública permite que
terceiros vejam e façam fork dentro do GitHub, e a licença é uma proteção jurídica,
não uma barreira técnica contra cópias indevidas.

Se confidencialidade do código se tornar requisito no futuro, será necessário
migrar primeiro o bootstrap para deploy autenticado ou para um pipeline central.
Até lá, manter público evita distribuir credenciais do GitHub entre as VPSs.
