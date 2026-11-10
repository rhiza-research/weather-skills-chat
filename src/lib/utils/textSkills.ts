import { get } from "svelte/store";
import { textSkills } from "$lib/stores";
import { getTextSkills, type TextSkill } from "$lib/apis/textSkills";

/** A chat's skills ride in its tool selection with this prefix; the server splits them out. */
export const TEXT_SKILL_PREFIX = "text_skill:";

export const textSkillToolId = (id: string) => `${TEXT_SKILL_PREFIX}${id}`;

/** Skills switched on in a new chat: enabled and on by default. */
export const defaultTextSkillToolIds = (skills: TextSkill[] | null): string[] =>
  (skills ?? [])
    .filter((s) => s.enabled && s.enabled_by_default)
    .map((s) => textSkillToolId(s.id));

/** The active organization's skills, fetched once until the organization changes. */
export const loadTextSkills = async (): Promise<TextSkill[]> => {
  const current = get(textSkills);
  if (current) return current;
  const loaded = await getTextSkills(localStorage.token).catch(() => []);
  textSkills.set(loaded);
  return loaded;
};
