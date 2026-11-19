---
name: edicao-de-cortes
description: Predefinição do Mauricio para editar cortes de live/stream. Use quando ele pedir "cortes", "corta essa live", "faz uns cortes", "edita esse clipe", "tira os melhores momentos" ou mandar um vídeo/VOD de live. Entrega vertical 9:16 (1080x1920), até 60s, legenda palavra a palavra com destaque amarelo, áudio normalizado.
---

# Edição de cortes — predefinição

Padrão fixo (só mude se o Mauricio pedir):

| Item | Valor |
|---|---|
| Conteúdo | live / stream (facecam + jogo/tela) |
| Formato | vertical 9:16, 1080x1920, 30 fps, H.264 + AAC, `+faststart` |
| Duração | 15–60 s por corte (o script recusa > 60 s sem `--forcar`) |
| Legenda | palavra a palavra, até 3 palavras por vez, MAIÚSCULAS, fonte Anton, branca com contorno preto, palavra falada em **amarelo** (#FFE500), "pop" no início de cada grupo |
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
     "então...", ou contexto lento. Se precisar de contexto, use o `--titulo`.
   - **Termine no payoff** (reação, risada, resultado) — corte logo depois, sem cauda.
   - Comece/termine em limite de palavra: use os tempos do `.palavras.json`
     (início ≈ `s` da 1ª palavra − 0.15 s; fim ≈ `e` da última + 0.3 s).
   - Um assunto por corte. 20–45 s costuma performar melhor; 60 s é o teto.
   Apresente a lista de cortes propostos (tempo, duração, por que funciona, título-gancho)
   antes de renderizar, a não ser que ele tenha pedido para já entregar.

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
     --layout stream --cam 1460:690:440:370 --titulo "ELE NÃO ACREDITOU" \
     --saida cortes/01-jogada-absurda.mp4
   ```
   Vários de uma vez com um JSON:
   ```json
   [
     {"nome": "01-jogada-absurda", "inicio": "1:23:05.4", "fim": "1:23:41", "titulo": "ELE NÃO ACREDITOU"},
     {"nome": "02-rage", "inicio": "2:10:12", "fim": "2:10:50"}
   ]
   ```
   ```bash
   python3 $C lote brutos/live.mp4 cortes.json --layout stream --cam 1460:690:440:370
   ```
   Opções úteis: `--legenda-y`, `--titulo-y` (no layout stream o título fica sobre a cam;
   se cobrir o rosto, mova com ex. `--titulo-y 1750`), `--tamanho` (padrão 110), `--palavras-por-vez`,
   `--fps 60` (jogo rápido), `--sem-legenda`.

6. **Conferir antes de entregar.** Para cada corte, tire 1–2 quadros do resultado
   (`python3 $C frame cortes/01-....mp4 2`) e verifique: cam/jogo bem enquadrados,
   legenda legível e sem cobrir rosto/HUD importante, gancho forte no início.
   Corrija nomes, gírias ou palavras erradas no `.palavras.json` antes de re-renderizar.

7. **Entregar.** Envie os MP4 com `SendUserFile` e, para cada corte, sugira:
   título/legenda do post, 3–5 hashtags e o melhor trecho para thumbnail/capa.

## Observações

- Vídeos, `.palavras.json` e `.transcricao.txt` ficam fora do git (`.gitignore`).
- Fonte Anton (SIL OFL) em `fontes/` — já vem no repositório, não precisa baixar.
- `CORTES_WHISPER_MODEL=/caminho/do/modelo` força um modelo local do faster-whisper.
