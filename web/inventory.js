/* Inventory (库存): the page asks the game's official API itself, on your action only,
   and lays the answer next to the static "one full build needs" table.

   Endfield only for now. The result is shaped per game so 明日方舟 / 鸣潮 can be
   added later without changing the shape:

     { "取自": "HH:MM",
       games: [ { game: "终末地", gameId: "endfield", caliber, footnote, source, built, gameLevel,
                  sections: ["通用", "高阶素材", "采集", "经验与货币"], lagMinutes: 30, lagNote,
                  standard: {charId, name, rarity, releasedAt, weapon}, standards: [...], "错误": "",
                  rows: [ { id, name, rarity, icon, have, need, servings, section,
                            group, stage, note, virtual, sumInto, exp } ] } ] }

   * section   - which heading the row sits under, in `sections` order; a row with
                 section null (the exp cards) is folded into 干员经验 / 武器经验 and not shown
   * footnote  - the one-line caption for 人份 (already worded for the page)
   * lagNote   - Skland's own statement that its depot copy runs about 30 minutes behind
                 the game (the official calculator page says so); lagMinutes is the number

   * have      - what the account holds now (森空岛 calculate/user-game-data itemCount;
                 a material the account has none of is ABSENT there, so absent = 0)
   * need      - the build standard's full build, from data/need.json (built by
                 scripts/mac/build-need-tables.py): 0 when that build does not use the
                 material, null when it is not a build material at all (exp cards, the box)
   * standards - data/need.json carries games[].standards[] (today: the newest six-star
                 with her signature weapon); setStandard(charId) picks one and the choice
                 stays in this phone's localStorage; standards() lists them for a picker
   * servings  - have ÷ need, one decimal, null when there is no need
   * virtual   - the two exp rows (exp:char / exp:weapon): have = Σ count × exp of the
                 exp materials (rows carrying sumInto), because the game spends exp,
                 not cards
   * icon      - material-list's icon URL (bbs.hycdn.cn), the same picture the
                 official calculator shows

   Credentials and signing are Stamina's (stamina.js): the 森空岛 session the machine
   handed over in the snapshot, and skRefresh / skGet - the signing code exists once.
   Reads happen only when the page asks (open / pull-to-refresh / 刷新); repeats within
   a minute reuse the last answer. No timers.

   The material-list (names, rarity, icons) is cached in localStorage for seven days
   and refetched early only when the inventory names an id the cache does not know. */
(function () {
  const ZONAI_INV = "/web/v1/game/endfield/calculate/user-game-data";
  const ZONAI_MAT = "/web/v1/game/endfield/calculate/material-list";
  const NEED_URL = "data/need.json";
  const LS_MAT = "ark-remote-matlist";
  const LS_STD = "ark-remote-need-standard";
  const MIN_GAP_MS = 60 * 1000;
  const MAT_MAX_AGE_MS = 7 * 24 * 3600 * 1000;
  const GAME = "终末地", GAME_ID = "endfield";

  const Inventory = { data: null, at: 0, busy: false, need: null, err: "" };

  /* The static need table, revalidated against the server on every read (the
     file changes only when a new operator appears; `no-cache` still asks once). */
  async function loadNeed(force = false) {
    const r = await fetch(NEED_URL, { cache: force ? "reload" : "no-cache" });
    if (!r.ok) throw new Error("需求表拿不到（" + r.status + "）");
    const j = await r.json();
    if (!j || !Array.isArray(j.games)) throw new Error("需求表格式不对");
    Inventory.need = j;
    return j;
  }
  function needFor(gameId) {
    const n = Inventory.need;
    return n && n.games.find((g) => g.gameId === gameId) || null;
  }
  /* The build standards of a game (games[].standards[]), for a picker. */
  function standards(gameId = GAME_ID) {
    const g = needFor(gameId);
    return ((g && g.standards) || []).map((s) => ({ charId: s.charId, name: s.name, rarity: s.rarity, releasedAt: s.releasedAt,
                                                    weapon: s.weapon && s.weapon.name, caliber: s.caliber }));
  }
  function chosenStandard(gameId = GAME_ID) {
    try { return localStorage.getItem(LS_STD + ":" + gameId) || ""; } catch { return ""; }
  }
  /* Pick a standard by charId; "" goes back to the file's default. Rows are recomputed on the next refresh(true). */
  function setStandard(charId, gameId = GAME_ID) {
    try { if (charId) localStorage.setItem(LS_STD + ":" + gameId, charId); else localStorage.removeItem(LS_STD + ":" + gameId); } catch {}
  }
  /* The standard in force: the chosen one if the file still has it, else the file's default. */
  function standardFor(g) {
    const list = (g && g.standards) || [];
    const want = chosenStandard(g && g.gameId);
    return list.find((s) => s.charId === want) || list.find((s) => s.charId === g.standard) || list[0] || null;
  }

  // ---- material-list cache ----
  function matFromStore() {
    try { return JSON.parse(localStorage.getItem(LS_MAT) || "null"); } catch { return null; }
  }
  function matToStore(list) {
    try { localStorage.setItem(LS_MAT, JSON.stringify({ at: Date.now(), list })); } catch {}
  }
  /* {id: {name, rarity, icon, exp, kind}} for all 40 materials; names stripped
     (they carried a trailing newline on 2026-08-28). */
  function flattenMaterials(d) {
    const out = {};
    for (const kind of ["charExpMaterials", "weaponExpMaterials", "materials"]) {
      for (const [id, m] of Object.entries((d && d[kind]) || {})) {
        out[id] = { name: String(m.name || "").trim(), rarity: m.rarity ? Number(m.rarity.value) : null,
                    icon: m.icon || "", exp: Number(m.exp) || 0, kind };
      }
    }
    return out;
  }
  async function materialList(sk, ts, force = false) {
    const c = matFromStore();
    if (!force && c && c.list && Date.now() - c.at < MAT_MAX_AGE_MS) return c.list;
    const list = flattenMaterials(await Stamina.skGet(sk, ts, ZONAI_MAT));
    matToStore(list);
    return list;
  }

  // ---- one game ----
  function servingsOf(have, need) {
    if (!need || !(need > 0)) return null;
    return Math.floor((have / need) * 10) / 10;
  }
  function rowOf(base, have, mat) {
    const m = mat[base.id] || {};
    return {
      id: base.id, name: base.name || m.name || base.id,
      rarity: base.rarity != null ? base.rarity : (m.rarity != null ? m.rarity : null),
      icon: base.icon || m.icon || "",
      have, need: base.need == null ? null : base.need, servings: servingsOf(have, base.need),
      group: base.group == null ? null : base.group, stage: base.stage == null ? null : base.stage,
      note: base.note == null ? null : base.note,
      virtual: !!base.virtual, sumInto: base.sumInto || null, exp: base.exp == null ? null : base.exp,
      section: base.section == null ? null : base.section,
    };
  }
  /* need rows + live counts -> rows. Exp materials add count × exp into their
     virtual row; ids the need table does not know are appended with need null. */
  function rowsFor(needGame, counts, mat) {
    const base = (needGame && needGame.rows) || [];
    const rows = [];
    const expSum = {};
    for (const b of base) {
      if (b.sumInto) expSum[b.sumInto] = (expSum[b.sumInto] || 0) + (Number(counts[b.id]) || 0) * (Number(b.exp) || 0);
    }
    for (const b of base) {
      const have = b.virtual ? (expSum[b.id] || 0) : (Number(counts[b.id]) || 0);
      rows.push(rowOf(b, have, mat));
    }
    const known = new Set(base.map((b) => b.id));
    for (const [id, n] of Object.entries(counts || {})) {
      if (known.has(id)) continue;
      rows.push(rowOf({ id, name: (mat[id] && mat[id].name) || id, need: null }, Number(n) || 0, mat));
    }
    return rows;
  }
  async function endfield(sk) {
    const g = { game: GAME, gameId: GAME_ID, "错误": "", rows: [] };
    const needGame = needFor(GAME_ID);
    const std = standardFor(needGame);
    if (needGame) {
      g.caliber = (std && std.caliber) || needGame.caliber; g.footnote = (std && std.footnote) || needGame.footnote || "";
      g.source = needGame.source; g.built = Inventory.need.built;
      g.sections = needGame.sections || []; g.lagMinutes = needGame.lagMinutes == null ? null : needGame.lagMinutes; g.lagNote = needGame.lagNote || "";
      g.standard = std ? { charId: std.charId, name: std.name, rarity: std.rarity, releasedAt: std.releasedAt, weapon: std.weapon && std.weapon.name } : null;
      g.standards = standards(GAME_ID);
    }
    const needRows = std ? { rows: std.rows } : needGame;
    try {
      if (!sk.efRole) throw new Error("密钥串里没有终末地的角色");
      const ts = await Stamina.skRefresh(sk);
      const d = await Stamina.skGet(sk, ts, `${ZONAI_INV}?roleId=${encodeURIComponent(sk.efRole)}&serverId=${encodeURIComponent(sk.efServer || "1")}`);
      const counts = ((d.userGameData || {}).itemCount) || {};
      if (!Object.keys(counts).length) throw new Error("森空岛没给终末地的仓库：" + Object.keys(d.userGameData || d).slice(0, 6).join("、"));
      let mat = await materialList(sk, ts);
      const known = new Set(((needRows && needRows.rows) || []).map((b) => b.id));
      if (Object.keys(counts).some((id) => !known.has(id) && !mat[id])) mat = await materialList(sk, ts, true);
      g.rows = rowsFor(needRows, counts, mat);
      g.gameLevel = (d.userGameData || {}).gameLevel;
    } catch (e) { g["错误"] = e.message; }
    return g;
  }

  // ---- entry ----
  /* One read. `force` skips the one-minute reuse. Returns the object described at the top. */
  async function refresh(force = false) {
    const t = Stamina.tokens || Stamina.loadTokens();
    if (!force && Inventory.data && Date.now() - Inventory.at < MIN_GAP_MS) return Inventory.data;
    if (Inventory.busy) return Inventory.data;
    Inventory.busy = true;
    try {
      const d = new Date(); const p = (x) => String(x).padStart(2, "0");
      const out = { "取自": `${p(d.getHours())}:${p(d.getMinutes())}`, games: [] };
      try { await loadNeed(force); } catch (e) { Inventory.err = e.message; }
      out.games.push(t && t.sk ? await endfield(t.sk) : { game: GAME, gameId: GAME_ID, "错误": "没配森空岛", rows: [] });
      Inventory.data = out;
      Inventory.at = Date.now();
      return out;
    } finally { Inventory.busy = false; }
  }
  function status() {
    const t = Stamina.tokens || Stamina.loadTokens();
    return t && t.sk ? "森空岛" : "";
  }

  Object.assign(Inventory, { refresh, loadNeed, needFor, rowsFor, flattenMaterials, servingsOf, status, standards, setStandard, chosenStandard });
  window.Inventory = Inventory;
})();
