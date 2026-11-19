---
name: edicao-de-cortes
description: Predefinição do Mauricio para editar cortes de live/stream (estilo viral ou estilo notícia com faixa branca de perfil), sempre com manchete-gancho tipo "ELE DESCOBRIU UM NOVO EASTER EGG NO GTA 6". Use quando ele pedir "cortes", "corta essa live", "faz uns cortes", "edita esse clipe", "tira os melhores momentos" ou mandar um vídeo/VOD de live. Entrega vertical 9:16 (1080x1920), até 60s, legenda palavra a palavra com destaque amarelo, áudio normalizado.
---

# Edição de cortes — predefinição

Há **dois estilos**. Use o **viral** por padrão; use o **notícia** quando o Mauricio pedir
"estilo notícia", "modelo da TNT", "estilo post", "com a faixa branca" ou "segunda opção".

| | Estilo 1 — `viral` (padrão) | Estilo 2 — `noticia` |
|---|---|---|
| Visual | vídeo em tela cheia, manchete em caixa preta no topo | faixa branca no topo com foto + nome + @ do perfil e a manchete em preto, vídeo ocupando o resto embaixo |
| Manchete | Anton, palavras-chave em amarelo | Montserrat ExtraBold, preta, alinhada à esquerda, até 4 linhas |
| Legenda | palavra a palavra, MAIÚSCULAS, destaque amarelo/verde | frase inteira, como foi falada, branca com contorno, palavras-chave em amarelo |
| Comando | `--estilo viral` (ou nada) | `--estilo noticia` |

Padrão fixo dos dois estilos (só mude se o Mauricio pedir):

| Item | Valor |
|---|---|
| Conteúdo | live / stream (facecam + jogo/tela) |
| Formato | vertical 9:16, 1080x1920, 30 fps, H.264 + AAC, `+faststart` |
| Duração | 15–60 s por corte (o script recusa > 60 s sem `--forcar`) |
| Manchete | **obrigatória em todo corte** — frase-gancho tipo notícia no topo ("ELE DESCOBRIU UM NOVO EASTER EGG NO GTA 6"), caixa preta, texto branco, palavras-chave em amarelo |
| Legenda | palavra a palavra, até 3 palavras por vez, MAIÚSCULAS, fonte Anton, branca com contorno preto, palavra falada em **amarelo** (#FFE500), palavras-chave do momento em **verde** (#39FF14) e maiores quando faladas, "pop" no início de cada grupo |
| Áudio | loudnorm −14 LUFS, pico −1 dBTP |
| Saída | pasta `cortes/` |

Tudo é feito com `cortes.py` (nesta pasta). Rode a partir da raiz do projeto:

```bash
C=.claude/skills/edicao-de-cortes/cortes.py
python3 $C setup                      # 1x por sessão
```

## Fluxo

1. **Pegar o vídeo.** Arquivo enviado na sessão, caminho local, ou link
   (`python3 $C baixar <url> [--trecho 1:20:00-1:35:00]`). Guarde brutos em `brutos/`.
   Se o download for bloqueado pela rede, peça para o Mauricio enviar o arquivo.

2. **Transcrever** (gera `<video>.palavras.json` e `<video>.transcricao.txt`):
   ```bash
   python3 $C transcrever brutos/live.mp4            # modelo small, pt
   python3 $C transcrever brutos/live.mp4 --inicio 1:20:00 --fim 1:40:00   # só um trecho
   ```
   Live longa (> 1 h): transcreva por trechos ou use `--modelo base` para ir mais rápido.
   Se o modelo não baixar (Hugging Face bloqueado), avise o Mauricio — sem transcrição
   não há legenda — e ofereça renderizar com `--sem-legenda` por enquanto.

3. **Achar os momentos.** Combine as duas fontes:
   - `python3 $C picos brutos/live.mp4` → trechos mais barulhentos (grito, hype, risada, raiva).
   - Leia o `.transcricao.txt` procurando: reação forte, jogada absurda, fail, briga/treta,
     piada com punchline, frase polêmica ou "citável", história curta com desfecho.
   Regras de um bom corte:
   - **Gancho nos 2 primeiros segundos** — comece na frase/ação mais forte, nunca em silêncio,
     "então...", ou contexto lento. O contexto vem da manchete (passo 3b).
   - **Termine no payoff** (reação, risada, resultado) — corte logo depois, sem cauda.
   - Comece/termine em limite de palavra: use os tempos do `.palavras.json`
     (início ≈ `s` da 1ª palavra − 0.15 s; fim ≈ `e` da última + 0.3 s).
   - Um assunto por corte. 20–45 s costuma performar melhor; 60 s é o teto.
   Apresente a lista de cortes propostos (tempo, duração, por que funciona, manchete)
   antes de renderizar, a não ser que ele tenha pedido para já entregar.

3b. **Escrever a manchete de cada corte (sempre).** Toda vez que achar um momento
   impactante, transforme-o numa manchete curta, como se fosse notícia, e coloque no
   topo do vídeo com `--titulo`. Exemplo do Mauricio:
   **"ELE DESCOBRIU UM NOVO \*EASTER EGG\* NO \*GTA 6\*"**.
   Como escrever:
   - Diga **o que aconteceu**, em 3ª pessoa: "ELE...", "O CHAT...", "O STREAMER...".
   - Seja **específico**: nome do jogo, item, valor, número, pessoa (GTA 6, R$ 50 MIL, 1 HP,
     TOP 1, 3 HORAS). Específico prende mais do que genérico ("OLHA ISSO").
   - Crie **curiosidade sem entregar o final**: a manchete promete, o vídeo paga.
     Bom: "ELE ACHOU UMA PASSAGEM SECRETA NO *GTA 6*". Ruim: "ELE ENTROU NA PASSAGEM E ACHOU UM CARRO".
   - Verbos fortes: DESCOBRIU, ACHOU, PERDEU, GANHOU, HUMILHOU, REVELOU, QUEBROU, NÃO ACREDITOU.
   - 4 a 10 palavras (até ~45 caracteres), MAIÚSCULAS, sem ponto final e sem emoji (a fonte não tem emoji; ponha emoji só na legenda do post).
   - Marque **1–2 palavras-chave** entre `*asteriscos*` → ficam em amarelo.
   - **Nunca mentir**: a manchete tem que ser verdade no que aparece no corte. Se não tiver
     certeza (ex: se é mesmo "novo"), use algo que o vídeo comprova ("ELE ACHOU UM *EASTER EGG* NO *GTA 6*").
   Mais modelos:
   - "ELE PERDEU *R$ 50 MIL* EM UMA ÚNICA APOSTA"
   - "O CHAT NÃO ACREDITOU NESSA JOGADA COM *1 HP*"
   - "ELE REVELOU O QUE ACHA DO *GTA 6*"
   - "ELE QUEBROU O TECLADO DEPOIS DESSA MORTE"

   **Manchete no estilo notícia:** mesmo princípio, mas descrevendo a cena, como post de
   portal de notícias, terminando em dois-pontos. Ex: "MBAPPÉ RESPONDENDO QUAL É O MELHOR
   'BOLA DE OURO' DA HISTÓRIA:" → "ELE DESCOBRINDO UM NOVO EASTER EGG NO GTA 6:",
   "A REAÇÃO DO CHAT QUANDO ELE ACHOU O EASTER EGG NO GTA 6:". Pode ser um pouco mais
   longa (até ~70 caracteres); `*asteriscos*` só colorem se `cor_destaque` estiver no perfil.

   **Palavras-chave na legenda:** passe as mesmas palavras do momento com
   `--destaques "easter egg,gta 6"` — elas aparecem em verde na legenda e crescem quando
   ele fala, reforçando a frase impactante.

4. **Definir o layout.** Tire um quadro e olhe a imagem:
   ```bash
   python3 $C frame brutos/live.mp4 1:23:10
   ```
   - Tem facecam → `--layout stream --cam x:y:w:h` (coordenadas da cam no vídeo
     original; cam fica em cima com 35% da altura, jogo embaixo, legenda na divisa).
     Ajuste `--jogo x:y:w:h` se o centro da tela não for a parte importante.
   - Sem facecam / tela cheia de jogo → `--layout blur` (vídeo inteiro no meio com fundo
     desfocado; título vai no espaço de cima).
   - Pessoa só falando (just chatting) → `--layout crop --foco 0.5` (0 = esquerda, 1 = direita).
   Use o mesmo layout/coordenadas para todos os cortes da mesma live.

5. **Renderizar.**
   ```bash
   python3 $C render brutos/live.mp4 --inicio 1:23:05.4 --fim 1:23:41 \
     --layout stream --cam 1460:690:440:370 \
     --titulo "ELE DESCOBRIU UM NOVO *EASTER EGG* NO *GTA 6*" --destaques "easter egg,gta 6" \
     --saida cortes/01-easter-egg-gta6.mp4
   ```
   Vários de uma vez com um JSON:
   ```json
   [
     {"nome": "01-easter-egg-gta6", "inicio": "1:23:05.4", "fim": "1:23:41",
      "titulo": "ELE DESCOBRIU UM NOVO *EASTER EGG* NO *GTA 6*", "destaques": ["easter egg", "gta 6"]},
     {"nome": "02-rage", "inicio": "2:10:12", "fim": "2:10:50",
      "titulo": "ELE QUEBROU O *TECLADO* DEPOIS DESSA MORTE", "destaques": ["teclado"]}
   ]
   ```
   ```bash
   python3 $C lote brutos/live.mp4 cortes.json --layout stream --cam 1460:690:440:370
   ```
   Estilo notícia (mesmos layouts; sem `--cam` o vídeo preenche a área de baixo):
   ```bash
   python3 $C render brutos/live.mp4 --inicio 1:23:05.4 --fim 1:23:41 --estilo noticia \
     --titulo "ELE DESCOBRINDO UM NOVO EASTER EGG NO GTA 6:" --destaques "easter egg,gta 6"
   ```
   No `lote`, cada corte pode ter `"estilo": "noticia"`.
   A faixa usa `perfil.json` (nesta pasta): `nome`, `usuario` (@), `foto` (caminho a partir
   da raiz do repo), `verificado` (selo azul — só `true` se a conta for verificada de verdade)
   e `cor_destaque` (ex: `"#E8112D"`, ou `null`). Perfil atual: página **Clip Five6** com o logo `logo-clip-five6.jpg`. Use sempre esse perfil, nunca
   nome/logo de outro canal ou marca.

   Opções úteis: `--legenda-y`, `--titulo-y` (no layout stream o título fica sobre a cam;
   se cobrir o rosto, mova com ex. `--titulo-y 1750`), `--tamanho` (padrão 110), `--palavras-por-vez`,
   `--fps 60` (jogo rápido), `--sem-legenda`.

6. **Conferir antes de entregar.** Para cada corte, tire 1–2 quadros do resultado
   (`python3 $C frame cortes/01-....mp4 2`) e verifique: cam/jogo bem enquadrados,
   legenda legível e sem cobrir rosto/HUD importante, gancho forte no início,
   manchete em no máximo 3 linhas e sem cobrir o rosto (se cobrir, use `--titulo-y`).
   Corrija nomes, gírias ou palavras erradas no `.palavras.json` antes de re-renderizar.

7. **Entregar.** Envie os MP4 com `SendUserFile` e, para cada corte, sugira:
   título/legenda do post, 3–5 hashtags e o melhor trecho para thumbnail/capa.

## Observações

- Vídeos, `.palavras.json` e `.transcricao.txt` ficam fora do git (`.gitignore`).
- Fonte Anton (SIL OFL) em `fontes/` — já vem no repositório, não precisa baixar.
- `CORTES_WHISPER_MODEL=/caminho/do/modelo` força um modelo local do faster-whisper.
