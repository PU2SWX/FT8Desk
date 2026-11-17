# FT8Desk

Estação **FT8 para desktop** (Windows 10/11, também roda em Linux/macOS), com
**PTT por FTDI via DTR** — pensada para quem usa cabo caseiro, DigiRig, XGGComms
ou interface com FT232 + transistor optoacoplador.

Não é um clone do qFT8 (aquele app tem ~130 modos e decodificadores próprios).
Aqui o foco é **FT8 muito bem feito** sobre o `ft8_lib` (o mesmo codec usado por
metade dos projetos sérios de FT8), com o que importa no dia a dia: decodificar
bem, chamar CQ, completar QSO, logar em ADIF e chavear o rádio sem dor de cabeça.

---

## 1. O que já funciona

| Recurso | Estado |
|---|---|
| Decodificação FT8 (CRC-14 + LDPC 174/91 + Costas sync) | ✅ testado, 4/4 mensagens a −5 dB |
| Codificação / transmissão FT8 (GFSK BT=2.0) | ✅ testado round-trip |
| Waterfall + espectro com marcador de TX | ✅ |
| Slots sincronizados em UTC (15 s) + NTP | ✅ |
| PTT por porta serial: DTR, RTS ou ambos, com inversão | ✅ |
| TX delay / hang time configuráveis | ✅ |
| Máquina de estados de QSO (CQ → relatório → RR73 → log) | ✅ testada |
| Log ADIF 3.1.4 append-only | ✅ testado |
| Interface com tema, sequenciador Tx1–Tx6, bússola, waterfall adaptativo | ✅ renderizada e revisada |
| Distância/azimute pelo grid (Maidenhead) | ✅ |
| FT4 | protocolo disponível no codec; UI operacional ainda focada em FT8 |

---

## 2. A interface

Console escuro com tema próprio (`ft8desk/ui/theme.py`), pensado para operar por
horas sem cansar a vista:

- **Cabeçalho de estação** — faixas em botões (160 m a 6 m), frequência de
  discagem, frequência de TX em Hz, indicativo e grid, relógio UTC grande.
- **Waterfall vertical** — frequência no eixo X e tempo descendo, **no mesmo
  eixo do espectro**: o pico do espectro fica exatamente em cima da marca do
  sinal na cachoeira. 30 s de histórico (2 slots), fronteiras de slot em linhas
  tracejadas com marcação `-15s`/`-30s`, marcadores com o indicativo de cada
  decode e linha de TX vertical.
- **Escala adaptativa**: o piso de ruído é medido em
  tempo real e a faixa de 42 dB é ajustada a ele, então o contraste fica correto
  com qualquer ganho de placa de som.
- **Tabela de decodes** — cor por significado: CQ em verde, mensagem dirigida a
  você em azul, indicativos já trabalhados esmaecidos, 73 em cinza. Duplo clique
  chama a estação.
- **Sequenciador TX (Tx1–Tx6)** — as seis mensagens padrão do QSO, geradas a
  partir do estado atual; a ativa fica destacada. Clique em qualquer uma para
  transmiti-la.
- **Aba QSO** — indicativo do DX em destaque, estado da sequência, relatório
  recebido, distância e **bússola com azimute**.
- **Barra de slot** — mostra a janela de transmissão, o progresso do slot e a
  paridade (PAR/ÍMPAR) da sua estação.
- **Chips de status** — NTP (offset em ms), taxa de áudio, estado do PTT, número
  de decodes e de QSOs no log.

As capturas de tela do aplicativo podem ser geradas em modo offscreen durante o
desenvolvimento. Elas não fazem parte do pacote-fonte mínimo desta versão.

---

## 3. Gerar o executável (para distribuir)

Quem recebe o executável **não precisa de Python** — tudo vai dentro da pasta.

Na sua máquina Windows, com o projeto em mãos:

```bat
build_exe.bat
```

O script cria um ambiente isolado, instala as dependências, empacota com
PyInstaller e gera:

```
dist\FT8Desk\FT8Desk.exe      <- pasta pronta para rodar
FT8Desk-windows.zip           <- é este arquivo que você envia
```

Tamanho esperado: ~170 MB descompactado, ~**100 MB** no ZIP (Qt + numpy).

**Como o amigo usa:** descompacta em qualquer pasta, dá duplo clique em
`FT8Desk.exe`. Não instala nada, não pede senha, não mexe no sistema. O log e as
configurações ficam em `%APPDATA%\FT8Desk`.

### Avisos honestos

- **SmartScreen**: o .exe não é assinado digitalmente (assinatura custa ~US$ 200/ano),
  então o Windows vai mostrar *"O Windows protegeu o seu PC"*. É só clicar em
  **Mais informações → Executar mesmo assim**. Avise seus amigos disso, senão
  eles desistem no primeiro clique.
- **Antivírus**: executáveis gerados por PyInstaller às vezes são sinalizados
  por heurística. A pasta (`onedir`) é bem menos problemática que o modo
  `onefile` — por isso o padrão é pasta.
- **Build tem de ser no Windows**: PyInstaller não compila para Windows a partir
  de Linux/macOS. Para Linux/macOS rode o mesmo spec lá.

### Se o build parar em "[3/5] Biblioteca nativa"

A DLL do FT8 já vem pronta no repositório (`native/ft8shim.dll`). Se o script
não a encontrou, uma de duas coisas aconteceu:

1. **O antivírus removeu o arquivo** ao descompactar (acontece com DLL gerada).
   Restaure da quarentena ou exclua a pasta da verificação.
2. **A pasta não veio completa.** Nesse caso não há problema — a partir da 0.7.3
   o script instala sozinho um compilador C portátil (`ziglang` via pip, sem
   precisar de Visual Studio) e compila a DLL.

Manual, se preferir:

```bat
.venv\Scripts\python -m pip install ziglang
.venv\Scripts\python build_native.py
```

E confira que o arquivo existe antes de continuar:

```bat
dir native\ft8shim.dll
```

### Versão em arquivo único (opcional)

```bat
.venv\Scripts\pyinstaller --onefile --windowed --icon ft8desk.ico ^
    --add-binary "native\ft8shim.dll;native" --name FT8Desk run.py
```

Gera um `.exe` só, mas abre mais devagar (descompacta em pasta temporária a cada
execução) e tem mais chance de falso positivo no antivírus.

---

## 4. Instalação a partir do código (desenvolvedor)

Pré-requisito: **Python 3.10+** ([python.org](https://www.python.org/downloads/windows/),
marque *Add python.exe to PATH*).

```bat
cd ft8desk
python -m pip install -r requirements.txt
python run.py
```

`run.py` carrega a biblioteca nativa `native/ft8shim.dll` (já vem compilada no
repositório). Se ela não carregar no seu Windows, ele compila sozinho:

```bat
python -m pip install ziglang
python build_native.py
```

Antes de operar, rode o diagnóstico:

```bat
python -m ft8desk.diag
```

Se o NTP falhar, o `diag` mostra o motivo (UDP 123 bloqueado, servidor com
estrato 0, etc.). O app tenta cinco servidores e, se todos falharem, cai para o
cabeçalho `Date` via HTTPS — pior precisão (±0,5 s), mas melhor que nada.

Ele mostra: biblioteca nativa + auto-teste de encode/decode, dispositivos de
áudio, portas seriais (onde o FTDI aparece), offset do NTP e caminho do log.

---

## 5. Áudio

1. Cabo de áudio do rádio para a entrada de linha/USB do PC (nível de **linha**;
   se usar entrada de microfone, atenue — sinal alto gera IMD e decodifica pior).
2. No menu **Estação → Configurações → Áudio**, escolha a entrada e a saída.
3. Taxa: use a taxa nativa do dispositivo (48 kHz é o padrão). O app reamostra
   para 12 kHz internamente, com filtro anti-alias.
4. Ajuste o volume de TX com o rádio em carga falsa: pico de ALC **zero**, e
   potência ~30–50 % do máximo. Ajuste fino pelo "Ganho de TX".

---

## 6. PTT por FTDI (DTR)

### Ligação típica

```
FT232RL            transistor             rádio
  DTR# ──[1k]── B(2N7000/BC547) ── coletor ──── PTT (para GND do rádio)
  GND  ─────────────────────────── emissor ──── GND
```

Se o seu cabo já tem o chaveamento pronto (DigiRig, XGGComms, SignaLink), só
conecte e escolha a porta.

### Configuração

Em **Configurações → PTT / FTDI**:

| Campo | O que faz |
|---|---|
| Porta | `COM3`, `COM7`… (a porta do FTDI) |
| Linha de PTT | `DTR`, `RTS` ou `DTR + RTS` |
| Inverter polaridade | inverte o nível lógico — **use se o rádio transmitir ao contrário** |
| Atraso de TX | tempo entre fechar o PTT e começar o áudio (150 ms padrão; 300 ms se tiver amplificador) |
| Hang time | tempo de PTT ligado depois do áudio (120 ms padrão) |

**Detalhe de hardware que pega todo mundo:** no FT232R o pino **DTR# é ativo em
nível baixo**. Com "Inverter polaridade" desmarcado, o app faz `ser.dtr = True`,
o que coloca o pino em LOW. Metade dos cabos caseiros chaveia em LOW, a outra
metade em HIGH — por isso a opção existe. O botão **Testar PTT (1 s)** resolve
isso em 10 segundos: aperte, veja se o rádio entra em TX, e se ficar invertido
marque a caixa e teste de novo.

A porta serial fica **aberta durante toda a sessão** (abrir/fechar porta faz o
driver pulsar as linhas e pode gerar transmissão fantasma).

---

## 7. Operando

1. Preencha **indicativo** e **grid** na barra superior.
2. Escolha a banda (a frequência de discagem FT8 é preenchida automaticamente:
   20 m = 14.074 MHz USB).
3. Ajuste a frequência de áudio de TX (clique no waterfall ou use o campo `TX`).
4. Espere o slot: a lista **Decodes** preenche a cada 15 s.
5. **Chamar CQ**: botão `CQ`. **Responder alguém**: duplo clique na linha do
   decode. A partir daí o app conduz a sequência sozinho.
6. `Habilitar TX` precisa estar marcado. `Parar TX` cancela imediatamente e solta
   o PTT.

### Modo automático

Três níveis, independentes:

| Nível | O que faz | Como ligar |
|---|---|---|
| **Sequência** | uma vez iniciado o QSO, o app conduz tudo: relatório → R+relatório → RR73 → log. Se o outro lado não responde, repete até o limite e desiste. | sempre ativo |
| **Responder** | se alguém te chama direto (`PY2ABC W1AW -12`) enquanto você está ocioso, o app entra na sequência sozinho. | Configurações → *Responder automaticamente* |
| **AUTO (caça)** | fica ouvindo CQ e chama uma estação automaticamente, completa o QSO e loga. Escolhe o sinal mais forte que passe nos filtros; ignora quem já está no log e ignora `CQ DX`. | botão **AUTO** na barra de TX |

No modo AUTO os filtros ficam em *Configurações → Avançado*: SNR mínimo
(padrão −18 dB), não chamar quem já está no log, ignorar `CQ DX`. Se o QSO for
abandonado por timeout, ele volta a caçar. Com *Repetir CQ sozinho* ligado, ao
terminar um QSO ele recomeça a chamar CQ em vez de caçar.

### O AUTO não está chamando ninguém?

A partir da 0.7.1 o app **diz o motivo** na barra de status em vez de ficar em
silêncio. Causas comuns, em ordem:

1. **"todos já estão no log nesta banda"** — o filtro `Não chamar quem já está
   no log` agora considera **só a banda atual**: um QSO em 40 m não bloqueia a
   mesma estação em 20 m. Se ainda assim quiser chamar quem já está no log,
   desmarque a opção em *Configurações → Avançado*.
2. **"todos abaixo de −18 dB"** — baixe o *SNR mínimo* (dá para ir até −24 dB).
3. **`CQ DX` é ignorado** por padrão; desmarque *Ignorar "CQ DX"* se quiser
   chamar essas estações.
4. **TX desabilitado** — a aba QSO mostra "AUTO ligado, mas TX está desabilitado".
5. **QSO anterior travado** — se uma transmissão falhou (PTT/áudio), o estado
   ficava "ativo" para sempre e o AUTO nunca mais agia. Agora um **watchdog**
   abandona qualquer QSO sem progresso em 2 minutos e devolve o controle.

### Slots alternados (par / ímpar) — importante

FT8 é um protocolo de slots de 15 s. **Duas estações que transmitem no mesmo
slot nunca se ouvem.** Por isso quem chama usa uma paridade e quem responde usa
a outra:

```
slot par    Eu  ──► CQ PY2ABC GG66
slot ímpar       ◄── PY2ABC W1AW -05      (DX responde na paridade dele)
slot par    Eu  ──► W1AW PY2ABC -10
slot ímpar       ◄── PY2ABC W1AW R-07
slot par    Eu  ──► W1AW PY2ABC RR73
```

Na barra de status aparece `TX: par` ou `TX: impar`. Em **Configurações →
Avançado** há três opções: `Automático` (padrão — escolhe a paridade oposta à do
DX que você chamou), `Sempre pares` e `Sempre ímpares`.

Com isso o intervalo entre suas transmissões é de ~30 s, sobrando ~17 s para
decodificar a resposta do outro lado. Antes da correção o app transmitia no slot
seguinte (~2 s de intervalo) sem esperar o decode — o QSO nunca avançava.

### As seis mensagens (é o que os botões Tx1–Tx6 mostram)

O app sabe se **você chamou** ou se **você respondeu**, e usa a forma correta
para cada papel:

```
chamador (quem chamou CQ)          respondente (quem respondeu)
--------------------------         ----------------------------
Tx1  CQ PY2ABC GG66                Tx2  PY2ABC W1AW FN31
Tx3  W1AW PY2ABC -10               Tx4  PY2ABC W1AW R-09
Tx5  W1AW PY2ABC RR73  (log)       Tx6  PY2ABC W1AW 73    (log)
```

O `R` do Tx4 é o acuse de recebimento do relatório — só quem respondeu ao CQ
manda essa forma. Isso é verificado por teste automatizado: duas estações
simuladas trocam exatamente Tx1→Tx6 e as duas encerram.

Depois do RR73/73 o QSO **termina de verdade**: a máquina de estados entra em
`FINAL` e não retransmite a despedida (antes ela repetia o `73` indefinidamente).
Mensagens de relatório são repetidas no máximo `max_repetitions` vezes antes de
desistir; só o CQ repete sem limite.

---

## 8. Log

ADIF 3.1.4 em `%APPDATA%\FT8Desk\ft8desk.adi` (ou o caminho que você escolher).
Gravado **na hora**, sem "salvar" — se o app fechar, o QSO está no disco.
Importa em Log4OM, LogHX, DXLab, LoTW etc.

### Proteções contra log repetido

Três travas, porque no ar o outro lado às vezes não copia o `RR73` e a sequência
recomeça:

1. **Paridade na chamada direta** — quando alguém te chama, o app assume a
   paridade **oposta** à do DX. Sem isso podia transmitir no mesmo slot dele (ele
   nunca te ouvia, voltava a chamar, e o ciclo se repetia).
2. **QSO recém-concluído** — a mesma estação chamando de novo em até 5 minutos é
   ignorada, com aviso na barra de status.
3. **Anti-duplicidade no log** — mesmo indicativo + banda + modo dentro de 10
   minutos não gera segundo registro.

E o QSO só é **registrado depois** que a transmissão final conclui com sucesso:
se o PTT ou o áudio falharem, nada vai para o log.

Se o DX aparece sem `GRIDSQUARE`, o app completa pelo **cache de grids**: todo
grid visto num decode daquela estação (num `CQ ... GG66`) fica guardado e é usado
no log.

### Exportar para o QRZ

Aba **LOG** → botão **Exportar ADIF...** (ou menu **Log**). O diálogo permite:

- escolher destino (padrão `ft8desk-AAAAMMDD-HHMM.adi`)
- **formato**: `QRZ / geral (MODE=FT8)` ou `LoTW (legado) (MODE=MFSK + SUBMODE=FT8)`
- filtrar por **data de corte**, **banda** e **modo**
- remover duplicados (mesmo indicativo/dia/hora)

O arquivo sai com cabeçalho ADIF 3.1.4 e, em cada registro, os campos que o QRZ
exige: `CALL`, `QSO_DATE`, `BAND`, `MODE` (além de `TIME_ON`, `GRIDSQUARE`,
`RST_SENT`, `RST_RCVD`, `STATION_CALLSIGN`, `MY_GRIDSQUARE`, `FREQ`).
No QRZ: *Logbook → Import/Export Tools → Import from ADI File*.
Não usa `SUBMODE` no formato QRZ, porque o Logbook trata FT8 como modo final.

### Limpar o log

Aba **LOG → Limpar log...**. Os QSOs atuais são **arquivados** num arquivo com
data e hora (`ft8desk-backup-20261116-014810.adi`) e um log novo em branco é
aberto. Nada é apagado — dá para reimportar o backup a qualquer momento.

O texto é normalizado para ASCII antes de gravar (acentos em comentários
quebrariam o contador de caracteres do ADIF em servidores que leem bytes).

---

## 9. Arquitetura

```
native/ft8_shim.c     API C enxuta sobre o ft8_lib (create/feed/decode/encode)
native/ft8_lib/       codec FT8/FT4 (kgoba/ft8_lib, MIT) — vendorizado
build_native.py       compila a lib: zig cc → MSVC → gcc
ft8desk/native.py     bindings ctypes (Decoder: feed/decode/encode, check_text)
ft8desk/ptt.py        PTT serial (DTR/RTS, inversão, delays, test pulse)
ft8desk/clock.py      SNTP próprio + fronteiras de slot UTC
ft8desk/audio.py      sounddevice + reamostragem + SlotCollector
ft8desk/qso.py        máquina de estados do QSO
ft8desk/parse.py      interpretação de mensagens FT8
ft8desk/adif.py       log ADIF
ft8desk/grid.py       Maidenhead, distância, azimute
ft8desk/waterfall_model.py   FFT → matriz de waterfall (numpy puro)
ft8desk/ui/           PySide6: janela, waterfall, configurações
```

Fluxo de dados:

```
áudio 48k ──resample──> 12k ─┬─> WaterfallModel (visual)
                             └─> SlotCollector ──15 s──> DecodeJob (thread)
                                                              │
                              tabela de decodes <─────────────┘
                                     │
                                QsoEngine ──> TX (PTT + áudio) ──> ADIF
```

---

## 10. Testes

```bat
python tests\test_roundtrip.py   :: sintetiza FT8, mistura ruído, decodifica
python tests\test_logic.py       :: parse, QSO, ADIF, grid, coletor, FFT
```

Nenhum dos dois precisa de rádio, placa de som ou display.

---

## 11. Limitações conhecidas

- A UI é validada por **render offscreen** durante o desenvolvimento e por checagem
  estática com mypy contra os stubs oficiais do PySide6 — não por uso real em
  Windows. Pequenos ajustes de espaçamento podem ser necessários.
- A interface operacional atualmente é focada em FT8; o codec já aceita FT4.
- Sem CAT: banda/frequência são informativas, o rádio é sintonizado à mão.
- Sem PSK Reporter / LoTW upload.
- SNR é estimativa calibrada em sinais sintéticos (±1 dB); comparável ao WSJT-X,
  não idêntico.
- Uma transmissão por slot (sem multi-tone/fox-hound).

Roadmap curto: FT4 na UI, resposta automática a quem te chama, upload PSK
Reporter, CAT via rigctl, mapa de estações.

---

## 12. Licenças

- Código do FT8Desk: use como quiser (MIT).
- `ft8_lib` — © Karlis Goba (YL3JG), licença **MIT** em `native/ft8_lib/LICENSE`.
- Pequenos patches de portabilidade no `ft8_lib` (stpcpy, LOG_LEVEL, VLA-free)
  estão comentados no próprio código.
