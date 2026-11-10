import { WEBUI_API_BASE_URL } from "$lib/constants";
import { parseApiError } from "$lib/apis/response";
import { organizationHeaders } from "$lib/apis/organizations";

export type TextSkill = {
  id: string;
  title: string;
  content: string;
  visibility: "private" | "organization";
  enabled: boolean;
  enabled_by_default: boolean;
  can_manage?: boolean;
};

type TextSkillFields = Partial<
  Pick<
    TextSkill,
    "title" | "content" | "visibility" | "enabled" | "enabled_by_default"
  >
>;

const request = async (
  token: string,
  path: string,
  options: RequestInit = {},
) => {
  const res = await fetch(`${WEBUI_API_BASE_URL}${path}`, {
    ...options,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      authorization: `Bearer ${token}`,
      ...organizationHeaders(),
    },
  });
  if (!res.ok) {
    const err = await parseApiError(res);
    throw err.detail ?? err;
  }
  return res.json();
};

export const getTextSkills = async (token: string): Promise<TextSkill[]> =>
  request(token, "/text_skills/");

export const createTextSkill = async (token: string, skill: TextSkillFields) =>
  request(token, "/text_skills/", {
    method: "POST",
    body: JSON.stringify(skill),
  });

export const updateTextSkillById = async (
  token: string,
  id: string,
  skill: TextSkillFields,
) =>
  request(token, `/text_skills/${id}/update`, {
    method: "POST",
    body: JSON.stringify(skill),
  });

export const deleteTextSkillById = async (token: string, id: string) =>
  request(token, `/text_skills/${id}`, { method: "DELETE" });
