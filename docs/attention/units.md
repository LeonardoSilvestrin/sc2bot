# Units

↑ [Attention](README_ATTENTION.md) · [Frame](frame.md)

> O que uma unidade é, para a percepção: uma visão imutável dela e a classificação que todas as camadas
> leem. Nada aqui diz se ela é perigosa ou valiosa.

## UnitView

`unit_view` congela uma unidade do python-sc2 em `UnitView`: `tag`, `type_id`, `position`, `health` (a fração
de vida + escudo), `power` (0 para um Changeling, que reporta a arma do que imita), `supply`, se voa, se atira no chão e no ar, se é worker ou estrutura, se está pronta, o
`role` do Ares e, conforme o caso:

- `energy`;
- `is_cloaked` (camuflada ou enterrada) e `is_hidden` (camuflada e não revelada: nada a detecta);
- `moving_to`: o ponto aonde a primeira ordem leva, quando é move, attack-move, patrol ou smart no chão;
- `has_add_on`;
- `cargo_used` / `cargo_max`: as vagas de um Bunker (quem está dentro não aparece em lugar nenhum).

## Poder

`unit_power(dps, vida, alvos) = sqrt(dps · alvos · vida) / MARINE_POWER`, em Marines:

- `MARINE_POWER = sqrt(9,8 · 45)`, então um Marine vale 1;
- `alvos` é quantos alvos um tiro cobre, em equivalentes de dano cheio, contra um grupo aglomerado como a
  nossa bola de bio (`SPLASH_TARGETS`, nunca menos que 1);
- o splash multiplica o dano que a unidade **causa**, dentro da raiz: um Siege Tank em siege com a vida
  cheia vale 4,3 Marines em vez de 2,7;
- só contam armas automáticas, porque `ground_dps`/`air_dps` não enxergam feitiço.

Somar poderes é a lei quadrática de Lanchester: dobrar o número de unidades dobra o poder somado.

| `SPLASH_TARGETS` | Alvos |
| --- | --- |
| Baneling | 3,0 |
| Siege Tank em siege, Widow Mine enterrada, Hellbat, Colossus, Lurker enterrado | 2,5 |
| Liberator em modo terrestre, Hellion, Archon | 2,0 |
| Mutalisk | 1,5 |

## Exército

`is_army`: nem worker, nem estrutura, nem MULE, Auto-Turret, Larva, Egg, Broodling, Overlord, Overseer,
Observer, a sombra do Adept ou Changeling.

## Código

- [bot/attention/units.py](../../bot/attention/units.py): `UnitView`, `unit_view`, `unit_power`,
  `is_army`, `SPLASH_TARGETS`, `WORKER_TYPES`.
