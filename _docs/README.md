# Documentacao do Bot

Esta pasta documenta o runtime atual do bot deste repositorio.

O ponto central mudou desde a versao anterior:
- a defesa nao e mais so "segurar base X"
- a camada espacial agora passa por `frontline`, `world compression`, `operational geometry` e `territorial control`
- `MapControlPlanner` e `DefensePlanner` ficaram subordinados a essa leitura espacial

## Leitura recomendada

1. [Visao geral da arquitetura](architecture/overview.md)
2. [Runtime: Attention](runtime/attention.md)
3. [Runtime: Awareness](runtime/awareness.md)
4. [Runtime: Intel](runtime/intel.md)
5. [Catalogo de estado](runtime/state_catalog.md)
6. [Ownership de namespaces](governance/ownership.md)
7. [Perfis de build](builds/profiles.md)

## Estrutura

- `architecture/`: pipeline, camadas e responsabilidades
- `runtime/`: contratos de dados e chaves em runtime
- `governance/`: ownership de prefixes e hotspots de escrita
- `builds/`: formato dos profiles e selecao em runtime

## Escopo

Esta documentacao cobre o bot deste repositorio.

Documentacao do framework `ares-sc2` continua em:
- `ares-sc2/docs/`
- `ares-sc2/README.md`
