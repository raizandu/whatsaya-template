# Licenciamento e distribuição privada

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
fica em um único repositório privado controlado pela Raizandu. Cada cliente
recebe apenas uma instalação administrada na sua VPS.

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

## Acesso da VPS ao repositório privado

Privatizar o repositório exige preparar a autenticação antes. O bootstrap atual
clona por HTTPS sem credencial e deixará de receber atualizações quando o
repositório se tornar privado.

Para poucas instalações, use uma chave de deploy SSH exclusiva e somente leitura
por VPS. O cliente não recebe acesso ao GitHub; a chave privada permanece no
servidor e a chave pública é cadastrada no repositório. Nunca habilite escrita.

Quando houver mais instalações, prefira um GitHub App da Raizandu com permissão
somente de leitura de conteúdo e tokens de curta duração, ou um pipeline central
que envie releases para as VPSs. Isso facilita revogação, auditoria e rotação sem
vincular o deploy à conta pessoal de alguém.

## Sequência segura para tornar privado

1. Ajustar o bootstrap para clone autenticado sem gravar segredo na URL ou log.
2. Criar uma credencial somente leitura e exclusiva para cada VPS existente.
3. Testar `fetch` e um restart completo em cada instalação.
4. Confirmar backup dos dados persistentes e da sessão do WhatsApp.
5. Tornar o repositório privado.
6. Repetir o `fetch`, reiniciar e validar bridge, painel e conexão do WhatsApp.
7. Documentar como revogar uma VPS quando um contrato terminar.

Até essa sequência estar pronta, não altere a visibilidade: a instalação atual
conserva o código já clonado, mas seus updates automáticos falharão.
