# Publicar o painel, o QR e o dashboard com Cloudflare Tunnel

O objetivo é ter HTTPS e login de verdade **sem abrir porta nenhuma**. O conector
(`cloudflared`) faz uma conexão de saída para a Cloudflare; nada entra pela borda
do servidor. O Cloudflare Access fica na frente, então a autenticação acontece
antes de a requisição chegar ao serviço.

Por que não um proxy comum com Let's Encrypt: aqui a porta continuaria aberta, e
o dashboard e o painel hoje só têm basic auth. Com Access, quem não passou pelo
login nem alcança o processo.

## O que roda onde

| Hostname | Serviço local | O que é |
|---|---|---|
| `painel.SEU-DOMINIO` | `http://localhost:9120` | painel de operação |
| `qr.SEU-DOMINIO` | `http://localhost:80` | página de pareamento do WhatsApp |
| `hermes.SEU-DOMINIO` | `http://localhost:9119` | dashboard do Hermes |

`qr` é o mais sensível: quem abre a página e escaneia o código **pareia o
WhatsApp do cliente no próprio aparelho**. Nunca deixe essa rota sem Access.

## 1. Pré-requisitos

O domínio precisa estar na Cloudflare com os nameservers dela (Websites → Add a
domain). O conector já está instalado na VPS:

```bash
ssh <host> 'cloudflared --version'
```

Se faltar, é o repositório apt da Cloudflare:

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install cloudflared
```

## 2. Criar o túnel (painel da Cloudflare)

Túnel gerenciado remotamente, que é o padrão recomendado para instalação nova: a
configuração fica no painel da Cloudflare, não em arquivo no servidor.

1. Zero Trust → **Networks → Tunnels → Create a tunnel** → **Cloudflared**.
2. Nome sugerido: `whatsaya-<cliente>`.
3. A tela mostra o comando de instalação com um token `eyJ...`. **O token é
   credencial**: não cole em chat nem em commit. Rode direto na VPS:

   ```bash
   ssh <host>
   sudo cloudflared service install <TOKEN>
   systemctl status cloudflared    # deve ficar active (running)
   ```

4. Ainda no túnel, aba **Published application routes**, adicione as três rotas
   da tabela acima. Em cada uma: subdomínio, domínio, tipo **HTTP**, e a URL
   local (`localhost:9120`, `localhost:80`, `localhost:9119`). O registro DNS é
   criado sozinho.

Teste antes de seguir: `https://painel.SEU-DOMINIO` tem que pedir a senha do
dashboard (o basic auth do próprio painel).

## 3. Access na frente (é o que substitui a senha em texto claro)

Para cada um dos três hostnames, Zero Trust → **Access → Applications → Add an
application → Self-hosted**:

- **Application domain**: o hostname.
- **Policy**: `Allow`, com o seletor **Emails** e os endereços que podem entrar.
- **Login method**: One-time PIN serve, e não precisa de provedor de identidade.
  A Cloudflare manda um código para o e-mail a cada login.

Access é *default-deny*: uma aplicação sem política de Allow bloqueia todo mundo,
inclusive você. Teste numa janela anônima antes de fechar as portas.

## 4. Fechar as portas (só depois que o túnel estiver funcionando)

Com o túnel no ar, nada precisa mais escutar na borda.

No `deploy/docker-compose.yml`, prefixe as publicações com o loopback:

```yaml
    ports:
      - "127.0.0.1:9119:9119"
      - "127.0.0.1:9120:9120"
```

E aplique:

```bash
cd /opt/whatsaya && docker compose up -d
```

A página de QR já escuta só em `127.0.0.1` (ver `whatsaya-qr.service`).

Confirme de fora que fechou, do seu computador:

```bash
curl -sS -m 5 http://<ip-público>:9120/    # tem que falhar a conexão
curl -sS -m 5 http://<ip-público>:9119/    # tem que falhar a conexão
curl -sS -m 5 http://<ip-público>/         # tem que falhar a conexão
curl -sSI https://painel.SEU-DOMINIO       # tem que responder pelo Access
```

## Manutenção

- Atualizar o conector: `sudo apt-get update && sudo apt-get install --only-upgrade cloudflared && sudo systemctl restart cloudflared`.
- Trocar o token (se vazar): Zero Trust → o túnel → **Refresh token**, depois
  `sudo cloudflared service uninstall && sudo cloudflared service install <NOVO>`.
- Ver o que passou: Zero Trust → **Logs → Access** mostra quem autenticou em qual
  aplicação; `journalctl -u cloudflared -n 50` mostra o lado do servidor.

## Sinais de problema

| Sintoma | Onde olhar |
|---|---|
| Hostname dá 502 | rota apontando para porta errada, ou serviço local caído (`curl localhost:<porta>` na VPS) |
| Hostname dá 1033 | o túnel não está conectado: `systemctl status cloudflared` |
| Access não aparece | a aplicação não cobre exatamente esse hostname |
| Entra sem pedir login | falta a aplicação Access nesse hostname, ou a política é mais aberta do que você pensa |
