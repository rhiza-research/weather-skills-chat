import { describe, expect, it } from "vitest";
import { defaultTextSkillToolIds } from "./textSkills";

const skill = (id: string, enabled: boolean, enabled_by_default: boolean) => ({
  id,
  title: id,
  content: "x",
  visibility: "private" as const,
  enabled,
  enabled_by_default,
});

describe("defaultTextSkillToolIds", () => {
  it("selects enabled skills that are on by default", () => {
    expect(
      defaultTextSkillToolIds([
        skill("a", true, true),
        skill("b", true, false),
        skill("c", false, true),
      ]),
    ).toEqual(["text_skill:a"]);
    expect(defaultTextSkillToolIds(null)).toEqual([]);
  });
});
