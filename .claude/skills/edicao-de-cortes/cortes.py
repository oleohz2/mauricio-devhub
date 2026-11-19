#!/usr/bin/env python3
"""Predefinição de edição de cortes de live/stream.

Saída padrão: vertical 1080x1920 (9:16), até 60 s, legenda palavra a palavra
com a palavra falada em destaque, áudio normalizado para redes (-14 LUFS).

Subcomandos:
  setup        instala dependências (faster-whisper, yt-dlp)
  baixar       baixa um VOD/clipe (Twitch, YouTube...) com yt-dlp
  transcrever  gera <video>.palavras.json e <video>.transcricao.txt
  picos        lista os trechos mais barulhentos (gritos, hype, risada)
  frame        salva um quadro do vídeo em PNG (para ver o layout/facecam)
  render       renderiza um corte
  lote         renderiza vários cortes a partir de um JSON
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
FONTES = AQUI / "fontes"
FONTE = "Anton"

W, H = 1080, 1920
DURACAO_MAX = 60.0

# Cores ASS no formato &HAABBGGRR
BRANCO = "&H00FFFFFF"
AMARELO = "&H0000E5FF"  # amarelo forte (#FFE500)
PRETO = "&H00000000"
VERDE = "&H0014FF39"  # verde neon (#39FF14) para palavras-chave


# ----------------------------------------------------------------- utilidades

def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def tempo(txt: str | float) -> float:
    """Aceita '83', '83.5', '1:23', '1:02:03.5'."""
    if isinstance(txt, (int, float)):
        return float(txt)
    partes = [float(p) for p in str(txt).strip().split(":")]
    seg = 0.0
    for p in partes:
        seg = seg * 60 + p
    return seg


def hms(seg: float) -> str:
    h, r = divmod(seg, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}" if h else f"{int(m)}:{s:05.2f}"


def ass_tempo(seg: float) -> str:
    seg = max(0.0, seg)
    cs = int(round(seg * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def info(video: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(video)],
        check=True, capture_output=True, text=True,
    ).stdout
    d = json.loads(out)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    tem_audio = any(s["codec_type"] == "audio" for s in d["streams"])
    return {
        "w": int(v["width"]),
        "h": int(v["height"]),
        "dur": float(d["format"].get("duration", 0)),
        "audio": tem_audio,
    }


def arquivo_palavras(video: Path) -> Path:
    return video.with_suffix(".palavras.json")


def regiao(txt: str | None) -> tuple[int, int, int, int] | None:
    """'x:y:w:h' em pixels do vídeo original."""
    if not txt:
        return None
    x, y, w, h = (int(float(v)) for v in txt.split(":"))
    return x, y, w, h


# ---------------------------------------------------------------------- setup

def cmd_setup(_a):
    pkgs = []
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        pkgs.append("faster-whisper")
    if not shutil.which("yt-dlp"):
        pkgs.append("yt-dlp")
    try:
        import PIL  # noqa: F401
    except ImportError:
        pkgs.append("pillow")
    if pkgs:
        run([sys.executable, "-m", "pip", "install", "-q", *pkgs])
    for b in ("ffmpeg", "ffprobe"):
        if not shutil.which(b):
            sys.exit(f"ERRO: {b} não encontrado. Instale com: apt-get install -y ffmpeg")
    print("ok: ffmpeg, faster-whisper, yt-dlp, pillow prontos")


# --------------------------------------------------------------------- baixar

def cmd_baixar(a):
    destino = Path(a.pasta)
    destino.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
        "--merge-output-format", "mp4",
        "-o", str(destino / "%(title).80s [%(id)s].%(ext)s"),
    ]
    if a.trecho:
        ini, fim = a.trecho.split("-")
        cmd += ["--download-sections", f"*{ini}-{fim}", "--force-keyframes-at-cuts"]
    run(cmd + [a.url])


# ---------------------------------------------------------------- transcrever

def cmd_transcrever(a):
    from faster_whisper import WhisperModel

    video = Path(a.video)
    modelo = os.environ.get("CORTES_WHISPER_MODEL", a.modelo)
    print(f"carregando modelo '{modelo}'...", file=sys.stderr)
    m = WhisperModel(modelo, device="cpu", compute_type="int8")
    kw = dict(language=a.idioma, word_timestamps=True, vad_filter=True,
              beam_size=5, condition_on_previous_text=False)
    if a.inicio is not None or a.fim is not None:
        kw["clip_timestamps"] = [tempo(a.inicio or 0), tempo(a.fim)] if a.fim else [tempo(a.inicio or 0)]
    segs, _ = m.transcribe(str(video), **kw)

    palavras, linhas = [], []
    for s in segs:
        linhas.append(f"[{hms(s.start)} → {hms(s.end)}] {s.text.strip()}")
        print(linhas[-1], file=sys.stderr)
        for w in s.words or []:
            palavras.append({"w": w.word.strip(), "s": round(w.start, 3),
                             "e": round(w.end, 3), "p": round(w.probability, 3)})

    arquivo_palavras(video).write_text(json.dumps(palavras, ensure_ascii=False), encoding="utf-8")
    video.with_suffix(".transcricao.txt").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"ok: {len(palavras)} palavras -> {arquivo_palavras(video)}")
    print(f"ok: transcrição -> {video.with_suffix('.transcricao.txt')}")


# ---------------------------------------------------------------------- picos

def cmd_picos(a):
    """Volume por segundo (RMS) e lista as janelas mais altas."""
    import array

    video = Path(a.video)
    taxa = 8000
    proc = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video), "-vn",
         "-ac", "1", "-ar", str(taxa), "-f", "s16le", "-"],
        stdout=subprocess.PIPE,
    )
    rms = []
    while True:
        bloco = proc.stdout.read(taxa * 2)  # 1 segundo
        if len(bloco) < 2:
            break
        amostras = array.array("h", bloco[: len(bloco) // 2 * 2])
        energia = sum(x * x for x in amostras) / len(amostras)
        rms.append(10 * math.log10(energia / 32768**2) if energia > 0 else -90.0)
    proc.wait()
    if not rms:
        sys.exit("não consegui medir o áudio (vídeo sem áudio?)")
    jan = max(1, int(a.janela))
    medias = [sum(rms[i:i + jan]) / len(rms[i:i + jan]) for i in range(0, len(rms))]
    base = sorted(rms)[len(rms) // 2]
    ordem = sorted(range(len(medias)), key=lambda i: medias[i], reverse=True)
    escolhidos: list[int] = []
    for i in ordem:
        if all(abs(i - j) >= a.distancia for j in escolhidos):
            escolhidos.append(i)
        if len(escolhidos) >= a.top:
            break
    print(f"volume mediano: {base:.1f} dB  (janela {jan}s)")
    for i in sorted(escolhidos):
        print(f"{hms(i)}  → {hms(i + jan)}   {medias[i]:6.1f} dB  (+{medias[i] - base:.1f} dB acima da mediana)")


# ---------------------------------------------------------------------- frame

def cmd_frame(a):
    video = Path(a.video)
    saida = Path(a.saida or video.with_name(f"{video.stem}_frame_{int(tempo(a.tempo))}s.png"))
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(tempo(a.tempo)), "-i", str(video),
         "-frames:v", "1", str(saida)])
    i = info(video)
    print(f"ok: {saida}  (vídeo original {i['w']}x{i['h']}, {hms(i['dur'])})")


# ------------------------------------------------------------------- legendas

def agrupar(palavras: list[dict], max_palavras: int, max_dur: float = 1.4, pausa: float = 0.45):
    grupos, atual = [], []
    for w in palavras:
        if atual:
            ini = atual[0]["s"]
            quebra = (
                len(atual) >= max_palavras
                or w["s"] - atual[-1]["e"] > pausa
                or w["e"] - ini > max_dur
                or re.search(r"[.!?,;:…]$", atual[-1]["w"])
            )
            if quebra:
                grupos.append(atual)
                atual = []
        atual.append(w)
    if atual:
        grupos.append(atual)
    return grupos


def limpar(txt: str) -> str:
    txt = txt.replace("{", "(").replace("}", ")").replace("\\", "/")
    return txt.upper()


def normalizar(txt: str) -> str:
    return re.sub(r"[^\w]", "", txt.lower())


def lista_destaques(destaques) -> set[str]:
    if not destaques:
        return set()
    if isinstance(destaques, str):
        destaques = destaques.split(",")
    return {normalizar(p) for d in destaques for p in d.split() if normalizar(p)}


def equilibrar(tokens: list, max_chars: int) -> list[list]:
    """Quebra em poucas linhas de tamanho parecido (evita palavra sozinha no fim)."""
    from itertools import combinations

    n = len(tokens)
    tam = lambda ts: sum(len(w) for w, _ in ts) + max(0, len(ts) - 1)
    for k in range(1, min(4, n) + 1):
        melhor = None
        for cortes in combinations(range(1, n), k - 1):
            idx = (0, *cortes, n)
            ls = [tokens[idx[i]:idx[i + 1]] for i in range(k)]
            pior = max(tam(l) for l in ls)
            if melhor is None or pior < melhor[0]:
                melhor = (pior, ls)
        if melhor and melhor[0] <= max_chars:
            return melhor[1]
    return melhor[1] if melhor else [tokens]


def titulo_ass(titulo: str, max_chars: int = 22) -> str:
    """Manchete em até 3 linhas; trechos entre *asteriscos* ficam em amarelo."""
    tokens, destaque = [], False
    for parte in re.split(r"(\*)", titulo):
        if parte == "*":
            destaque = not destaque
            continue
        if destaque and parte.strip():
            tokens.append((limpar(parte.strip()), True))  # destaque não quebra no meio
            continue
        for w in parte.split():
            tokens.append((limpar(w), destaque))
    linhas = equilibrar(tokens, max_chars)
    fmt = lambda w, d: f"{{\\c{AMARELO}}}{w}{{\\c{BRANCO}}}" if d else w
    return "\\N".join(" ".join(fmt(w, d) for w, d in l) for l in linhas)


def gerar_ass(palavras: list[dict], inicio: float, fim: float, legenda_y: int,
              tamanho: int, max_palavras: int, titulo: str | None, titulo_y: int,
              destaques=None, legenda_estilo: str = "viral") -> str:
    chaves = lista_destaques(destaques)
    dur = fim - inicio
    ws = []
    for w in palavras:
        if w["e"] <= inicio or w["s"] >= fim or not w["w"]:
            continue
        ws.append({"w": w["w"], "s": max(0.0, w["s"] - inicio), "e": min(dur, w["e"] - inicio)})

    linhas = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {W}",
        f"PlayResY: {H}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Legenda,{FONTE},{tamanho},{BRANCO},{BRANCO},{PRETO},&H96000000,0,0,0,0,100,100,1,0,1,7,4,5,60,60,0,1",
        f"Style: Simples,Montserrat,{round(tamanho * 0.56)},{BRANCO},{BRANCO},&H20000000,&H80000000,1,0,0,0,100,100,0,0,1,4,3,5,70,70,0,1",
        f"Style: Titulo,{FONTE},80,{BRANCO},{BRANCO},&H1A000000,&H00000000,0,0,0,0,100,100,1,0,3,20,0,5,60,60,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    if titulo:
        linhas.append(
            f"Dialogue: 1,{ass_tempo(0)},{ass_tempo(dur)},Titulo,,0,0,0,,"
            f"{{\\pos({W // 2},{titulo_y})\\fscx70\\fscy70\\t(0,160,\\fscx100\\fscy100)}}"
            f"{titulo_ass(titulo)}"
        )

    if legenda_estilo == "simples":
        # Frase inteira por vez, como foi falada (sem caixa alta), palavras-chave em amarelo
        grupos = agrupar(ws, max(6, max_palavras), max_dur=2.6, pausa=0.6)
        for n, g in enumerate(grupos):
            fim_g = g[-1]["e"] + 0.2
            if n + 1 < len(grupos):
                fim_g = min(fim_g, grupos[n + 1][0]["s"])
            limpo = lambda t: t.replace("{", "(").replace("}", ")").replace("\\", "/")
            txt = " ".join(
                f"{{\\c{AMARELO}}}{limpo(x['w'])}{{\\c{BRANCO}}}" if normalizar(x["w"]) in chaves
                else limpo(x["w"])
                for x in g
            )
            linhas.append(
                f"Dialogue: 0,{ass_tempo(g[0]['s'])},{ass_tempo(fim_g)},Simples,,0,0,0,,"
                f"{{\\pos({W // 2},{legenda_y})}}{txt}"
            )
        return "\n".join(linhas) + "\n"

    for g in agrupar(ws, max_palavras):
        g_fim = g[-1]["e"] + 0.15
        for i, w in enumerate(g):
            ini = w["s"]
            fim_w = g[i + 1]["s"] if i + 1 < len(g) else g_fim
            if fim_w - ini < 0.04:
                continue
            partes = []
            for j, x in enumerate(g):
                t = limpar(x["w"])
                chave = normalizar(x["w"]) in chaves
                if chave and j == i:
                    t = f"{{\\c{VERDE}\\fscx118\\fscy118}}{t}{{\\c{BRANCO}\\fscx100\\fscy100}}"
                elif chave:
                    t = f"{{\\c{VERDE}}}{t}{{\\c{BRANCO}}}"
                elif j == i:
                    t = f"{{\\c{AMARELO}}}{t}{{\\c{BRANCO}}}"
                partes.append(t)
            pop = "\\fscx85\\fscy85\\t(0,90,\\fscx100\\fscy100)" if i == 0 else ""
            linhas.append(
                f"Dialogue: 0,{ass_tempo(ini)},{ass_tempo(fim_w)},Legenda,,0,0,0,,"
                f"{{\\pos({W // 2},{legenda_y}){pop}}}{' '.join(partes)}"
            )
    return "\n".join(linhas) + "\n"


# ------------------------------------------------------ cabeçalho "notícia"

RAIZ = AQUI.parents[2]  # raiz do repositório


def carregar_perfil(caminho: str | None) -> dict:
    p = Path(caminho) if caminho else AQUI / "perfil.json"
    perfil = {"nome": "Seu Nome", "usuario": "", "foto": "", "verificado": False, "cor_destaque": None}
    if p.exists():
        perfil.update(json.loads(p.read_text(encoding="utf-8")))
    return perfil


def gerar_cabecalho(titulo: str, perfil: dict, saida: Path) -> int:
    """Faixa branca com foto, nome, @ e a manchete. Salva PNG e retorna a altura."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    MARGEM, TOPO, FOTO = 48, 120, 124
    PRETO_TXT, CINZA = (15, 20, 25), (83, 100, 113)
    destaque = perfil.get("cor_destaque") or None
    f_nome = ImageFont.truetype(str(FONTES / "Montserrat-Bold.ttf"), 46)
    f_user = ImageFont.truetype(str(FONTES / "Montserrat-Medium.ttf"), 38)

    # Manchete: quebra pela largura real do texto; diminui a fonte se passar de 4 linhas
    tokens, d = [], False
    for parte in re.split(r"(\*)", titulo):
        if parte == "*":
            d = not d
            continue
        tokens += [(w.upper(), d) for w in parte.split()]
    colados = []
    for w, dd in tokens:
        if colados and (len(colados[-1][0]) <= 2 or re.fullmatch(r"[\d.,R$%]+", colados[-1][0])) \
                and colados[-1][1] == dd and " " not in colados[-1][0][-3:]:
            colados[-1] = (colados[-1][0] + "\u00a0" + w, dd)
        else:
            colados.append((w, dd))
    tokens = colados
    largura = W - 2 * MARGEM
    for tam in (72, 68, 64, 60, 56, 52):
        f_tit = ImageFont.truetype(str(FONTES / "Montserrat-ExtraBold.ttf"), tam)
        espaco = f_tit.getlength(" ")
        linhas, atual, larg = [], [], 0.0
        for w, dd in tokens:
            lw = f_tit.getlength(w)
            if atual and larg + espaco + lw > largura:
                linhas.append(atual)
                atual, larg = [], 0.0
            larg += (espaco if atual else 0) + lw
            atual.append((w, dd, lw))
        if atual:
            linhas.append(atual)
        if len(linhas) <= 4:
            break
    passo = round(tam * 1.12)
    y_tit = TOPO + FOTO + 44
    altura = y_tit + passo * len(linhas) + 44
    altura += altura % 2

    img = Image.new("RGB", (W, altura), "white")
    dr = ImageDraw.Draw(img)

    foto = perfil.get("foto")
    caminho_foto = next((c for c in (Path(foto), RAIZ / foto, AQUI / foto) if foto and c.is_file()), None)
    if caminho_foto:
        av = ImageOps.fit(Image.open(caminho_foto).convert("RGB"), (FOTO * 4, FOTO * 4))
        mask = Image.new("L", av.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, *av.size), fill=255)
        av = av.resize((FOTO, FOTO), Image.LANCZOS)
        img.paste(av, (MARGEM, TOPO), mask.resize((FOTO, FOTO), Image.LANCZOS))
        dr.ellipse((MARGEM, TOPO, MARGEM + FOTO, TOPO + FOTO), outline=(225, 232, 237), width=2)
    else:
        dr.ellipse((MARGEM, TOPO, MARGEM + FOTO, TOPO + FOTO), fill=(220, 220, 220))

    x_txt = MARGEM + FOTO + 26
    tem_user = bool(perfil.get("usuario"))
    y_nome = TOPO + (14 if tem_user else 36)
    dr.text((x_txt, y_nome), perfil["nome"], font=f_nome, fill=PRETO_TXT)
    if perfil.get("verificado"):
        r, cx = 20, x_txt + f_nome.getlength(perfil["nome"]) + 14 + 20
        cy = y_nome + 30
        dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(29, 155, 240))
        dr.line([(cx - 9, cy + 1), (cx - 2, cy + 8), (cx + 10, cy - 7)], fill="white", width=5, joint="curve")
    if tem_user:
        u = perfil["usuario"]
        dr.text((x_txt, TOPO + 72), u if u.startswith("@") else "@" + u, font=f_user, fill=CINZA)

    for i, linha in enumerate(linhas):
        x = MARGEM
        for w, dd, lw in linha:
            dr.text((x, y_tit + i * passo), w, font=f_tit, fill=(destaque if dd and destaque else PRETO_TXT))
            x += lw + espaco
    img.save(saida)
    return altura


# --------------------------------------------------------------------- layout

def preencher(rotulo_in: str, rotulo_out: str, w: int, h: int) -> str:
    """Escala cobrindo a área e corta o excesso no centro."""
    return (f"[{rotulo_in}]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1[{rotulo_out}]")


def filtro_layout(a, src: dict, H: int = H) -> tuple[str, int, int]:
    """Monta o vídeo numa área W x H. Retorna (filtro que termina em [base],
    legenda_y padrão, titulo_y padrão), relativos à área."""
    layout = a.layout
    cam = regiao(a.cam)
    if layout == "auto":
        layout = "stream" if cam else "blur"

    if layout == "blur":
        f = (
            "[0:v]split=2[bg0][fg0];"
            f"[bg0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            "gblur=sigma=30,eq=brightness=-0.12,setsar=1[bg];"
            f"[fg0]scale={W}:-2,setsar=1[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]"
        )
        altura_fg = round(W * src["h"] / src["w"])
        legenda = min(H - 260, (H + altura_fg) // 2 + 170)
        titulo = max(170, (H - altura_fg) // 2 - 150)
        return f, legenda, titulo

    if layout == "crop":
        # Corte 9:16 na altura total; --foco 0 = esquerda, 0.5 = centro, 1 = direita
        cw = min(src["w"], round(src["h"] * W / H / 2) * 2)
        x = round((src["w"] - cw) * a.foco)
        f = f"[0:v]crop={cw}:{src['h']}:{x}:0,scale={W}:{H},setsar=1[base]"
        return f, round(H * 0.72), 260

    if layout == "stream":
        if not cam:
            sys.exit("layout 'stream' precisa de --cam x:y:w:h (região da facecam no vídeo original)")
        topo = round(H * a.proporcao_cam / 2) * 2
        resto = H - topo
        jogo = regiao(a.jogo)
        if jogo:
            jx, jy, jw, jh = jogo
        else:
            # Jogo: altura total, largura proporcional à área de baixo, centrado
            jh = src["h"]
            jw = min(src["w"], round(jh * W / resto / 2) * 2)
            jx, jy = (src["w"] - jw) // 2, 0
        cx, cy, cw, ch = cam
        f = (
            "[0:v]split=2[c0][j0];"
            f"[c0]crop={cw}:{ch}:{cx}:{cy}[c1];"
            f"[j0]crop={jw}:{jh}:{jx}:{jy}[j1];"
            + preencher("c1", "cam", W, topo) + ";"
            + preencher("j1", "jogo", W, resto) + ";"
            "[cam][jogo]vstack=inputs=2[base]"
        )
        return f, topo, 140

    sys.exit(f"layout desconhecido: {layout}")


# --------------------------------------------------------------------- render

def render(a, video: Path, inicio: float, fim: float, saida: Path, titulo: str | None,
           destaques=None):
    src = info(video)
    if fim <= inicio:
        sys.exit("o fim precisa ser depois do início")
    if fim - inicio > DURACAO_MAX and not a.forcar:
        sys.exit(f"corte de {fim - inicio:.1f}s passa de {DURACAO_MAX:.0f}s (use --forcar para ignorar)")

    tmp = Path(tempfile.mkdtemp(prefix="corte_"))
    estilo = getattr(a, "estilo", "viral")
    legenda_estilo = a.legenda_estilo or ("simples" if estilo == "noticia" else "viral")
    entradas = []
    if estilo == "noticia":
        if a.layout == "auto" and not a.cam:
            a.layout = "crop"  # vídeo preenchendo a área de baixo, como no modelo
        if not titulo:
            sys.exit("o estilo 'noticia' precisa de --titulo (a manchete da faixa branca)")
        topo = gerar_cabecalho(titulo, carregar_perfil(a.perfil), tmp / "cabecalho.png")
        filtro, legenda_y, _ = filtro_layout(a, src, H - topo)
        em_stream = a.layout == "stream" or (a.layout == "auto" and a.cam)
        legenda_y = topo + (legenda_y if em_stream else round((H - topo) * 0.74))
        filtro += f";[1:v]format=rgb24,setsar=1[cab];[cab][base]vstack=inputs=2[base2]"
        entradas = ["-loop", "1", "-i", str(tmp / "cabecalho.png")]
        ultimo = "base2"
        titulo_y, titulo = 0, None  # manchete já está na faixa
    else:
        filtro, legenda_y, titulo_y = filtro_layout(a, src)
        ultimo = "base"
    if a.legenda_y is not None:
        legenda_y = a.legenda_y
    if a.titulo_y is not None:
        titulo_y = a.titulo_y

    pal_path = Path(a.palavras) if a.palavras else arquivo_palavras(video)
    palavras = []
    if not a.sem_legenda:
        if pal_path.exists():
            palavras = json.loads(pal_path.read_text(encoding="utf-8"))
        else:
            print(f"aviso: {pal_path} não existe — rode 'transcrever' antes. Renderizando sem legenda.",
                  file=sys.stderr)
    if palavras or titulo:
        ass = tmp / "legenda.ass"
        ass.write_text(gerar_ass(palavras if not a.sem_legenda else [], inicio, fim, legenda_y,
                                 a.tamanho, a.palavras_por_vez, titulo, titulo_y,
                                 destaques, legenda_estilo), encoding="utf-8")
        filtro += f";[{ultimo}]ass={ass}:fontsdir={FONTES}[v]"
        ultimo = "v"
    filtro += f";[{ultimo}]fps={a.fps},format=yuv420p[vout]"

    saida.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stats",
           "-ss", f"{inicio:.3f}", "-t", f"{fim - inicio:.3f}", "-i", str(video), *entradas,
           "-filter_complex", filtro, "-map", "[vout]", "-t", f"{fim - inicio:.3f}"]
    if src["audio"]:
        cmd += ["-map", "0:a:0", "-af", "loudnorm=I=-14:TP=-1.0:LRA=11,aresample=48000",
                "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-preset", a.preset, "-crf", str(a.crf),
            "-profile:v", "high", "-movflags", "+faststart", str(saida)]
    run(cmd)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"ok: {saida}  ({fim - inicio:.1f}s)")


def cmd_render(a):
    video = Path(a.video)
    saida = Path(a.saida or Path("cortes") / f"{video.stem}_{int(tempo(a.inicio))}s.mp4")
    render(a, video, tempo(a.inicio), tempo(a.fim), saida, a.titulo, a.destaques)


def cmd_lote(a):
    """JSON: [{"nome": "corte1", "inicio": "1:02:10", "fim": "1:02:48",
               "titulo": "ELE DESCOBRIU UM *EASTER EGG* NO *GTA 6*", "destaques": ["easter egg", "gta 6"]}]"""
    video = Path(a.video)
    lista = json.loads(Path(a.lista).read_text(encoding="utf-8"))
    pasta = Path(a.pasta)
    for n, c in enumerate(lista, 1):
        nome = c.get("nome") or f"corte{n:02d}"
        op = copy.copy(a)  # opções deste corte não vazam para os próximos
        for k in ("estilo", "layout", "cam", "jogo", "legenda_y", "titulo_y", "legenda_estilo"):
            if k in c:
                setattr(op, k, c[k])
        if not c.get("titulo"):
            print(f"aviso: {nome} está sem manchete (titulo) — todo corte deve ter uma.", file=sys.stderr)
        render(op, video, tempo(c["inicio"]), tempo(c["fim"]), pasta / f"{nome}.mp4",
               c.get("titulo"), c.get("destaques", a.destaques))


# ------------------------------------------------------------------------ CLI

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("baixar")
    s.add_argument("url")
    s.add_argument("--pasta", default="brutos")
    s.add_argument("--trecho", help="só um pedaço, ex: 1:20:00-1:35:00")
    s.set_defaults(fn=cmd_baixar)

    s = sub.add_parser("transcrever")
    s.add_argument("video")
    s.add_argument("--modelo", default="small", help="tiny|base|small|medium|large-v3 ou pasta local")
    s.add_argument("--idioma", default="pt")
    s.add_argument("--inicio")
    s.add_argument("--fim")
    s.set_defaults(fn=cmd_transcrever)

    s = sub.add_parser("picos")
    s.add_argument("video")
    s.add_argument("--janela", type=int, default=5, help="tamanho da janela em segundos")
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--distancia", type=int, default=45, help="segundos mínimos entre picos")
    s.set_defaults(fn=cmd_picos)

    s = sub.add_parser("frame")
    s.add_argument("video")
    s.add_argument("tempo")
    s.add_argument("--saida")
    s.set_defaults(fn=cmd_frame)

    def opcoes_render(s):
        s.add_argument("--estilo", default="viral", choices=["viral", "noticia"],
                       help="viral = manchete em caixa preta + legenda palavra a palavra; "
                            "noticia = faixa branca com perfil e manchete, vídeo embaixo")
        s.add_argument("--perfil", help="JSON do perfil da faixa (padrão: perfil.json da skill)")
        s.add_argument("--legenda-estilo", choices=["viral", "simples"],
                       help="padrão: viral no estilo viral, simples no estilo noticia")
        s.add_argument("--layout", default="auto", choices=["auto", "blur", "crop", "stream"])
        s.add_argument("--cam", help="facecam x:y:w:h no vídeo original (layout stream)")
        s.add_argument("--jogo", help="área do jogo x:y:w:h (opcional, layout stream)")
        s.add_argument("--proporcao-cam", type=float, default=0.35, help="fração da altura para a cam")
        s.add_argument("--foco", type=float, default=0.5, help="layout crop: 0 esquerda .. 1 direita")
        s.add_argument("--palavras", help="arquivo .palavras.json (padrão: ao lado do vídeo)")
        s.add_argument("--sem-legenda", action="store_true")
        s.add_argument("--destaques", help="palavras-chave em verde na legenda, ex: 'easter egg,gta 6'")
        s.add_argument("--legenda-y", type=int)
        s.add_argument("--titulo-y", type=int, help="posição vertical do título (0 = topo, 1920 = base)")
        s.add_argument("--tamanho", type=int, default=110, help="tamanho da fonte da legenda")
        s.add_argument("--palavras-por-vez", type=int, default=3)
        s.add_argument("--fps", type=int, default=30)
        s.add_argument("--crf", type=int, default=20)
        s.add_argument("--preset", default="medium")
        s.add_argument("--forcar", action="store_true", help="permite cortes acima de 60s")

    s = sub.add_parser("render")
    s.add_argument("video")
    s.add_argument("--inicio", required=True)
    s.add_argument("--fim", required=True)
    s.add_argument("--saida")
    s.add_argument("--titulo", help="manchete-gancho; *palavras* entre asteriscos ficam em amarelo")
    opcoes_render(s)
    s.set_defaults(fn=cmd_render)

    s = sub.add_parser("lote")
    s.add_argument("video")
    s.add_argument("lista", help="JSON com os cortes")
    s.add_argument("--pasta", default="cortes")
    opcoes_render(s)
    s.set_defaults(fn=cmd_lote)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
