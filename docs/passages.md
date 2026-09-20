# Passagens dinâmicas

`MapPassage` (também exportada como `Passage`) guarda identidade, geometria,
regiões, `blocker_type`, `blocker_tags` e `state`. Os valores de estado são
`OPEN`, `CLOSED` e `UNKNOWN`, serializados em minúsculas. A geometria de
`MapTopology`, a adjacência estática e a identidade das expansões são construídas
uma vez. Uma transição substitui somente os registros de estado e o snapshot
`MapView`; regiões, lattice, natural/third e associação de expansões permanecem.

## Associação e atualização

`read_blockers` distingue mineral walls dos recursos das expansões usando os
grupos de recursos do python-sc2. Para rocks, usa os footprints do MapAnalyzer,
com fallback pelo raio, excluindo objetos decorativos e zonas de aceleração.
Blockers com células adjacentes formam grupos, inclusive mistos. Um grupo é
associado a uma passagem quando, carimbado no grid, interrompe a conectividade
local entre seus lados. Um desvio distante não torna a passagem aberta.

`PassageWatch` acompanha as tags desses grupos na lista de neutros de cada
observação. Compara as tags sobreviventes, não apenas a contagem de unidades:

- Algum blocker permanece: `CLOSED`, inclusive após remoção parcial.
- Todos desapareceram, ou os minerais observados estão esgotados: `OPEN`.
- Alguma fonte de observação não pôde ser lida: `UNKNOWN`, sem permitir trânsito.
- Um snapshot sem quantidade de minerais continua contando como blocker.

Somente mudanças de estado substituem o snapshot do mapa. A topologia não é
recalculada por frame. A telemetria `map.passage_changed` informa passagem,
transição, tipo, blockers restantes, regiões e posição.

## Consumidores

`open_passages`, `connected_regions`, `route` e `reachable` oferecem conectividade
atual. `neighbours(..., open_only=True)` filtra a adjacência estática. No `MapView`,
`route_to` e `reachable_now` consultam a mesma topologia sem renomear expansões.

MapControl/staging usa apenas passagens abertas nas distâncias, candidatos e
avaliação de proteção de bases. Seu cache é invalidado quando o mapa muda.
Intel atualiza saídas inimigas, rotas de busca de proxy e a ronda de uma missão
ativa. O scout evita destinos inacessíveis a partir da própria posição e pode
retomar a observação se uma parede abrir durante sua janela. O movimento de
unidades continua usando o grid atualizado do Ares.

## Validação reproduzível em Torches

Com StarCraft II e `TorchesAIE_v4` instalados, a partir da raiz do projeto:

```powershell
.venv\Scripts\python.exe scripts/validate_torches_passages.py --seed 1 --output bench/torches-passages/seed-1.json
```

O script inicia uma partida curta com o bot completo, valida a geometria real e
simula remoção parcial e total filtrando os minerais observados. Verifica duas
paredes inicialmente fechadas, identidade estável, mudança de rota, uso do
atalho nas distâncias de staging e uma única transição de telemetria. Falha com
exit code diferente de zero se algum callback não terminar ou uma asserção falhar.
Não é um teste de mineração física por SCVs.

Na validação de 20/09/2026, seeds 1 e 2 (os dois lados de spawn): 18 regiões,
27 passagens e duas paredes com 15 blockers cada. A rota entre os lados passou de quatro passagens a uma;
a outra parede permaneceu fechada. Natural/third e geometria permaneceram iguais.
