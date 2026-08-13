export type RoleCode = "GENERATOR" | "RETAILER" | "EXCHANGE" | "REGULATOR" | "ADMIN";

export interface UserProfile {
  user_id: string;
  org_id: string;
  username: string;
  display_name: string;
  role_code: RoleCode;
  status: string;
  last_login_at?: string | null;
}

export interface SessionPayload {
  access_token?: string;
  user: UserProfile;
  org: Record<string, unknown>;
  did: Record<string, unknown>;
  menus: Array<{ code: string; path: string; roles: RoleCode[] }>;
  field_scopes: Record<string, string>;
}

export type JsonRecord = Record<string, any>;

export const ROLE_LABELS: Record<RoleCode, string> = {
  GENERATOR: "发电企业",
  RETAILER: "售电企业",
  EXCHANGE: "交易中心",
  REGULATOR: "监管方",
  ADMIN: "系统管理员",
};
