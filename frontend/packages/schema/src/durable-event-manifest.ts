import { QuantCodeGovernance } from "./quantcode-governance"
import { QuantCodeTaskIndex } from "./quantcode-task-index"
import { QuantCodeBudgetEvent } from "./quantcode-budget"
import { QuantCodeKnowledge } from "./quantcode-knowledge"
export * as DurableEventManifest from "./durable-event-manifest"

import { Event } from "./event"
import { SessionEvent } from "./session-event"
import { SessionV1 } from "./session-v1"

export const SessionDurable = {
  definitions: Event.durable(SessionEvent.DurableDefinitions),
  schema: SessionEvent.Durable,
} as const

export const Durable = Event.durable([
  ...QuantCodeKnowledge.Definitions,
  ...QuantCodeTaskIndex.Definitions,
  ...QuantCodeGovernance.Definitions,
  ...QuantCodeBudgetEvent.Definitions,
  ...SessionV1.Event.Definitions.filter((definition) => definition.durable !== undefined),
  ...SessionEvent.DurableDefinitions,
])
