# M1 — Estabilidade

↑ [Marcos](README_MILESTONES.md)

**Objetivo:** nenhuma partida perdida por crash ou por uma exceção num planner.

**Critério de saída:** Terran CheatInsane, 3 seeds, 0 crash; um teste em que um planner lança exceção e o frame
segue com o plano neutro dele.

**Depende de:** nada. É o primeiro porque o bench do [M2](m2-medicao.md) precisa de partidas que terminem.

## Itens

**Blips de radar derrubam o bot** [D1] — o Ares não filtra os blips das nossas Sensor Towers, e um `KeyError: 0`
encerra a partida contra Terran. Direção: sobrescrever `_should_add_unit` no bot (o Ares só o chama para unidades
inimigas), sem forkar o Ares; até lá, pausar as torres. Aceite: Terran CheatInsane, 3 seeds, 0 crash.

**Uma exceção derruba o frame inteiro** [D1, N8, P0.5] — não há `try` em volta de `play_frame` nem de cada
planner. Direção: o planner que falha devolve um plano neutro e registra o erro; sem frame, só o macro do Ares.
