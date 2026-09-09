import { Schema } from "effect"

const Hash = Schema.String.check(Schema.isPattern(/^[a-f0-9]{64}$/))
export const CredentialPreparation = Schema.Struct({
  version: Schema.Literal(1), nonce: Schema.String, session_id: Schema.String,
  owner_digest: Hash, github_subject: Schema.String, expires_at: Schema.Finite,
}).annotate({ identifier: "QuantCodeGitHubCredentialPreparation" })
export interface CredentialPreparation extends Schema.Schema.Type<typeof CredentialPreparation> {}

/** Secret-bearing request accepted only from a desktop main-process transport;
 * never returned in responses, event payloads, tool arguments or renderer IPC. */
export const CredentialImport = Schema.Struct({
  version: Schema.Literal(1), nonce: Schema.String, session_id: Schema.String,
  owner_digest: Hash, token: Schema.String.check(Schema.isPattern(/^\S{1,16384}$/)),
}).annotate({ identifier: "QuantCodeGitHubCredentialImport" })
export interface CredentialImport extends Schema.Schema.Type<typeof CredentialImport> {}
export const Connection = Schema.Struct({ status: Schema.Literal("connected"), subject: Schema.String })
  .annotate({ identifier: "QuantCodeGitHubConnection" })
export interface Connection extends Schema.Schema.Type<typeof Connection> {}
export * as QuantCodeGitHub from "./quantcode-github"
