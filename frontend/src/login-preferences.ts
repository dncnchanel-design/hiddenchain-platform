const ACCOUNT_KEY = "hiddenchain_remembered_account";

export function rememberedAccount(storage: Pick<Storage, "getItem"> = localStorage): string {
  try { return storage.getItem(ACCOUNT_KEY) || ""; }
  catch { return ""; }
}

export function rememberAccount(username: string, remember: boolean, storage: Pick<Storage, "setItem" | "removeItem"> = localStorage) {
  try {
    if (remember) storage.setItem(ACCOUNT_KEY, username);
    else storage.removeItem(ACCOUNT_KEY);
  } catch { /* Account convenience must never prevent authentication. */ }
}
