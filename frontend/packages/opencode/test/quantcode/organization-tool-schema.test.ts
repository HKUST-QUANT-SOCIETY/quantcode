import { describe, expect, test } from "bun:test"
import { Schema } from "effect"
import { ReuseParameters, ReuseJsonSchema } from "../../src/tool/organization-reuse"
import { SolutionParameters, SolutionJsonSchema } from "../../src/tool/organization-solution"

describe("organization tool model schemas", () => {
  test.each([ReuseJsonSchema, SolutionJsonSchema])("model presentation is one object with an action enum", schema => {
    expect(schema.type).toBe("object")
    expect(schema.required).toEqual(["action"])
    expect(schema).not.toHaveProperty("anyOf")
    expect(schema.properties?.action).toMatchObject({ enum: ["status", "propose"] })
  })

  test("component and solution lists are arrays of strings", () => {
    for (const field of [ReuseJsonSchema.properties?.components, SolutionJsonSchema.properties?.acceptance_criteria,
      SolutionJsonSchema.properties?.file_impact]) {
      expect(field).toMatchObject({ type: "array", items: { type: "string" } })
    }
  })

  test("status and valid proposals retain the runtime union contract", () => {
    const reuse = { action: "propose", coverage: "partial", components: ["quant-evaluator"], reason: "Fixture gap" } as const
    const solution = { action: "propose", goal: "Create the report", acceptance_criteria: ["Report contains the result"],
      file_impact: ["report.md"], expected_hash: "fixture-hash", expected_version: 1 } as const
    expect(Schema.decodeUnknownSync(ReuseParameters)({ action: "status" })).toEqual({ action: "status" })
    expect(Schema.decodeUnknownSync(SolutionParameters)({ action: "status" })).toEqual({ action: "status" })
    expect(Schema.decodeUnknownSync(ReuseParameters)(reuse)).toEqual(reuse)
    expect(Schema.decodeUnknownSync(SolutionParameters)(solution)).toEqual(solution)
    expect(Schema.decodeUnknownSync(ReuseParameters)({ ...reuse, coverage: "none", components: [] })).toMatchObject({ components: [] })
  })

  test.each([
    { action: "propose", coverage: "none", components: "[]", reason: "Fixture gap" },
    { action: "propose", coverage: "none", components: [1], reason: "Fixture gap" },
    { action: "propose", coverage: "none", reason: "Fixture gap" },
    { action: "propose", components: [], reason: "Fixture gap" },
    { action: "propose", coverage: "none", components: [] },
    { action: "approve" },
  ])("reuse rejects invalid proposal %j", input => {
    expect(() => Schema.decodeUnknownSync(ReuseParameters)(input)).toThrow()
  })

  test.each([
    { action: "propose", goal: "Report", acceptance_criteria: "[]", file_impact: [] },
    { action: "propose", goal: "Report", acceptance_criteria: [], file_impact: "[\"report.md\"]" },
    { action: "propose", goal: "Report", acceptance_criteria: [] },
    { action: "propose", goal: "Report", file_impact: [] },
    { action: "propose", acceptance_criteria: [], file_impact: [] },
    { action: "propose", goal: "Report", acceptance_criteria: [], file_impact: [], expected_version: "1" },
    { action: "freeze" },
    { action: "approve" },
  ])("solution rejects invalid proposal %j", input => {
    expect(() => Schema.decodeUnknownSync(SolutionParameters)(input)).toThrow()
  })
})
