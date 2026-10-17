# Opening belief

↑ [Awareness](README_AWARENESS.md) · [Opening watch](../attention/opening-watch.md)

> O que a abertura inimiga significa: quatro leituras contínuas e uma confiança, lidas a partir dos fatos
> que a Attention registrou.

`read_opening` transforma o `OpeningObservations` do [Opening watch](../attention/opening-watch.md) numa
`OpeningBelief`: o quanto a abertura parece `aggression`, `greed`, `tech` e `proxy`. As quatro ficam em
[0, 1] e são independentes: não somam 1. Uma abertura pode ser agressiva e tecnológica ao mesmo tempo, e uma
que ninguém viu não é nenhuma delas.

## Como lê

Toda evidência é contínua, então um Gateway a mais nunca vira a leitura. Vale **quando foi observado**, não
o instante atual: uma expansão confirmada vazia aos 1:31 diz que o inimigo não tinha natural aos 1:31, e isso
continua verdade. O que envelhece é a confiança.

- Rampas por raça (`knowledge.py`): `atraso = clamp((referência − early) / (late − early))` e
  `antecipação = clamp((late − visto) / (late − early))`. A referência de uma expansão é o instante em que foi
  vista de pé (`PRESENT`) ou o da última checagem vazia (`ABSENT_CONFIRMED`). `UNKNOWN` lê 0: ninguém olhou
  não é "não tem".
- `aggression = S(1,0·atraso_natural + 0,9·produção_extra + 0,9·rush + 0,6·unidades_precoces)`.
- `greed = S(1,1·antecipação_natural + 1,3·antecipação_third)`.
- `tech = S(0,9·tipos_de_tech + 0,8·gás_extra + 0,6·atraso_third·gás_extra)`.
- `proxy = S(1,6·faltando_na_main·cobertura + 2,0·estruturas_na_nossa_metade + 0,5·rush)`.
  `faltando_na_main` é a fração do que a raça deveria ter na main, pesada pela cobertura e por quanto o
  registro passou do horário esperado.
- `confidence = (1 − (1 − explorado) · (1 − avistado)) · recência · raça`, com:
  - `explorado = clamp(0,45·cobertura + 0,35·checagens + 0,20·evidência)`;
  - `avistado = 1,0 · estruturas_na_nossa_metade` (`proxy_sighting`);
  - `recência = exp(-max(0, t − last_updated − 30 s) / 120 s)`;
  - `raça = 0,6` enquanto a raça é desconhecida.

As duas fontes da confiança são independentes. Um proxy visto no caminho é a abertura vista, não inferida do
que falta na main, e vale o mesmo antes de a main ser vista. Um registro velho continua dizendo o mesmo; o que
cai é quanto ele vale.

## Knowledge por raça

`OpeningExpectations` (`ZERG`, `TERRAN`, `PROTOSS`, `UNKNOWN`) traz as normas de ladder em segundos de jogo:
quando a natural e a third são cedo ou tarde, quanta produção e quanto gás uma abertura padrão tem e até
quando, o que deveria estar na main, o que é tech e o que só um rush constrói. Calibrar a leitura é editar
essa tabela, não o scoring. Um Random que ainda não mostrou a raça lê `UNKNOWN`, que não espera nada na main,
então uma main que não dá para interpretar nunca acusa proxy.

## Quem lê

- Defense (`policies/rush.py`): a leitura de rush. Ver [Defense](../ego/planners/defense.md).
- Intel: manda procurar proxy pela suspeita, e encerra a ronda do scout quando a `confidence` passa de
  `READ_ENOUGH`. Ver [Intel](../ego/planners/intel.md).
- Logs: `awareness.opening_updated`, o painel do overlay e dos SVG, e o chat (proxy, aggression, greed, tech).

## Parâmetros

Pesos e escalas em `OpeningBeliefConfig`, com os valores das fórmulas acima; normas em `knowledge.py`.

## No log

`awareness.opening_updated`: um fato novo, a leitura muda de faixa (1 casa decimal) ou heartbeat. Traz
`summary`, `belief` e cada termo em `evidence`.

## Limitações conhecidas

- A Strategy ainda não lê a `OpeningBelief`.
- Nenhum limiar ou peso da leitura foi medido em partida real.

## Código

- [bot/awareness/opening/belief.py](../../bot/awareness/opening/belief.py): `read_opening`, `OpeningBelief`,
  `OpeningBeliefConfig`.
- [bot/awareness/opening/knowledge.py](../../bot/awareness/opening/knowledge.py): `OpeningExpectations`,
  `expectations_for`.
